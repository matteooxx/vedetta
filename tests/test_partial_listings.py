"""A board that changed while being read is not a broken board.

The Workday adapter refuses a listing shorter than the total the board declared on
its own first page, because 40 postings of 127 once came back silently and a partial
board looks exactly like an employer with fewer openings than it has.

Then a real run reported `listing stopped at 387 of 388 postings`. One posting had
been taken down during the minute it takes to walk a board twenty at a time. The run
threw away all 387 and the digest said "1 source failing" - and a failure notice that
is usually nothing is how a reader learns to stop reading failure notices.

So there are three states, not two, and the middle one has to behave correctly in
both directions: the postings are kept and reported, and nothing may be closed on the
strength of an incomplete listing.
"""
from __future__ import annotations

import pytest

from vedetta import db as db_mod
from vedetta import run as run_mod
from vedetta.adapters.base import AdapterError, RawPosting
from vedetta.adapters.workday import _tolerable


# --- where the line sits ---------------------------------------------------

@pytest.mark.parametrize("total,allowed", [
    (388, 3),     # the board this was found on
    (127, 2),     # the board the strict guard was built for
    (30, 2),      # small: one percent rounds to nothing, so the floor carries it
    (2000, 20),
])
def test_the_tolerance_scales_with_the_board(total, allowed):
    assert _tolerable(total) == allowed


def test_the_fault_it_was_built_for_is_still_a_fault():
    """40 of 127 - a third of the board - must never pass as a busy board."""
    assert 127 - 40 > _tolerable(127)


def test_one_posting_short_of_a_large_board_is_tolerated():
    assert 388 - 387 <= _tolerable(388)


# --- the adapter ------------------------------------------------------------

class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Client:
    """Answers the listing POSTs with a board of `declared` postings that only ever
    hands back `available` of them."""

    def __init__(self, declared, available):
        self.declared = declared
        self.available = available

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        offset, limit = json["offset"], json["limit"]
        page = [{"title": f"Role {i}", "externalPath": f"/job/{i}",
                 "locationsText": "Dublin, Ireland"}
                for i in range(offset, min(offset + limit, self.available))]
        payload = {"jobPostings": page}
        if offset == 0:
            payload["total"] = self.declared
        return _Response(payload)

    def get(self, url):
        return _Response({}, status=404)


def _fetch(monkeypatch, declared, available):
    from vedetta.adapters import workday
    monkeypatch.setattr(workday, "POLITE_DELAY", 0)
    adapter = workday.WorkdayAdapter()
    monkeypatch.setattr(adapter, "client", lambda: _Client(declared, available))
    source = {"endpoint": "https://x.wd1.myworkdayjobs.com/wday/cxs/x/Site/jobs"}
    return adapter, adapter.fetch(source, detail_budget=0)


def test_a_board_one_posting_short_still_returns_its_postings(monkeypatch):
    """The 387 used to be thrown away. They are the point of the poll."""
    adapter, items = _fetch(monkeypatch, declared=388, available=387)
    assert len(items) == 387
    assert adapter.notes, "a shortfall that is tolerated still has to be said"
    assert "1 short" in adapter.notes[0]
    assert adapter.incomplete, "the listing cannot be trusted to be the whole board"


def test_a_board_missing_a_third_of_itself_still_raises(monkeypatch):
    with pytest.raises(AdapterError) as caught:
        _fetch(monkeypatch, declared=127, available=40)
    assert "pagination is incomplete" in str(caught.value)


def test_a_complete_board_says_nothing(monkeypatch):
    adapter, items = _fetch(monkeypatch, declared=100, available=100)
    assert len(items) == 100
    assert adapter.notes == []
    assert adapter.incomplete is False


# --- what the run does with it ---------------------------------------------

class _StubAdapter:
    platform = "stub"

    def __init__(self):
        self.notes = []
        self.incomplete = False

    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        self.notes.append("listing was 1 short of its declared 4 postings")
        self.incomplete = True
        return [RawPosting(platform_key="a", title="Still Here",
                           location="Dublin, Ireland", url="https://x.invalid/a")]


class _CleanAdapter(_StubAdapter):
    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        return [RawPosting(platform_key="a", title="Still Here")]


class _TalkativeAdapter(_StubAdapter):
    """A complete listing with something worth saying about it.

    The sitemap adapter is this: it reports, correctly and on every run, which of two
    translated sitemaps it followed. Reading that as an incomplete listing would stop
    the source ever closing a posting again.
    """

    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        self.notes.append("followed one of two translated sitemaps")
        return [RawPosting(platform_key="a", title="Still Here")]


@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "v.db")
    connection.execute(
        "INSERT INTO employer (id, key, display_name) VALUES (1,'x','Example')")
    connection.execute(
        "INSERT INTO source (id, employer_id, platform, identifier, verified_on) "
        "VALUES (1,1,'stub','x','2026-10-08')")
    connection.commit()
    yield connection
    connection.close()


