"""Reporting what a run is doing while it does it.

A run started from the interface takes anything from a second to an hour. Blocking an
HTTP request on that is not an option, so the run happens in a background thread and
this module is how it says where it has got to.

Two levels, because one is not enough:

**Which source it is on.** Already answerable from `source_poll`, which gets a row per
source as each finishes. Nothing new needed.

**How far through a source.** On a sitemap source with 465 detail pages to read, the
first level says "0 of 36 done" for twenty minutes, which is indistinguishable from
being stuck. So adapters are handed a reporter and call it as they work.

A **heartbeat** matters as much as the progress. A run whose process died is still
marked `running` in the database, and that has to look different from a run that is
simply slow — otherwise the only way to tell is to wait and see, which is the same
problem again.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# A run that has not touched its heartbeat for this long is presumed dead. Generous
# on purpose: a single slow detail page should never make a healthy run look dead.
STALE_AFTER = timedelta(minutes=10)

# Progress events are written at most this often per source, so a 900-posting board
# does not write 900 rows nobody reads.
EVERY = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Reporter:
    """Writes progress for one run. Safe to call often; it throttles itself.

    Opens its own short-lived connection per write rather than sharing the run's.
    The run holds a long write transaction at times, and progress that blocks the
    work it is reporting on would be worse than no progress at all.
    """

    def __init__(self, db_path: str | Path, run_id: int):
        self.db_path = str(db_path)
        self.run_id = run_id
        self._counter: dict[str, int] = {}

    # ---------------------------------------------------------------- writing
    def _write(self, kind: str, detail: str, done: int | None = None,
               total: int | None = None) -> None:
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            try:
                conn.execute(
                    """INSERT INTO run_event (run_id, at, kind, detail, done, total)
                       VALUES (?,?,?,?,?,?)""",
                    (self.run_id, _now(), kind, detail, done, total))
                conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?",
                             (_now(), self.run_id))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            # Progress reporting must never be able to fail a run. Losing a line of
            # narrative is a nuisance; losing the run is the actual work.
            pass

    def source(self, employer: str, platform: str, index: int, total: int) -> None:
        self._counter.pop(f"{employer}/{platform}", None)
        self._write("source", f"{employer} ({platform})", index, total)

    def progress(self, employer: str, done: int, total: int | None,
                 what: str = "postings") -> None:
        """Called from inside an adapter. Throttled."""
        key = employer
        seen = self._counter.get(key, 0) + 1
        self._counter[key] = seen
        if done <= 1 or (total is not None and done >= total) or seen % EVERY == 0:
            shape = f"{done} of {total}" if total else str(done)
            self._write("progress", f"{employer}: {shape} {what}", done, total)

    def note(self, detail: str) -> None:
        self._write("note", detail)

    def error(self, detail: str) -> None:
        self._write("error", detail)

    def heartbeat(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            try:
                conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?",
                             (_now(), self.run_id))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            pass


# ------------------------------------------------------------------------ reading

@dataclass
class Snapshot:
    run_id: int
    state: str                 # running | finished | failed | interrupted
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None
    trigger: str
    error: str | None
    sources_total: int
    sources_done: int
    outcomes: dict
    current: str | None
    events: list[dict]
    seconds: int | None

    @property
    def percent(self) -> int:
        if not self.sources_total:
            return 0
        return min(100, round(100 * self.sources_done / self.sources_total))

    @property
    def live(self) -> bool:
        return self.state == "running"


def _age(stamp: str | None) -> timedelta | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when


def snapshot(conn, run_id: int, events: int = 12) -> Snapshot | None:
    row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    if row is None:
        return None
    run = dict(row)

    state = run.get("state") or "finished"
    heartbeat = run.get("heartbeat_at")
    if state == "running":
        age = _age(heartbeat or run.get("started_at"))
        if age is not None and age > STALE_AFTER:
            # Said plainly rather than left looking busy: a dead run that still reads
            # as "running" sends the reader back to wait for nothing.
            state = "interrupted"

    polls = conn.execute(
        "SELECT outcome, count(*) AS n FROM source_poll WHERE run_id=? GROUP BY outcome",
        (run_id,)).fetchall()
    outcomes = {r["outcome"]: r["n"] for r in polls}
    done = sum(outcomes.values())

    total = conn.execute(
        """SELECT count(*) FROM source s JOIN employer e ON e.id = s.employer_id
           WHERE s.enabled=1 AND e.enabled=1 AND s.verified_on IS NOT NULL"""
    ).fetchone()[0]

    history = [dict(r) for r in conn.execute(
        """SELECT at, kind, detail, done, total FROM run_event
           WHERE run_id=? ORDER BY id DESC LIMIT ?""", (run_id, events)).fetchall()]

    current = None
    for event in history:
        if event["kind"] in ("progress", "source", "note"):
            current = event["detail"]
            break

    elapsed = _age(run.get("started_at"))
    if run.get("finished_at"):
        start, end = _age(run["started_at"]), _age(run["finished_at"])
        if start is not None and end is not None:
            elapsed = start - end

    return Snapshot(
        run_id=run_id, state=state, started_at=run.get("started_at"),
        finished_at=run.get("finished_at"), heartbeat_at=heartbeat,
        trigger=run.get("trigger") or "manual", error=run.get("error"),
        sources_total=max(total, done), sources_done=done, outcomes=outcomes,
        current=current, events=history,
        seconds=int(elapsed.total_seconds()) if elapsed else None,
    )


def latest_running(conn) -> int | None:
    """The run in progress, if there is one. Drives the banner on every page."""
    row = conn.execute(
        "SELECT id, heartbeat_at, started_at FROM run WHERE state='running' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    age = _age(row["heartbeat_at"] or row["started_at"])
    if age is not None and age > STALE_AFTER:
        return None
    return row["id"]
