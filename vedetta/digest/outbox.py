"""Handing the digest to the host to deliver.

The server already has a working, authenticated mail configuration — it sends its own
alerts with it. Reusing that means the application needs **no credential of its own**:
nothing to create, nothing to rotate, nothing to leak.

But the application runs in a container and the host's mail is only reachable from the
host. So the two are split: the application writes the digest to an outbox, and the
host's runner script delivers it and reports back.

That split turns out to be better than sending directly, for a reason that has nothing
to do with containers. **An undelivered digest stays in the outbox.** A send that fails
is retried on the next run instead of being lost — and an unsent digest is the one
failure the reader cannot discover by reading the digest.

The file format is deliberately dull: first line the subject, blank line, then the
body. Anything can read it, including a person wondering what went out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^run-(\d+)\.txt$")


@dataclass
class Pending:
    run_id: int
    path: Path
    subject: str
    body: str


def directory(db_path: str | Path) -> Path:
    return Path(db_path).parent / "outbox"


def write(db_path: str | Path, run_id: int, subject: str, body: str) -> Path:
    out = directory(db_path)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"run-{run_id}.txt"
    # Written through a temporary file and renamed, so the runner can never read a
    # half-written digest and mail it.
    temp = path.with_suffix(".txt.tmp")
    temp.write_text(f"{subject}\n\n{body}", encoding="utf-8")
    temp.replace(path)
    return path


def pending(db_path: str | Path) -> list[Pending]:
    """Everything waiting to go out, oldest run first."""
    out = directory(db_path)
    if not out.exists():
        return []
    found: list[Pending] = []
    for path in sorted(out.glob("run-*.txt")):
        match = NAME.match(path.name)
        if not match:
            continue
        text = path.read_text(encoding="utf-8")
        subject, _, body = text.partition("\n\n")
        found.append(Pending(run_id=int(match.group(1)), path=path,
                             subject=subject.strip(), body=body))
    found.sort(key=lambda item: item.run_id)
    return found


def clear(path: str | Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