def _source(conn, source_id=1):
    return conn.execute(
        "SELECT s.*, e.display_name AS employer_name, e.channel AS channel "
        "FROM source s JOIN employer e ON e.id = s.employer_id "
        "WHERE s.id = ?", (source_id,)).fetchone()


def _store_an_older_posting(conn, run_id):
    conn.execute(
        "INSERT INTO posting (id, employer_id, title, title_norm, first_seen_run, "
        "last_seen_run) VALUES (1,1,'Gone Missing','gone missing',?,?)",
        (run_id, run_id))
    conn.commit()


def test_a_short_listing_is_recorded_as_partial_not_as_an_error(conn, monkeypatch):
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _StubAdapter)
    run_id = run_mod.start_run(conn, "manual", False)
    outcome, items, note = run_mod.poll(conn, run_id, _source(conn))
    assert outcome == "partial"
    assert len(items) == 1
    assert note and "1 short" in note
    row = conn.execute(
        "SELECT outcome, note, error FROM source_poll WHERE run_id=?",
        (run_id,)).fetchone()
    assert (row["outcome"], row["error"]) == ("partial", None)
    assert row["note"] == note, "the note belongs in its own column, not in `error`"


def test_nothing_is_closed_when_one_route_came_back_short(conn, monkeypatch):
    """The one case where a posting can be absent and still open. Which posting it
    was is exactly what the shortfall does not say.

    Two sources for one employer, which is the arrangement that makes this reachable:
    a single short source closes nothing anyway, because closure already needs at
    least one route to have answered cleanly. The exposure is a healthy route
    alongside a short one - the healthy one satisfies that condition, and without
    this guard the short one is read as agreement.

    The first version of this test used one source and passed with the guard
    removed. It was testing the precondition, not the guard.
    """
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _StubAdapter)
    monkeypatch.setitem(run_mod.ADAPTERS, "clean", _CleanAdapter)
    conn.execute(
        "INSERT INTO source (id, employer_id, platform, identifier, verified_on) "
        "VALUES (2,1,'clean','x','2026-10-08')")
    conn.commit()
    _store_an_older_posting(conn, run_mod.start_run(conn, "manual", False))

    run_id = run_mod.start_run(conn, "manual", False)
    assert run_mod.poll(conn, run_id, _source(conn))[0] == "partial"
    assert run_mod.poll(conn, run_id, _source(conn, 2))[0] == "ok"

    assert run_mod.close_missing(conn, run_id) == 0
    assert conn.execute(
        "SELECT closed_run FROM posting WHERE id=1").fetchone()[0] is None


def test_a_single_short_route_closes_nothing_either(conn, monkeypatch):
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _StubAdapter)
    _store_an_older_posting(conn, run_mod.start_run(conn, "manual", False))
    run_id = run_mod.start_run(conn, "manual", False)
    run_mod.poll(conn, run_id, _source(conn))
    assert run_mod.close_missing(conn, run_id) == 0


def test_a_clean_listing_still_closes_what_has_gone(conn, monkeypatch):
    """The guard has to stay narrow, or closures stop happening at all."""
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _CleanAdapter)
    _store_an_older_posting(conn, run_mod.start_run(conn, "manual", False))

    run_id = run_mod.start_run(conn, "manual", False)
    outcome, _, note = run_mod.poll(conn, run_id, _source(conn))
    assert (outcome, note) == ("ok", None)
    assert run_mod.close_missing(conn, run_id) == 1


def test_a_note_on_a_complete_listing_does_not_block_closures(conn, monkeypatch):
    """The distinction between a note and an incomplete listing, which the first
    version of this did not make: it inferred incompleteness from any note, so a
    source that says something true on every run would never close anything."""
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _TalkativeAdapter)
    _store_an_older_posting(conn, run_mod.start_run(conn, "manual", False))

    run_id = run_mod.start_run(conn, "manual", False)
    outcome, _, note = run_mod.poll(conn, run_id, _source(conn))
    assert outcome == "ok"
    assert note == "followed one of two translated sitemaps", (
        "the note still has to be recorded")
    assert run_mod.close_missing(conn, run_id) == 1


def test_the_digest_calls_it_short_rather_than_failed():
    from vedetta.digest import render
    report = {"run_id": 1, "seeding": False, "new": [], "seeded": [],
              "excluded": [], "excluded_reasons": {}, "closed": 0, "sources": 2,
              "unwatched": [],
              "polls": [
                  {"employer": "Example", "platform": "workday",
                   "outcome": "partial", "count": 387,
                   "note": "listing was 1 short of its declared 388 postings"},
                  {"employer": "Other", "platform": "greenhouse",
                   "outcome": "ok", "count": 12, "note": None}]}
    body = render.render_text(report)
    assert "SHORT   Example (workday)" in body
    assert "1 short of its declared 388" in body
    assert "FAILED" not in body
    # And not in the subject line: a big board loses a posting mid-walk often
    # enough that putting it there would teach the reader to skim the subject.
    assert "failing" not in render.subject(report)
