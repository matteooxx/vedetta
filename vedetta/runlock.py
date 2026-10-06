"""A lock so two runs cannot interleave.

The scheduled container and the interface's "run now" button write the same SQLite
database. SQLite in WAL mode tolerates concurrent readers and one writer, but two
runs polling the same sources would still produce doubled sightings and a confused
digest.

Implemented as a lock file holding the owner and a timestamp, with a stale timeout -
rather than an in-process mutex, because the two contenders are different processes
in different containers.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_AFTER = timedelta(minutes=30)


class RunInProgress(RuntimeError):
    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(
            f"a run started by {holder.get('owner', 'unknown')} at "
            f"{holder.get('started_at', 'unknown')} is still in progress")


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_stale(holder: dict) -> bool:
    started = holder.get("started_at")
    if not started:
        return True
    try:
        when = datetime.fromisoformat(started)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when > STALE_AFTER


@contextmanager
def acquire(path: str | Path, owner: str = "unknown"):
    """Take the lock, or raise RunInProgress.

    A lock older than the stale timeout is taken over: a container killed mid-run
    would otherwise block every future run, which would be a silent outage of the
    whole watch.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "owner": owner,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        holder = _read(path) or {}
        if not _is_stale(holder):
            raise RunInProgress(holder) from None
        # stale: replace it and carry on
        path.write_text(payload, encoding="utf-8")
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)

    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
