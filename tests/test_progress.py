"""Tests for run progress.

The point of this feature is that a slow run and a dead run must not look the same.
So the tests concentrate there: the heartbeat, the interrupted verdict, and the fact
that reporting can never take the run down with it.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from vedetta import db as db_mod
from vedetta import progress, run as run_mod


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "vedetta.db"
    conn = db_mod.connect(path)
    conn.execute("INSERT INTO employer (id, key, display_name) VALUES (1,'acme','Acme')")
    conn.execute(
        """INSERT INTO source (id, employer_id, platform, identifier, discovered_by,
                verified_on) VALUES (1,1,'greenhouse','acme','test','2026-10-08')""")
    conn.commit()
    return path, conn


def _stamp(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec="seconds")


# --- the reporter -----------------------------------------------------------

def test_a_source_step_is_recorded(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    progress.Reporter(path, run_id).source("Acme", "greenhouse", 1, 3)
    snap = progress.snapshot(conn, run_id)
    assert snap.current == "Acme (greenhouse)"


def test_progress_inside_a_source_is_throttled(db):
    """A 900-posting board must not write 900 rows nobody reads."""
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    reporter = progress.Reporter(path, run_id)
    for done in range(1, 101):
        reporter.progress("Acme", done, 100)
    written = conn.execute(
        "SELECT count(*) FROM run_event WHERE kind='progress'").fetchone()[0]
    assert 1 < written < 20


def test_the_first_and_last_steps_are_always_written(db):
    """So a source reports immediately and is seen to have finished."""
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    reporter = progress.Reporter(path, run_id)
    reporter.progress("Acme", 1, 3)
    reporter.progress("Acme", 2, 3)
    reporter.progress("Acme", 3, 3)
    details = [r[0] for r in conn.execute(
        "SELECT detail FROM run_event WHERE kind='progress' ORDER BY id")]
    assert "Acme: 1 of 3 postings" in details
    assert "Acme: 3 of 3 postings" in details


def test_reporting_touches_the_heartbeat(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?", (_stamp(hours=2), run_id))
    conn.commit()
    progress.Reporter(path, run_id).note("still here")
    assert progress.snapshot(conn, run_id).state == "running"


def test_a_reporting_failure_cannot_take_the_run_down(db, tmp_path):
    """Losing a line of narrative is a nuisance. Losing the run is the actual work."""
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    broken = progress.Reporter(tmp_path / "nonexistent" / "no.db", run_id)
    broken.note("this cannot be written")      # must not raise
    broken.progress("Acme", 1, 2)
    broken.heartbeat()


# --- the interrupted verdict ------------------------------------------------

def test_a_run_still_working_reads_as_running(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    assert progress.snapshot(conn, run_id).state == "running"
    assert progress.snapshot(conn, run_id).live is True


def test_a_run_whose_heartbeat_went_cold_reads_as_interrupted(db):
    """The whole point. A dead run that still says `running` sends the reader back to
    wait for nothing."""
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?", (_stamp(hours=1), run_id))
    conn.commit()
    snap = progress.snapshot(conn, run_id)
    assert snap.state == "interrupted"
    assert snap.live is False


def test_a_finished_run_is_not_second_guessed(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?", (_stamp(days=3), run_id))
    conn.commit()
    run_mod.finish_run(conn, run_id, "finished")
    assert progress.snapshot(conn, run_id).state == "finished"


def test_a_failure_is_recorded_with_its_reason(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    run_mod.finish_run(conn, run_id, "failed", "RuntimeError: boom")
    snap = progress.snapshot(conn, run_id)
    assert snap.state == "failed" and "boom" in snap.error


# --- the banner -------------------------------------------------------------

def test_a_live_run_is_offered_on_every_page(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    assert progress.latest_running(conn) == run_id


def test_a_dead_run_is_not_offered(db):
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    conn.execute("UPDATE run SET heartbeat_at=? WHERE id=?", (_stamp(hours=1), run_id))
    conn.commit()
    assert progress.latest_running(conn) is None


def test_no_run_means_no_banner(db):
    path, conn = db
    assert progress.latest_running(conn) is None


# --- counting ---------------------------------------------------------------

def test_the_count_comes_from_polls_already_written(db):
    """No new bookkeeping: source_poll gets a row per source as each finishes."""
    path, conn = db
    run_id = run_mod.start_run(conn, "manual", False)
    conn.execute(
        """INSERT INTO source_poll (run_id, source_id, outcome, item_count)
           VALUES (?,1,'ok',12)""", (run_id,))
    conn.commit()
    snap = progress.snapshot(conn, run_id)
    assert snap.sources_done == 1
    assert snap.outcomes == {"ok": 1}
    assert snap.percent == 100


def test_percent_is_zero_rather_than_an_error_with_no_sources(tmp_path):
    conn = db_mod.connect(tmp_path / "empty.db")
    run_id = run_mod.start_run(conn, "manual", False)
    assert progress.snapshot(conn, run_id).percent == 0


def test_an_unknown_run_is_none_rather_than_an_exception(db):
    path, conn = db
    assert progress.snapshot(conn, 9999) is None
