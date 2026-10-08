"""Whatever starts a run, the digest gets queued.

Written after the interface spent a run's novelty and reported none of it: 117
postings seen for the first time, nothing queued, and the next scheduled run finding
nothing new because they were already recorded. The unit tests were all green - the
digest code worked perfectly, and one of its two callers simply never called it.

So these tests are about the wiring, not the composition. Each one fails if a caller
stops queueing.
"""
from __future__ import annotations

import os
import time

import pytest

from vedetta import config as config_mod
from vedetta import db as db_mod
from vedetta.digest import dispatch, outbox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def setup(tmp_path, offline_config):
    cfg = config_mod.load(tmp_path, offline_config)
    conn = db_mod.connect(cfg.db_path)
    config_mod.sync_watchlist(conn, cfg.watchlist)
    yield cfg, conn
    conn.close()


def _report(run_id, seeding=False, new=None):
    return {"run_id": run_id, "seeding": seeding, "polls": [],
            "new": new or [], "seeded": [], "excluded": [],
            "excluded_reasons": {}, "closed": 0, "sources": 3, "unwatched": []}


def test_a_quiet_run_still_queues_a_digest(setup):
    """The silence has to be reported, or silence stops meaning anything."""
    cfg, conn = setup
    outcome = dispatch.dispatch(conn, cfg, _report(1))
    assert outcome.action == "queued"
    assert [p.run_id for p in outbox.pending(cfg.db_path)] == [1]


def test_a_fully_seeded_run_queues_nothing(setup):
    """A first pass is somebody's back catalogue, not news."""
    cfg, conn = setup
    outcome = dispatch.dispatch(conn, cfg, _report(2, seeding=True))
    assert outcome.action == "skipped"
    assert outbox.pending(cfg.db_path) == []


def test_a_seeding_run_that_found_news_anyway_queues_it(setup):
    cfg, conn = setup
    posting = {"employer": "X", "title": "Y", "url": "u", "labels": [],
               "score": 1, "platform": "greenhouse", "location": None,
               "published_at": None, "channel": None, "skills": None,
               "workable": True, "blocked_by": [], "posting_id": 1}
    outcome = dispatch.dispatch(conn, cfg, _report(3, seeding=True, new=[posting]))
    assert outcome.action == "queued"


def test_the_queued_digest_is_the_one_a_person_would_read(setup):
    cfg, conn = setup
    dispatch.dispatch(conn, cfg, _report(4))
    waiting = outbox.pending(cfg.db_path)[0]
    assert waiting.subject
    assert waiting.body.strip()


# --------------------------------------------------------------- the two callers

