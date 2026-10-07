"""Triage stages.

Three flags could not answer "what is in flight", which is the question that matters
once more than a handful of applications are out. So the state is an **ordered**
ladder with the date of each move recorded.

Two deliberate limits:

**Vedetta's ladder stops being authoritative after `applied`.** The operator keeps a
hand-written tracker whose prose carries far more than a status word — declared gaps,
the exact wording used, why a deviation was accepted. That file stays authoritative
(ADR-0007). The stages past `applied` exist so the interface can show what is in
flight, not to replace the record.

**Nothing here is inferred.** A stage changes because a person said so. Reading
outcomes from a mailbox is a separate, approved piece of work; when it arrives it will
*propose* a stage with its evidence, and a human will still accept it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .labels.engine import now_iso


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    order: int          # 0 = not in the pipeline; higher = further along
    terminal: bool = False
    tone: str = "info"  # maps to the interface's severity colours


STAGES: tuple[Stage, ...] = (
    Stage("interested", "Interested", 1, tone="info"),
    Stage("applied", "Applied", 2, tone="positive"),
    Stage("screening", "Screening", 3, tone="positive"),
    Stage("interview", "Interview", 4, tone="positive"),
    Stage("offer", "Offer", 5, tone="positive"),
    Stage("rejected", "Rejected", 6, terminal=True, tone="blocking"),
    Stage("dismissed", "Not for me", 0, terminal=True, tone="warning"),
)

BY_KEY = {s.key: s for s in STAGES}

# What the interface offers as one-click moves. The full ladder is available from the
# select, but these are the two that get used constantly.
QUICK = ("interested", "applied", "dismissed")

# In flight: applied and past it, not yet finished.
IN_FLIGHT = tuple(s.key for s in STAGES if 2 <= s.order <= 5 and not s.terminal)


def is_valid(state: str | None) -> bool:
    return state in BY_KEY


def label_of(state: str | None) -> str:
    stage = BY_KEY.get(state or "")
    return stage.label if stage else (state or "")


def tone_of(state: str | None) -> str:
    stage = BY_KEY.get(state or "")
    return stage.tone if stage else "info"


def set_stage(conn, posting_id: int, state: str, note: str | None = None) -> None:
    """Record the current stage and append to the history.

    The history is the point of the exercise: "applied three weeks ago, interviewed
    last Tuesday" is the thing a status word on its own cannot say.
    """
    if not is_valid(state):
        raise ValueError(f"unknown stage: {state}")
    stamp = now_iso()
    conn.execute(
        """INSERT INTO triage (posting_id, state, note, decided_at) VALUES (?,?,?,?)
           ON CONFLICT(posting_id) DO UPDATE SET
             state=excluded.state, note=excluded.note, decided_at=excluded.decided_at""",
        (posting_id, state, note, stamp),
    )
    # Appended, never collapsed: moving back a stage is information too.
    conn.execute(
        """INSERT INTO triage_event (posting_id, state, note, at, source)
           VALUES (?,?,?,?,?)""",
        (posting_id, state, note, stamp, "human"),
    )
    conn.commit()


def clear(conn, posting_id: int) -> None:
    """Remove the current stage, keeping the history.

    The history survives on purpose: that you once marked something applied and then
    cleared it is a fact about your search, and deleting it would quietly rewrite it.
    """
    conn.execute("DELETE FROM triage WHERE posting_id=?", (posting_id,))
    conn.execute(
        """INSERT INTO triage_event (posting_id, state, note, at, source)
           VALUES (?,?,?,?,?)""",
        (posting_id, "cleared", None, now_iso(), "human"),
    )
    conn.commit()


def history(conn, posting_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT state, note, at, source FROM triage_event
           WHERE posting_id=? ORDER BY id""", (posting_id,)).fetchall()
    return [dict(r) for r in rows]


def pipeline(conn) -> list[dict]:
    """How many postings sit at each stage, in ladder order."""
    counts = dict(conn.execute(
        "SELECT state, count(*) FROM triage GROUP BY state").fetchall())
    out = []
    for stage in sorted(STAGES, key=lambda s: (s.order == 0, s.order)):
        out.append({"key": stage.key, "label": stage.label, "tone": stage.tone,
                    "order": stage.order, "terminal": stage.terminal,
                    "n": counts.get(stage.key, 0)})
    return out


def in_flight(conn, limit: int = 60) -> list[dict]:
    """Applications that are out and not yet resolved.

    The question three flags could not answer.
    """
    marks = ",".join("?" * len(IN_FLIGHT))
    rows = conn.execute(
        f"""SELECT p.id AS posting_id, p.title, p.url, p.location,
                   e.display_name AS employer, t.state, t.decided_at
            FROM triage t
            JOIN posting p ON p.id = t.posting_id
            JOIN employer e ON e.id = p.employer_id
            WHERE t.state IN ({marks})
            ORDER BY t.decided_at DESC
            LIMIT ?""",
        (*IN_FLIGHT, limit),
    ).fetchall()
    return [dict(r) for r in rows]
