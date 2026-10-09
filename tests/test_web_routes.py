"""Every route answers.

This file exists because of a specific failure: removing a feature also removed a
helper the other views depended on, and the whole interface returned 500 on every
page while the suite stayed green. 142 tests passed against an application that could
not render its own home page.

Unit tests cover the parts; nothing was checking that the parts were still wired
together. These are deliberately shallow — a status code and a trace of real content —
because their job is to notice that something is gone, not to check what it says.
"""
from __future__ import annotations

import os

import pytest

from vedetta import config as config_mod
from vedetta import db as db_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def client(tmp_path, monkeypatch, offline_config):
    # The offline configuration, because two of these tests start a run and the
    # shipped example watchlist would have them polling real company boards.
    monkeypatch.setenv("VEDETTA_ROOT", str(tmp_path))
    monkeypatch.setenv("VEDETTA_CONFIG_DIR", offline_config)
    # Imported inside the fixture so the module reads the patched environment.
    import importlib

    from vedetta.web import app as app_module
    importlib.reload(app_module)

    cfg = config_mod.load(tmp_path, offline_config)
    conn = db_mod.connect(cfg.db_path)
    config_mod.sync_watchlist(conn, cfg.watchlist)
    conn.close()

    application = app_module.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


@pytest.mark.parametrize("path", [
    "/",
    "/postings",
    "/postings?scope=all",
    "/postings?scope=excluded",
    "/postings?place=Ireland&place=Poland",
    "/postings?employer=gitlab&mode=remote&age=7d",
    "/postings?q=engineer",
    "/sources",
    "/insights",
    "/insights?weeks=4",
    "/config/profile",
    "/config/rules",
    "/config/watchlist",
    "/config/settings",
    "/health",
])
def test_every_route_answers(client, path):
    response = client.get(path)
    assert response.status_code in (200, 503), f"{path} returned {response.status_code}"


def test_the_home_page_renders_real_content(client):
    """A 200 from an error handler would still be a 200."""
    body = client.get("/").data.decode("utf-8", "ignore")
    assert "Vedetta" in body
    assert "Dashboard" in body


def test_an_unknown_configuration_file_is_a_404(client):
    assert client.get("/config/secrets").status_code == 404


def test_a_removed_feature_is_gone_rather_than_broken(client):
    """Mailbox reading was built and then removed at the operator's request."""
    assert client.get("/mail").status_code == 404


def test_triage_rejects_an_unknown_stage(client):
    assert client.post("/postings/1/triage", data={"state": "elsewhere"}).status_code == 400


def test_a_run_page_for_an_unknown_run_is_a_404(client):
    assert client.get("/runs/9999").status_code == 404


def test_run_now_returns_immediately_and_points_at_a_progress_page(client):
    """A run takes anything from a second to an hour, so the request must not wait
    for it. The browser used to sit on a white page with no way to tell a slow run
    from a dead one."""
    response = client.post("/run")
    assert response.status_code == 302
    assert "/runs/" in response.headers["Location"]


def test_the_progress_page_renders(client):
    location = client.post("/run").headers["Location"]
    body = client.get(location).data.decode("utf-8", "ignore")
    assert "What it is doing" in body


def test_health_reports_the_database(client):
    import json
    payload = json.loads(client.get("/health").data)
    assert "ok" in payload


@pytest.mark.parametrize("name", ["profile", "rules", "settings"])
def test_the_generator_prompt_has_its_own_plain_text_page(client, name):
    """A copy button would need script and this interface has none. A page of text
    answers the same need: open it, select all, paste."""
    response = client.get(f"/config/{name}/prompt.txt")
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert b"NEVER INVENT A VALUE" in response.data


def test_the_watchlist_has_no_prompt_page(client):
    assert client.get("/config/watchlist/prompt.txt").status_code == 404


def test_the_config_page_offers_the_prompt(client):
    body = client.get("/config/profile").data.decode("utf-8", "ignore")
    assert "Write this file with your own AI" in body
    assert "attach your CV" in body


def test_check_writes_nothing(client, tmp_path):
    """The whole point of a Check button. It renders a report and leaves the file
    alone, so a candidate file can be weighed before it is believed."""
    before = client.get("/config/profile").data
    response = client.post("/config/profile", data={
        "action": "check",
        "text": "locations:\n  acceptable: [Ireland]\n",
    })
    assert response.status_code == 200
    assert b"What this would do" in response.data
    assert client.get("/config/profile").data == before


def test_check_reports_a_key_nothing_reads_without_saving(client):
    response = client.post("/config/profile", data={
        "action": "check",
        "text": "location:\n  acceptable: [Ireland]\n",
    })
    assert response.status_code == 200
    body = response.data.decode("utf-8", "ignore")
    assert "would not save" in body
    assert "did you mean locations?" in body


def test_saving_a_key_nothing_reads_is_refused(client):
    """Refused rather than warned about: it saves cleanly and then does nothing,
    which is the one kind of mistake these files cannot afford."""
    response = client.post("/config/profile", data={
        "action": "save",
        "text": "location:\n  acceptable: [Ireland]\n",
    })
    body = response.data.decode("utf-8", "ignore")
    assert "Not saved" in body