def _wait_for_the_run_to_finish(conn, run_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = conn.execute("SELECT state FROM run WHERE id=?", (run_id,)).fetchone()
        if row and row[0] != "running":
            return row[0]
        time.sleep(0.1)
    return "timed out"


def test_a_run_started_from_the_interface_queues_its_digest(tmp_path, monkeypatch,
                                                            offline_config):
    """The defect itself. Press the button, and the news must still go out.

    Nothing is polled here: the fixture's one source has no verified_on, so the run
    is quiet. A quiet run queues too, which is the whole point.
    """
    monkeypatch.setenv("VEDETTA_ROOT", str(tmp_path))
    monkeypatch.setenv("VEDETTA_CONFIG_DIR", offline_config)
    import importlib

    from vedetta.web import app as app_module
    importlib.reload(app_module)

    cfg = config_mod.load(tmp_path, offline_config)
    conn = db_mod.connect(cfg.db_path)
    config_mod.sync_watchlist(conn, cfg.watchlist)

    application = app_module.create_app()
    application.config.update(TESTING=True)
    client = application.test_client()

    location = client.post("/run").headers["Location"]
    run_id = int(location.rstrip("/").split("/")[-1])
    assert _wait_for_the_run_to_finish(conn, run_id) == "finished"

    assert [p.run_id for p in outbox.pending(cfg.db_path)] == [run_id], (
        "a run started from the interface recorded its postings and queued no "
        "digest, so nothing was ever reported")

    # And the page says so, rather than leaving the reader to wonder.
    body = client.get(location).data.decode("utf-8", "ignore")
    assert "queued" in body.lower()
    conn.close()


def test_the_run_is_only_marked_finished_once_the_digest_exists(tmp_path, monkeypatch,
                                                               offline_config):
    """Order matters: the progress page stops refreshing when the run ends, so a
    digest queued after that moment is one the reader never sees mentioned."""
    monkeypatch.setenv("VEDETTA_ROOT", str(tmp_path))
    monkeypatch.setenv("VEDETTA_CONFIG_DIR", offline_config)
    import importlib

    from vedetta.web import app as app_module
    importlib.reload(app_module)

    cfg = config_mod.load(tmp_path, offline_config)
    conn = db_mod.connect(cfg.db_path)
    config_mod.sync_watchlist(conn, cfg.watchlist)
    application = app_module.create_app()
    application.config.update(TESTING=True)

    location = application.test_client().post("/run").headers["Location"]
    run_id = int(location.rstrip("/").split("/")[-1])
    assert _wait_for_the_run_to_finish(conn, run_id) == "finished"
    # Finished is the last thing that happens, so by now the digest is already there.
    assert outbox.pending(cfg.db_path)
    conn.close()


# ------------------------------------------------- rebuilding a lost digest

def _slug(title):
    return title.lower().replace(" ", "-")


def _store_a_posting(conn, run_id, title, workable=1, blocked=None):
    employer_id = conn.execute(
        "INSERT INTO employer (key, display_name, channel) VALUES (?,?,?) "
        "RETURNING id", (_slug(title), f"Co {title}", "private")
    ).fetchone()[0]
    posting_id = conn.execute(
        "INSERT INTO posting (employer_id, title, title_norm, location, "
        "location_norm, url, first_seen_run, last_seen_run, workable, blocked_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (employer_id, title, title.lower(), "Dublin, Ireland", "dublin ireland",
         f"https://example.invalid/{_slug(title)}", run_id, run_id,
         # Joined exactly as run.label_posting writes it. The first version of
         # this helper wrote JSON instead, so the test passed against a format
         # the application never produces and the real database raised.
         workable, "; ".join(blocked or []) or None)).fetchone()[0]
    conn.execute(
        "INSERT INTO label (posting_id, rule_id, kind, severity, value, explain, "
        "produced_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (posting_id, "cluster-platform", "cluster", "good", None,
         "platform engineering", "rules", "2026-10-08T00:00:00+00:00"))
    conn.commit()
    return posting_id


def test_a_lost_digest_can_be_rebuilt_from_the_database(setup):
    """The whole point: postings already recorded are not new any more, so the only
    way they ever get reported is to reassemble the run they arrived in."""
    cfg, conn = setup
    from vedetta.digest import rebuild
    run_id = conn.execute(
        "INSERT INTO run (started_at, trigger, state) VALUES (?,?,?) RETURNING id",
        ("2026-10-08T18:30:00+00:00", "manual", "finished")).fetchone()[0]
    _store_a_posting(conn, run_id, "Platform Engineer")
    _store_a_posting(conn, run_id, "Senior Staff Director", workable=0,
                     blocked=["too senior"])

    report = rebuild.report_for(conn, cfg, run_id)
    assert report["rebuilt"] is True
    assert [p["title"] for p in report["new"]] == ["Platform Engineer"]
    assert [p["title"] for p in report["excluded"]] == ["Senior Staff Director"]
    assert report["excluded_reasons"] == {"too senior": 1}


def test_a_rebuilt_digest_says_so_where_it_cannot_be_missed(setup):
    """A rebuilt digest looks exactly like a live one, and acting on it as current
    means applying to postings that may have closed weeks ago."""
    cfg, conn = setup
    from vedetta.digest import rebuild
    run_id = conn.execute(
        "INSERT INTO run (started_at, trigger, state) VALUES (?,?,?) RETURNING id",
        ("2026-10-08T18:30:00+00:00", "manual", "finished")).fetchone()[0]
    _store_a_posting(conn, run_id, "Platform Engineer")

    report = rebuild.report_for(conn, cfg, run_id)
    subject, body = dispatch.compose(report, cfg)
    assert "[rebuilt]" in subject
    assert "REBUILT AFTER THE FACT" in body


def test_rebuilding_an_unknown_run_is_refused_rather_than_invented(setup):
    cfg, conn = setup
    from vedetta.digest import rebuild
    with pytest.raises(LookupError):
        rebuild.report_for(conn, cfg, 999)
