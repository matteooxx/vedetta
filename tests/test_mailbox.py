"""Tests for mailbox classification and matching. No network, no mailbox.

Classification is rules over a subject line, which means it is right often rather
than always — so what matters is that it is wrong in the safe direction: a message it
cannot place is reported as unplaced, and nothing it decides moves a stage on its own.
"""
from __future__ import annotations

import pytest

from vedetta import db as db_mod
from vedetta import mailbox, triage


# --- classification --------------------------------------------------------

@pytest.mark.parametrize("subject,kind", [
    ("Unfortunately we will not be moving forward", "rejected"),
    ("Your application to Acme — update", None),
    ("We regret to inform you", "rejected"),
    ("We have decided to proceed with other candidates", "rejected"),
    ("Invitation to interview for Cloud Engineer", "interview"),
    ("Let's schedule a call", "interview"),
    ("Next steps for your application", "interview"),
    ("Recruiter screen — availability?", "screening"),
    ("We are delighted to offer you the position", "offer"),
    ("Thank you for applying to Acme", "acknowledged"),
    ("We have received your application", "acknowledged"),
])
def test_subjects_are_classified(subject, kind):
    out = mailbox.classify(subject, "jobs@example.com")
    assert (out[0] if out else None) == kind


def test_a_rejection_wins_over_the_word_interview():
    """Order matters: a rejection that mentions the interview you had is a rejection."""
    out = mailbox.classify(
        "Unfortunately, after your interview, we will not be moving forward",
        "noreply@greenhouse.io")
    assert out[0] == "rejected"


def test_the_deciding_phrase_is_reported():
    """So a wrong classification can be argued with rather than just disbelieved."""
    kind, stage, evidence = mailbox.classify("Unfortunately no", "x@y.com")
    assert evidence.lower() == "unfortunately"


def test_an_acknowledgement_proposes_no_stage():
    """A confirmation that an application arrived is not progress."""
    kind, stage, _ = mailbox.classify("Thank you for applying", "x@y.com")
    assert kind == "acknowledged" and stage is None


def test_an_unrelated_message_is_not_classified():
    assert mailbox.classify("Your invoice is ready", "billing@example.com") is None
    assert mailbox.classify("", "") is None


@pytest.mark.parametrize("sender,expected", [
    ("no-reply@greenhouse.io", True),
    ("Acme Careers <careers@myworkdayjobs.com>", True),
    ("recruiter@smartrecruiters.com", True),
    ("sarah@acme.com", False),
])
def test_hiring_platform_senders_are_recognised(sender, expected):
    """Used as corroboration only: a rejection from a person's own address is still
    a rejection."""
    assert mailbox.from_ats(sender) is expected


# --- configuration ---------------------------------------------------------

def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("VEDETTA_SMTP_USER", "me@example.com")
    monkeypatch.setenv("VEDETTA_SMTP_PASSWORD", "app-password")
    config = mailbox.MailboxConfig.from_env({})
    assert config.configured and config.user == "me@example.com"


def test_one_password_serves_sending_and_reading(monkeypatch):
    """Deliberate: one secret to create, one to rotate."""
    monkeypatch.delenv("VEDETTA_IMAP_PASSWORD", raising=False)
    monkeypatch.setenv("VEDETTA_SMTP_USER", "me@example.com")
    monkeypatch.setenv("VEDETTA_SMTP_PASSWORD", "shared")
    assert mailbox.MailboxConfig.from_env({}).password == "shared"


def test_without_a_password_it_is_not_configured(monkeypatch):
    for name in ("VEDETTA_SMTP_PASSWORD", "VEDETTA_IMAP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VEDETTA_SMTP_USER", "me@example.com")
    assert not mailbox.MailboxConfig.from_env({}).configured


def test_fetching_without_credentials_refuses_rather_than_tries(monkeypatch):
    for name in ("VEDETTA_SMTP_PASSWORD", "VEDETTA_IMAP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(mailbox.MailboxNotConfigured):
        mailbox.fetch(mailbox.MailboxConfig(user="x", password=""))


# --- storing and matching --------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    c.execute("INSERT INTO run (id, started_at, trigger) VALUES (1,'now','t')")
    c.execute("INSERT INTO employer (id, key, display_name) VALUES (1,'acme','Acme')")
    c.execute("INSERT INTO employer (id, key, display_name) VALUES (2,'other','Northwind')")
    c.execute(
        """INSERT INTO posting (id, employer_id, title, title_norm, location,
                location_norm, first_seen_run, last_seen_run)
           VALUES (1,1,'Cloud Engineer','cloud engineer','Dublin','dublin',1,1)""")
    c.commit()
    triage.set_stage(c, 1, "applied")
    return c


def _observation(**kwargs):
    base = dict(message_id="<a@b>", sender="jobs@acme.com",
                subject="Unfortunately we will not be moving forward",
                received_at="2026-10-01T10:00:00+00:00", kind="rejected",
                suggested_stage="rejected", evidence="Unfortunately",
                from_ats=False)
    base.update(kwargs)
    return mailbox.Observation(**base)


def test_an_observation_is_matched_to_an_employer_you_applied_to(conn):
    stats = mailbox.attach(conn, [_observation()])
    assert stats == {"stored": 1, "matched": 1, "unmatched": 0, "already": 0}
    row = mailbox.pending(conn)[0]
    assert row["posting_id"] == 1 and row["employer_guess"] == "Acme"


def test_an_unmatched_observation_is_stored_and_said_to_be_unmatched(conn):
    """A rejection attributed to the wrong employer is worse than one attributed to
    none."""
    stats = mailbox.attach(conn, [_observation(sender="jobs@unknown-co.com",
                                              message_id="<c@d>")])
    assert stats["unmatched"] == 1
    assert mailbox.pending(conn)[0]["posting_id"] is None


def test_an_employer_you_never_applied_to_is_not_matched(conn):
    """Matching is narrowed to postings you actually applied to, so an alert from a
    company you only watched does not become an outcome."""
    stats = mailbox.attach(conn, [_observation(sender="jobs@northwind.com",
                                              subject="Unfortunately no",
                                              message_id="<e@f>")])
    assert stats["unmatched"] == 1


def test_the_same_message_is_not_stored_twice(conn):
    mailbox.attach(conn, [_observation()])
    stats = mailbox.attach(conn, [_observation()])
    assert stats == {"stored": 0, "matched": 0, "unmatched": 0, "already": 1}


def test_storing_an_observation_does_not_move_a_stage(conn):
    """The whole posture: it proposes, a human accepts."""
    before = conn.execute("SELECT state FROM triage WHERE posting_id=1").fetchone()[0]
    mailbox.attach(conn, [_observation()])
    after = conn.execute("SELECT state FROM triage WHERE posting_id=1").fetchone()[0]
    assert before == after == "applied"
    assert [h["state"] for h in triage.history(conn, 1)] == ["applied"]


def test_pending_shows_only_what_is_unresolved(conn):
    mailbox.attach(conn, [_observation()])
    assert len(mailbox.pending(conn)) == 1
    conn.execute("UPDATE mail_observation SET accepted=1")
    conn.commit()
    assert mailbox.pending(conn) == []


def test_no_message_body_is_stored(conn):
    """Only the derived observation. The columns are the guarantee."""
    mailbox.attach(conn, [_observation()])
    columns = {row[1] for row in conn.execute("PRAGMA table_info(mail_observation)")}
    assert "body" not in columns and "text" not in columns and "html" not in columns
