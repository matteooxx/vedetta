"""T5: a source parameter travels from the watchlist to the adapter.

The defect: a key an adapter reads from its `source` dict, written in the watchlist,
is accepted, saved, and lost before it arrives. `configstore.KNOWN_KEYS` admits
`sitemap_include`, `sitemap_exclude` and `language` (configstore.py:169-171), so the
interface saves the file; `SitemapAdapter.fetch` reads them (adapters/sitemap.py:78-82);
but `sync_watchlist` writes only the columns of `source` (config.py:153-171) and
`verified_sources` hands `fetch` a row of that table (run.py:67-74). A key that is not
a column does not exist at runtime: `language` is always None, the language always
"en", and nothing says so.

The contract these tests set, which P3 implements: **every parameter an adapter
declares reaches `fetch` inside the `source` dict, under its own name, with the value
the watchlist gave it** - on the first sync that creates the row and on every later
sync that updates it.

How this file is built, and why:

* The whole path is the real one, from YAML text: `configstore.save` (what the
  interface calls) -> `config.load` -> `sync_watchlist` -> `run.execute` ->
  `verified_sources` -> `poll` -> `fetch`. Only `fetch` is replaced, by a subclass of
  the real adapter that records the dict it is given and returns nothing. A subclass
  rather than a stand-in, so that whatever P3 puts on the class (`params`) is still
  there if `poll` starts to read it.
* The database is built from the frozen production schema
  (tests/fixtures/schema_ae75d5e.sql) and then opened with `db.connect`, because the
  database on the NAS already exists: a parameter that reaches a fresh database only
  is a parameter that reaches nobody.
* Each test syncs twice, with different values, and runs after each sync. The second
  sync goes through `ON CONFLICT ... DO UPDATE`, which is what happens on the NAS
  every morning, and which today already drops one field (`discovered_by`, written on
  insert, never updated - photographed below).
* Preconditions use `_precondition` (`pytest.fail`), not `assert`. The known defects
  are `xfail(strict=True, raises=AssertionError)`, so a setup that no longer reaches
  `fetch` shows up red instead of being counted as the expected failure.

Since P3: the parameters come from `declared_params()`, which reads the adapters'
own `params`, and the main test runs once per (platform, parameter). Those without a
column are stored as JSON in `source.params` by `sync_watchlist` and spread back into
the dict by `db.source_dict`, the one place all three `SELECT s.*` readers go through.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from vedetta import config as config_mod
from vedetta import configstore
from vedetta import db as db_mod
from vedetta import run as run_mod

FROZEN_SCHEMA = Path(__file__).parent / "fixtures" / "schema_ae75d5e.sql"

# What the sitemap adapter reads beyond the columns of `source` today
# (adapters/sitemap.py:78-82). P3 must declare at least these on SitemapAdapter.
SITEMAP_PARAMS_TODAY = frozenset({"sitemap_include", "sitemap_exclude", "language"})


def declared_params() -> dict[str, frozenset[str]]:
    """Platform -> the source keys its adapter declares in `params`.

    Read from the adapters themselves, so a parameter declared tomorrow is tested
    tomorrow without anyone editing this file. Includes the two that are columns
    (`job_url_pattern`, `job_url_exclude`): they must arrive too, by the other road.
    """
    return {p: cls.params for p, cls in run_mod.ADAPTERS.items() if cls.params}


def _declared_pairs() -> list[tuple[str, str]]:
    return [(p, name) for p, names in sorted(declared_params().items())
            for name in sorted(names)]


def test_the_parameters_that_worked_before_are_still_declared():
    # Without this, dropping a name from SitemapAdapter.params would silently drop it
    # from the parametrised test below as well.
    assert SITEMAP_PARAMS_TODAY <= declared_params().get("sitemap", frozenset())


# Two values per parameter: one for the sync that creates the row, one for the sync
# that updates it. A parameter P3 adds without an entry here gets a placeholder string,
# which is enough to see it arrive.
SAMPLES = {
    "sitemap_include": (r"/ca/fr/", r"/global/en/"),
    "sitemap_exclude": (r"/global/en/", r"/ca/fr/"),
    "language": ("fr", "de"),
}

# What a source of that platform needs besides platform, identifier and verified_on to
# be a believable watchlist entry. `fetch` is never really run, so nothing here is
# required by the test itself.
BASE = {"sitemap": {"job_url_pattern": r"/job/"}}


def _sample(name: str, round_: int) -> object:
    return SAMPLES.get(name, (f"t5-{name}-first", f"t5-{name}-second"))[round_]


def _precondition(ok: bool, message: str) -> None:
    if not ok:
        pytest.fail(f"precondition: {message}", pytrace=False)


# --- the path ----------------------------------------------------------------------

@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A config directory, a production-shaped database, and the recorded fetches."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_path = tmp_path / "existing.db"
    old = sqlite3.connect(str(db_path))
    try:
        old.executescript(FROZEN_SCHEMA.read_text(encoding="utf-8"))
        old.commit()
    finally:
        old.close()
    conn = db_mod.connect(db_path)

    calls: list[dict] = []

    def record(self, source, *args, **kwargs):
        calls.append(dict(source))
        return []

    for platform, real in list(run_mod.ADAPTERS.items()):
        monkeypatch.setitem(run_mod.ADAPTERS, platform,
                            type(f"Recording{real.__name__}", (real,), {"fetch": record}))
    try:
        yield tmp_path, config_dir, conn, calls
    finally:
        conn.close()


def _watchlist(source: dict) -> str:
    return yaml.safe_dump({"employers": [{
        "key": "acme", "display_name": "Acme", "sources": [source]}]}, sort_keys=False)


def _sync_and_run(world, source: dict) -> dict:
    """Save the watchlist as the interface does, sync it, run, return what fetch got."""
    root, config_dir, conn, calls = world
    configstore.save(config_dir, "watchlist", _watchlist(source), None)
    cfg = config_mod.load(root, config_dir)
    config_mod.sync_watchlist(conn, cfg.watchlist)
    before = len(calls)
    report = run_mod.execute(conn, cfg, trigger="test")
    got = calls[before:]
    _precondition(len(got) == 1,
                  f"fetch was called {len(got)} times, expected once for the one source")
    _precondition([p["outcome"] for p in report["polls"]] == ["empty"],
                  f"the poll did not end cleanly: {report['polls']}")
    return got[0]


def _source(platform: str, **keys) -> dict:
    return {"platform": platform, "identifier": "acme-careers",
            "verified_on": dt.date(2026, 10, 1), **BASE.get(platform, {}), **keys}


# --- green today: what is a column arrives ------------------------------------------

def test_the_columns_sync_writes_reach_fetch_on_insert_and_update(world):
    """The seven fields `sync_watchlist` writes, end to end, on insert and on update.

    Proof that the path works for what is stored, so that when the xfail below turns
    green the only thing that changed is what had to.
    """
    first = {
        "endpoint": "https://careers.example.com/",
        "job_url_pattern": r"/job/\d+",
        "job_url_exclude": r"/job/0+$",
        "discovered_by": "manifest",
        "verified_on": dt.date(2026, 10, 1),
        "verified_note": "checked by hand",
        "enabled": True,
    }
    got = _sync_and_run(world, _source("sitemap", **first))
    assert {k: got[k] for k in first} == {
        **first, "verified_on": "2026-10-01", "enabled": 1}

    # `enabled` stays true: a disabled source is never polled, so it cannot be seen
    # arriving here. Every other field changes.
    second = {
        "endpoint": "https://jobs.example.com/",
        "job_url_pattern": r"/careers/\w+",
        "job_url_exclude": r"/careers/intern",
        "discovered_by": "redirect",
        "verified_on": dt.date(2026, 11, 2),
        "verified_note": "checked again",
        "enabled": True,
    }
    got = _sync_and_run(world, _source("sitemap", **second))
    assert {k: got[k] for k in second} == {
        **second, "verified_on": "2026-11-02", "enabled": 1,
        # A photograph, not an endorsement: the upsert writes discovered_by on insert
        # and leaves it out of DO UPDATE (config.py:158-164), so an edit to it in the
        # watchlist never reaches an existing row.
        "discovered_by": "manifest"}


# --- every declared parameter, insert, update, removal ------------------------------

@pytest.mark.parametrize("platform,name", _declared_pairs())
def test_declared_params_reach_fetch_on_insert_and_update(world, platform, name):
    """One parameter, followed through three syncs of the same source.

    All of the platform's parameters are set together, so the one under test has to
    survive next to the others. The third sync removes it from the watchlist: it must
    stop arriving (or fall back to what BASE gives a column), because a parameter that
    outlives its removal keeps filtering a source the operator thinks is unfiltered.
    """
    names = sorted(declared_params()[platform])
    others = [n for n in names if n != name]

    seen, wanted = {}, {}
    for round_, when in enumerate(("insert", "update")):
        values = {n: _sample(n, round_) for n in names}
        got = _sync_and_run(world, _source(platform, **values))
        seen[when] = {n: got.get(n) for n in names}
        wanted[when] = values

    kept = {n: _sample(n, 1) for n in others}
    got = _sync_and_run(world, _source(platform, **kept))
    seen["removed"] = {n: got.get(n) for n in names}
    wanted["removed"] = {**kept, name: BASE.get(platform, {}).get(name)}

    assert seen == wanted, (
        f"{platform}.{name}: what the watchlist said is not what fetch received")


def test_the_stored_params_are_only_the_ones_without_a_column(world):
    # The asymmetry is deliberate (job_url_* stay columns, so production data does not
    # move): photograph it, so that a change to it is a decision and not an accident.
    _, _, conn, _ = world
    _sync_and_run(world, _source("sitemap", **{n: _sample(n, 0)
                                               for n in declared_params()["sitemap"]}))
    stored = conn.execute("SELECT job_url_pattern, params FROM source").fetchall()
    assert len(stored) == 1
    assert stored[0]["job_url_pattern"] == _sample("job_url_pattern", 0)
    assert sorted(json.loads(stored[0]["params"])) == sorted(SITEMAP_PARAMS_TODAY)


def test_a_source_without_params_stores_null(world):
    _, _, conn, _ = world
    _sync_and_run(world, _source("sitemap"))
    assert conn.execute("SELECT params FROM source").fetchone()[0] is None


def test_removing_the_last_parameter_of_an_existing_source_clears_it(world):
    """The removal in the test above always leaves another parameter beside the one
    removed, so `params` is never None on that update. Here the last one goes: the
    upsert writes NULL, and `language` stops reaching fetch. With
    `params=COALESCE(excluded.params, params)` the old JSON would survive, and the
    source would keep being read in French with nothing in the watchlist saying so."""
    _, _, conn, _ = world
    got = _sync_and_run(world, _source("sitemap", language="fr"))
    _precondition(got.get("language") == "fr", "the parameter arrived on insert")
    got = _sync_and_run(world, _source("sitemap"))
    rows = conn.execute("SELECT params FROM source").fetchall()
    assert len(rows) == 1 and rows[0][0] is None
    assert got.get("language") is None


def test_a_parameter_another_adapter_reads_is_refused():
    text = _watchlist(_source("greenhouse", language="fr"))
    try:
        configstore.validate("watchlist", text)
    except configstore.ConfigError as exc:
        refused = str(exc)
    else:
        refused = None
    assert refused is not None and "language" in refused, (
        "a Greenhouse source carrying `language` was accepted, and Greenhouse never "
        "reads it")
