"""Tests for the triage ladder and the derived signals.

Both are about not quietly rewriting history: a stage change must leave a trail, and
a signal must be computed from what was actually observed rather than from what a
platform claims about dates.
"""
from __future__ import annotations

import pytest

from vedetta import db as db_mod
from vedetta import insights, triage


@pytest.fixture()
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    c.execute("INSERT INTO run (id, started_at, trigger) VALUES (1,'2026-01-01T00:00:00+00:00','t')")
    c.execute("INSERT INTO run (id, started_at, trigger) VALUES (2,'2026-10-01T00:00:00+00:00','t')")
    c.execute("INSERT INTO run (id, started_at, trigger) VALUES (3,'2026-10-06T00:00:00+00:00','t')")
    c.execute("INSERT INTO employer (id, key, display_name) VALUES (1,'alpha','Alpha')")
    c.execute("INSERT INTO employer (id, key, display_name) VALUES (2,'beta','Beta')")

    def posting(pid, emp, title, first, closed=None, workable=1):
        c.execute(
            """INSERT INTO posting (id, employer_id, title, title_norm, location,
                    location_norm, first_seen_run, last_seen_run, closed_run, workable)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, emp, title, title.lower(), "Dublin", "dublin", first, 3, closed, workable))

    posting(1, 1, "Cloud Engineer", 1)            # open since January - stale
    posting(2, 1, "Platform Engineer", 2)         # appeared in the window
    posting(3, 1, "SRE", 2, closed=3)             # appeared and closed in the window
    posting(4, 2, "Data Engineer", 1)             # Beta: old, still open, nothing new
    c.commit()
    return c


# --- the ladder -------------------------------------------------------------

def test_a_stage_change_is_recorded_and_appended(conn):
    triage.set_stage(conn, 1, "interested")
    triage.set_stage(conn, 1, "applied")
    assert conn.execute("SELECT state FROM triage WHERE posting_id=1").fetchone()[0] == "applied"
    assert [h["state"] for h in triage.history(conn, 1)] == ["interested", "applied"]


def test_moving_backwards_is_kept_rather_than_tidied(conn):
    """Going back a stage is information about the search, not a mistake to hide."""
    for state in ("applied", "interview", "applied"):
        triage.set_stage(conn, 1, state)
    assert [h["state"] for h in triage.history(conn, 1)] == ["applied", "interview", "applied"]


def test_clearing_keeps_the_history(conn):
    triage.set_stage(conn, 1, "applied")
    triage.clear(conn, 1)
    assert conn.execute("SELECT count(*) FROM triage WHERE posting_id=1").fetchone()[0] == 0
    assert [h["state"] for h in triage.history(conn, 1)] == ["applied", "cleared"]


def test_an_unknown_stage_is_refused(conn):
    with pytest.raises(ValueError):
        triage.set_stage(conn, 1, "probably-fine")


def test_in_flight_is_applied_and_beyond_but_not_finished(conn):
    triage.set_stage(conn, 1, "applied")
    triage.set_stage(conn, 2, "interview")
    triage.set_stage(conn, 3, "rejected")
    triage.set_stage(conn, 4, "interested")
    flight = {f["posting_id"] for f in triage.in_flight(conn)}
    assert flight == {1, 2}


def test_pipeline_counts_every_stage_in_order(conn):
    triage.set_stage(conn, 1, "applied")
    triage.set_stage(conn, 2, "applied")
    rows = triage.pipeline(conn)
    counts = {r["key"]: r["n"] for r in rows}
    assert counts["applied"] == 2 and counts["offer"] == 0
    ladder = [r["key"] for r in rows if r["order"] > 0]
    assert ladder.index("applied") < ladder.index("interview") < ladder.index("offer")


def test_the_facet_labels_come_from_the_ladder():
    """So a stage added to the ladder cannot go missing from the filter panel."""
    from vedetta.facets import TRIAGE_LABELS
    for stage in triage.STAGES:
        assert TRIAGE_LABELS[stage.key] == stage.label
    assert TRIAGE_LABELS["none"] == "Not triaged"


# --- derived signals --------------------------------------------------------

def test_activity_counts_from_when_the_watch_saw_it(conn):
    """Not from the platform's publication date: several supply none, and the ones
    that do disagree about what it means."""
    rows = {a["key"]: a for a in insights.employer_activity(conn, weeks=8)}
    assert rows["alpha"]["appeared"] == 2      # postings 2 and 3
    assert rows["alpha"]["closed"] == 1        # posting 3
    assert rows["alpha"]["net"] == 1
    assert rows["alpha"]["open_now"] == 2      # 1 and 2


def test_an_employer_with_nothing_new_shows_zero_appeared(conn):
    rows = {a["key"]: a for a in insights.employer_activity(conn, weeks=8)}
    assert rows["beta"]["appeared"] == 0
    assert rows["beta"]["open_now"] == 1


def test_stale_finds_the_long_open_posting(conn):
    stale = insights.stale(conn, days=90)
    ids = {s["posting_id"] for s in stale}
    assert 1 in ids and 4 in ids      # both open since January
    assert 2 not in ids               # opened in October


def test_stale_reports_how_long(conn):
    entry = next(s for s in insights.stale(conn, days=90) if s["posting_id"] == 1)
    assert entry["days_open"] is not None and entry["days_open"] > 200


def test_a_repost_is_a_closed_posting_coming_back_afterwards(conn):
    # posting 3 (SRE) closed in run 3; an equivalent appears later
    conn.execute("INSERT INTO run (id, started_at, trigger) VALUES (4,'2026-10-07T00:00:00+00:00','t')")
    conn.execute(
        """INSERT INTO posting (id, employer_id, title, title_norm, location,
                location_norm, first_seen_run, last_seen_run, workable)
           VALUES (5,1,'SRE','sre','Dublin','dublin',4,4,1)""")
    conn.commit()
    found = insights.reposts(conn)
    assert [r["posting_id"] for r in found] == [5]
    assert found[0]["previous_id"] == 3


def test_two_concurrent_listings_are_not_a_repost(conn):
    """A duplicate is flagged elsewhere; a repost needs the first one to have closed
    before the second appeared."""
    conn.execute(
        """INSERT INTO posting (id, employer_id, title, title_norm, location,
                location_norm, first_seen_run, last_seen_run, workable)
           VALUES (6,1,'Cloud Engineer','cloud engineer','Cork','cork',2,3,1)""")
    conn.commit()
    assert insights.reposts(conn) == []


def test_a_repost_carries_what_you_decided_last_time(conn):
    """The pointed case: a role you were turned down for, open again."""
    triage.set_stage(conn, 3, "rejected")
    conn.execute("INSERT INTO run (id, started_at, trigger) VALUES (4,'2026-10-07T00:00:00+00:00','t')")
    conn.execute(
        """INSERT INTO posting (id, employer_id, title, title_norm, location,
                location_norm, first_seen_run, last_seen_run, workable)
           VALUES (5,1,'SRE','sre','Dublin','dublin',4,4,1)""")
    conn.commit()
    assert insights.reposts(conn)[0]["previous_triage"] == "rejected"


def test_summary_is_one_call(conn):
    data = insights.summary(conn)
    assert set(data) >= {"window", "activity", "growing", "quiet", "reposts",
                         "stale", "stale_days"}
