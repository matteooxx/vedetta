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
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDETTA_ROOT", str(tmp_path))
    monkeypatch.setenv("VEDETTA_CONFIG_DIR", os.path.join(ROOT, "config"))
    # Imported inside the fixture so the module reads the patched environment.
    import importlib

    from vedetta.web import app as app_module
    importlib.reload(app_module)

    cfg = config_mod.load(tmp_path, os.path.join(ROOT, "config"))
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


def test_health_reports_the_database(client):
    import json
    payload = json.loads(client.get("/health").data)
    assert "ok" in payload
