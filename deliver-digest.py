#!/usr/bin/env python3
"""Deliver one queued digest through the machine's own mail configuration.

Called by run-vedetta.sh with a path and a recipient. Lives in the dataset on tank
rather than in /root, like the runner, because the boot pool is a single disk near end
of life and is not snapshotted.

**Why the middleware client and not `midclt`.** The payload is a whole digest — 15 KB
and rising — and passing it as a command-line argument is how the first attempt failed:

    sudo: argv[3] mismatch, expected "{"subject": "Vedetta: 16 new, ...

The handbook says this outright (api.md F-1, F-2): shell-quoting JSON into `midclt` is
a minefield, and anything non-trivial should use `truenas_api_client.Client` from a
Python file. This is that file.

Exit codes are what the runner reads: 0 delivered, 1 not. Nothing is retried here —
the outbox is the retry, and a digest that fails stays queued.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: deliver-digest.py <file> [recipient]", file=sys.stderr)
        return 2

    path = Path(argv[1])
    recipient = (argv[2].strip() if len(argv) > 2 else "")
    if not path.is_file():
        print(f"no such digest: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    subject, _, body = text.partition("\n\n")
    subject = subject.strip() or "Vedetta digest"
    if not body.strip():
        # Refusing is right: an empty digest delivered is worse than one that stayed
        # queued, because it looks like the watch ran and found nothing.
        print(f"{path} has no body; refusing to send an empty digest", file=sys.stderr)
        return 1

    payload = {"subject": subject, "text": body}
    if recipient:
        payload["to"] = [recipient]

    try:
        from truenas_api_client import Client
    except ImportError as exc:
        print(f"middleware client unavailable: {exc}", file=sys.stderr)
        return 1

    try:
        with Client() as client:
            # job=True waits for the send and raises if it failed, so a queued digest
            # is only cleared once the mail has actually gone.
            client.call("mail.send", payload, job=True)
    except Exception as exc:
        print(f"mail.send failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"delivered: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
