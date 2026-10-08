"""What happens to a digest once a run has produced one.

This exists because the logic lived only in the command line. A run started from
the interface recorded its postings and queued nothing, so the novelty was spent
without anybody being told: press the button, 117 postings are seen for the first
time, and the scheduled run at 05:00 finds nothing new because they are already
known. Those 117 were never going to reach an inbox.

A silent loss, in the one project built to make silence impossible - and it got in
through the newest code path rather than through any of the adapters. Both callers
now go through this function, so the two cannot drift apart again.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import run as run_mod
from . import mail, outbox, render


@dataclass
class Outcome:
    """What was done with the digest, for the caller to report in its own voice."""
    action: str          # skipped | queued | sent | unsendable
    detail: str
    subject: str
    body: str


def compose(report: dict, config) -> tuple[str, str]:
    subject = render.subject(report, config.digest.get("subject_prefix", "Vedetta"))
    return subject, render.render_text(report, config)


def dispatch(conn, config, report: dict) -> Outcome:
    """Queue or send the digest for a finished run.

    A run where every source was being seeded has no news in it, so nothing goes
    out: that would mail somebody their own back catalogue. Every other run produces
    a digest, including a quiet one, because a missing email has to keep meaning
    that something is wrong.
    """
    subject, body = compose(report, config)

    if report["seeding"] and not report["new"]:
        return Outcome("skipped", "every source was seeded on this run: "
                                  "nothing sent, by design", subject, body)

    if config.transport == "host":
        # Handed to the host rather than sent from here: the machine already has a
        # working mail configuration, so this application holds no credential of its
        # own. The scheduled runner delivers it and records the delivery, which also
        # means a delivery that fails is retried rather than lost.
        path = outbox.write(config.db_path, report["run_id"], subject, body)
        return Outcome("queued", f"digest queued for the host transport: {path}",
                       subject, body)

    try:
        result = mail.send(subject, body, config.digest)
    except mail.MailNotConfigured as exc:
        # Queued rather than only printed. An undelivered digest has to survive
        # somewhere a person can find it, and `vedetta outbox` is that place.
        path = outbox.write(config.db_path, report["run_id"], subject, body)
        return Outcome("unsendable", f"mail not configured ({exc}); queued "
                                     f"instead: {path}", subject, body)
    run_mod.mark_digest_sent(conn, report["run_id"])
    return Outcome("sent", result, subject, body)
