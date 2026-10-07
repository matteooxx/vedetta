"""Reading the job mailbox for outcomes.

The gap this fills is measurable: of 92 applications in the operator's tracker, 50 sit
with no recorded outcome. Some are silent rejections, some are still live, and from
the tracker alone there is no way to tell. Mail is the one channel where an outcome
*always* arrives — a posting closing says nothing about your application, a rejection
email does.

Four limits, and they are what make reading someone's inbox defensible:

**It reports observations. It never writes to the trackers.** Those are hand-curated
and authoritative (ADR-0007). A program guessing "rejected" from a phrase and writing
it into months of careful prose would be vandalism.

**It classifies with rules, not a model.** "Unfortunately" plus a known applicant-
tracking sender is a rule anyone can read, correct, and disagree with. A model's
verdict would have to be trusted (ADR-0006).

**It stores the derived observation, not the message.** Sender, subject, date,
classification, and the phrase that triggered it. No bodies.

**It proposes; a human accepts.** An observation never moves a triage stage on its
own. The ladder exists precisely so that a stage change means somebody decided.

Read-only IMAP. Nothing is marked read, moved, or deleted.
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .labels.engine import now_iso

# Senders that are almost always an applicant-tracking system talking on behalf of an
# employer. Used as corroboration, never on its own: a rejection from a person's own
# address is still a rejection.
ATS_SENDERS = (
    "greenhouse.io", "smartrecruiters.com", "myworkday.com", "myworkdayjobs.com",
    "ashbyhq.com", "lever.co", "hire.lever.co", "icims.com", "successfactors.com",
    "taleo.net", "eightfold.ai", "phenompeople.com", "workable.com", "breezy.hr",
    "recruitee.com", "teamtailor.com", "bamboohr.com", "jazz.co", "avature.net",
    "jobvite.com", "oraclecloud.com", "csod.com", "gupy.io", "hrmos.co",
)

# Ordered: the first family whose pattern matches wins, so a rejection that also
# contains the word "interview" is still a rejection.
CLASSIFIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("rejected", "rejected", (
        r"\bunfortunately\b",
        r"\bnot (?:be )?(?:moving|progress\w*|proceed\w*|taking)\b",
        r"\bdecided (?:not to|to proceed with other)\b",
        r"\bwe (?:have )?(?:chosen|selected) (?:another|other)\b",
        r"\bno longer under consideration\b",
        r"\bwill not be (?:moving|proceeding|progressing)\b",
        r"\bregret to inform\b",
        r"\bwe have filled\b",
        r"\bwithdrawn? (?:the|this) (?:role|position|requisition)\b",
    )),
    ("offer", "offer", (
        r"\b(?:job |employment )?offer\b",
        r"\bdelighted to offer\b",
        r"\bpleased to offer\b",
        r"\boffer letter\b",
    )),
    ("interview", "interview", (
        r"\binterview\b",
        r"\bschedule (?:a|your) (?:call|chat|conversation)\b",
        r"\bnext (?:step|stage)s?\b",
        r"\bspeak(?:ing)? (?:with|to) (?:you|the team)\b",
        r"\bavailability\b.{0,40}\b(?:call|chat|meeting)\b",
        r"\btechnical (?:screen|assessment|exercise)\b",
    )),
    ("screening", "screening", (
        r"\bscreening\b",
        r"\brecruiter (?:call|screen|chat)\b",
        r"\bshortlist\w*\b",
        r"\bmoving (?:you )?forward\b",
        r"\bprogress\w* (?:your|to the next)\b",
    )),
    ("acknowledged", None, (
        r"\b(?:thank you for|thanks for) (?:your )?(?:applying|application|interest)\b",
        r"\bwe (?:have )?received your application\b",
        r"\bapplication (?:received|submitted|confirmation)\b",
        r"\bwe are reviewing\b",
    )),
)

COMPILED = tuple(
    (name, stage, tuple(re.compile(p, re.I) for p in patterns))
    for name, stage, patterns in CLASSIFIERS
)


@dataclass
class Observation:
    message_id: str
    sender: str
    subject: str
    received_at: str | None
    kind: str                     # rejected | offer | interview | screening | acknowledged
    suggested_stage: str | None   # a proposal only; never applied automatically
    evidence: str                 # the phrase that decided it
    from_ats: bool
    employer_guess: str | None = None
    posting_id: int | None = None
    match_confidence: float = 0.0
    raw_headers: dict = field(default_factory=dict)


class MailboxNotConfigured(RuntimeError):
    pass


@dataclass
class MailboxConfig:
    host: str = "imap.gmail.com"
    port: int = 993
    user: str = ""
    password: str = ""
    folder: str = "INBOX"
    days: int = 30

    @classmethod
    def from_env(cls, settings: dict | None = None) -> "MailboxConfig":
        """Credentials from the environment only, never from a configuration file.

        The same Gmail app password serves sending and reading, so there is one secret
        to create and one to rotate.
        """
        settings = settings or {}
        user = (os.environ.get("VEDETTA_IMAP_USER")
                or os.environ.get("VEDETTA_SMTP_USER")
                or settings.get("user") or "")
        password = (os.environ.get("VEDETTA_IMAP_PASSWORD")
                    or os.environ.get("VEDETTA_SMTP_PASSWORD") or "")
        return cls(
            host=os.environ.get("VEDETTA_IMAP_HOST") or settings.get("host") or "imap.gmail.com",
            port=int(os.environ.get("VEDETTA_IMAP_PORT") or settings.get("port") or 993),
            user=user,
            password=password,
            folder=os.environ.get("VEDETTA_IMAP_FOLDER") or settings.get("folder") or "INBOX",
            days=int(os.environ.get("VEDETTA_IMAP_DAYS") or settings.get("days") or 30),
        )

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)


# ------------------------------------------------------------------ classification

def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in email.header.decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(charset or "utf-8", "replace"))
            except LookupError:
                parts.append(text.decode("utf-8", "replace"))
        else:
            parts.append(text)
    return " ".join(parts).strip()


def classify(subject: str, sender: str, snippet: str = "") -> tuple[str, str | None, str] | None:
    """Return (kind, suggested stage, the phrase that decided it), or None.

    The subject carries most of the signal and is cheap; a short snippet is accepted
    for the cases where it does not, but no message body is ever stored.
    """
    haystack = f"{subject}\n{snippet}"
    for kind, stage, patterns in COMPILED:
        for pattern in patterns:
            found = pattern.search(haystack)
            if found:
                return kind, stage, found.group(0)
    return None


def from_ats(sender: str) -> bool:
    lowered = (sender or "").lower()
    return any(domain in lowered for domain in ATS_SENDERS)


# ------------------------------------------------------------------------ fetching

def fetch(config: MailboxConfig, limit: int = 400) -> list[Observation]:
    """Read recent messages and return what looks like an application outcome.

    Opened read-only: `select(readonly=True)` plus `BODY.PEEK` so nothing is marked
    read, moved or deleted. Someone else's mailbox is not ours to tidy.
    """
    if not config.configured:
        raise MailboxNotConfigured(
            "no IMAP credentials: set VEDETTA_SMTP_PASSWORD (a Gmail app password "
            "serves both sending and reading) and VEDETTA_SMTP_USER")

    since = (datetime.now(timezone.utc) - timedelta(days=config.days)).strftime("%d-%b-%Y")
    observations: list[Observation] = []

    client = imaplib.IMAP4_SSL(config.host, config.port)
    try:
        client.login(config.user, config.password)
        client.select(config.folder, readonly=True)
        status, data = client.search(None, "SINCE", since)
        if status != "OK":
            return []
        ids = (data[0] or b"").split()[-limit:]
        for message_id in ids:
            status, payload = client.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1])
            subject = _decode(message.get("Subject"))
            sender = _decode(message.get("From"))
            verdict = classify(subject, sender)
            if verdict is None:
                continue
            kind, stage, evidence = verdict
            observations.append(Observation(
                message_id=(message.get("Message-ID") or f"imap-{message_id.decode()}").strip(),
                sender=sender,
                subject=subject,
                received_at=_as_iso(message.get("Date")),
                kind=kind,
                suggested_stage=stage,
                evidence=evidence,
                from_ats=from_ats(sender),
            ))
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return observations


def _as_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------------ matching

def attach(conn, observations: list[Observation]) -> dict:
    """Store observations and try to match each to a posting.

    Matching is by employer name appearing in the sender or the subject, narrowed to
    postings the reader has actually applied to. An unmatched observation is stored
    and reported as unmatched rather than guessed at: a rejection attributed to the
    wrong employer is worse than one attributed to none.
    """
    employers = conn.execute(
        """SELECT e.id, e.display_name FROM employer e
           WHERE EXISTS (SELECT 1 FROM posting p JOIN triage t ON t.posting_id = p.id
                         WHERE p.employer_id = e.id)"""
    ).fetchall()

    stats = {"stored": 0, "matched": 0, "unmatched": 0, "already": 0}
    for observation in observations:
        exists = conn.execute(
            "SELECT 1 FROM mail_observation WHERE message_id=?",
            (observation.message_id,)).fetchone()
        if exists:
            stats["already"] += 1
            continue

        haystack = f"{observation.sender} {observation.subject}".lower()
        best = None
        for row in employers:
            name = (row["display_name"] or "").lower()
            if len(name) >= 3 and name in haystack:
                best = row
                break
        if best is not None:
            observation.employer_guess = best["display_name"]
            observation.match_confidence = 0.7 if observation.from_ats else 0.5
            candidate = conn.execute(
                """SELECT p.id FROM posting p JOIN triage t ON t.posting_id = p.id
                   WHERE p.employer_id = ? ORDER BY t.decided_at DESC LIMIT 1""",
                (best["id"],)).fetchone()
            if candidate:
                observation.posting_id = candidate[0]
            stats["matched"] += 1
        else:
            stats["unmatched"] += 1

        conn.execute(
            """INSERT INTO mail_observation
                 (message_id, sender, subject, received_at, kind, suggested_stage,
                  evidence, from_ats, employer_guess, posting_id, match_confidence,
                  seen_at, accepted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (observation.message_id, observation.sender, observation.subject,
             observation.received_at, observation.kind, observation.suggested_stage,
             observation.evidence, int(observation.from_ats),
             observation.employer_guess, observation.posting_id,
             observation.match_confidence, now_iso()),
        )
        stats["stored"] += 1
    conn.commit()
    return stats


def pending(conn, limit: int = 100) -> list[dict]:
    """Observations awaiting a human. Nothing here has changed any stage."""
    rows = conn.execute(
        """SELECT m.*, e.display_name AS employer, p.title AS posting_title
           FROM mail_observation m
           LEFT JOIN posting p ON p.id = m.posting_id
           LEFT JOIN employer e ON e.id = p.employer_id
           WHERE m.accepted = 0
           ORDER BY m.received_at DESC, m.id DESC
           LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]
