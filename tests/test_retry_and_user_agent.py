"""What we say to other people's servers, and how many times we say it.

Two things nothing tested before, both found on 18 November 2026 while working out why
four Workday tenants had been answering 429 since the morning of the 17th.

The answer was not our volume. A single request, sent cold, came back as a Cloudflare
block page - 28,626 bytes of HTML with status 429 and no `Retry-After`. The client was
being refused, not throttled. Two things followed from that:

* `retrying` asked that same refused question **three times**, because 429 sat in
  `RETRY_ON` unconditionally. The module's own docstring says it does not retry a
  status that will not change; this was one.
* the `User-Agent` told those servers "one request per employer per day", which was
  not true: a Workday poll sends the listing plus up to `detail_budget` detail
  requests, 150 on a normal run and unlimited while seeding.

Neither of these restored the Workday polls - the block is Cloudflare's decision and
these tests make no claim about it. They are here because both statements were wrong on
their own terms, and because a false promise in a `User-Agent` is worse than no promise
at all: it is a claim made in the one place the other side will look for it.
"""
from __future__ import annotations

import httpx
import pytest

from vedetta.adapters import base as base_mod
from vedetta.adapters.base import RETRY_ON, USER_AGENT, Adapter


class _Response:
    """Only what `retrying` reads: a status and the headers."""

    def __init__(self, status: int, headers: dict | None = None):
        self.status_code = status
        self.headers = headers or {}


@pytest.fixture
def no_waiting(monkeypatch):
    """Record the sleeps instead of serving them, so the test measures the decision."""
    slept: list[float] = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda s: slept.append(s))
    return slept


def _ask(responses: list[_Response], what: str = "the listing"):
    """Run `retrying` against a canned sequence.

    Returns the answer, how many requests were sent, and what went into the record -
    the third one matters as much as the second: stopping early must not also stop
    saying so."""
    calls = {"n": 0}
    adapter = Adapter()

    def send():
        calls["n"] += 1
        return responses[min(calls["n"] - 1, len(responses) - 1)]

    answer = adapter.retrying(send, what=what)
    # `notes` is the whole surface the caller touches, and a refusal writes ONE
    # summary note into it however many times it happens. See `Adapter.refused`.
    return answer, calls["n"], adapter.notes


# --- a 429 is two different things -----------------------------------------

def test_a_429_with_a_retry_after_is_asked_again(no_waiting):
    """The platform stated a wait. That is a request, and it is honoured."""
    answer, calls, notes = _ask([_Response(429, {"Retry-After": "2"}), _Response(200)])
    assert answer.status_code == 200
    assert calls == 2
    assert no_waiting == [2.0], "the stated wait is what we waited"
    assert "the retry is what produced this listing" in notes[0]


def test_a_429_with_no_retry_after_is_asked_once(no_waiting):
    """A refusal. Asking twice more only changes how many times we knocked.

    This is the regression: before 18/11 this sent three requests to a server that had
    already said no, and the two extra ones were invisible in the record because the
    poll was reported the same either way.
    """
    answer, calls, notes = _ask([_Response(429)], what="the advert at /job/x")
    assert answer.status_code == 429, "the caller still sees the 429 it saw before"
    assert calls == 1, "exactly one request reached the server"
    assert no_waiting == [], "and nothing was slept over"
    # The Workday detail fetch swallows a non-200 on purpose, so this note is the only
    # trace that the text was refused rather than absent. Saving two requests must not
    # cost the record.
    assert len(notes) == 1, "the refusal is still written down"
    assert "/job/x" in notes[0], "and it says which request was refused"
    assert "refused with 429 and no Retry-After" in notes[0]
    assert "not asked again" in notes[0]


def test_the_block_page_shape_is_what_was_actually_measured(no_waiting):
    """The real response: 429, no Retry-After, and an HTML body from Cloudflare."""
    block = _Response(429, {"server": "cloudflare", "content-type": "text/html"})
    answer, calls, notes = _ask([block])
    assert (answer.status_code, calls) == (429, 1)
    assert notes and "refused with 429 and no Retry-After" in notes[0]


# --- everything else retries exactly as it did ------------------------------

@pytest.mark.parametrize("status", sorted(RETRY_ON - {429}))
def test_a_transient_server_fault_is_still_asked_again(status, no_waiting):
    """500/502/503/504 keep the behaviour the retry was built for."""
    answer, calls, notes = _ask([_Response(status), _Response(200)])
    assert answer.status_code == 200
    assert calls == 2
    assert "the retry is what produced this listing" in notes[0]


def test_a_404_is_still_never_retried(no_waiting):
    answer, calls, notes = _ask([_Response(404)])
    assert (answer.status_code, calls) == (404, 1)
    assert notes == [], "nothing was retried, so there is nothing to report"


def test_a_429_that_keeps_asking_for_a_wait_still_runs_out_of_attempts(no_waiting):
    """Three attempts in all, as before, when the platform keeps stating a wait."""
    answer, calls, notes = _ask([_Response(429, {"Retry-After": "1"})])
    assert (answer.status_code, calls) == (429, 3)
    # And the note must NOT claim a rescue that did not happen. A real poll of Zalando
    # wrote "the retry is what produced this listing" about seven adverts whose three
    # attempts had each answered 429.
    assert "the retry is what produced this listing" not in notes[0]
    assert "the attempts were spent" in notes[0]


# --- what we tell them we are ----------------------------------------------

def test_the_user_agent_makes_no_promise_about_how_many_requests():
    """It said "one request per employer per day", and that was false.

    `run.py` passes `detail_budget=150` on a normal run and `None` while seeding, so a
    Workday poll sends up to 151 requests per employer, and more the first time.
    """
    assert "one request per employer per day" not in USER_AGENT
    assert "per day" not in USER_AGENT, "no frequency claim the code cannot keep"
    assert "vedetta" in USER_AGENT, "it still says who is calling"


def test_the_user_agent_says_the_one_thing_the_code_does_guarantee():
    """There is no concurrency in the HTTP layer: the requests do arrive one at a time."""
    assert "one at a time" in USER_AGENT


def test_the_workday_listing_carries_the_project_user_agent():
    """A per-request header must not displace the client's identity.

    httpx merges per-request headers with the client's, so the Workday listing POST -
    which passes `Content-Type` of its own - still goes out as vedetta. This test
    exists because that was briefly misread as a defect, and a refactor that swapped
    the client for a bare `httpx.post` would make the misreading true.
    """
    with Adapter().client() as client:
        request = client.build_request(
            "POST", "https://example.invalid/wday/cxs/x/y/jobs",
            json={"limit": 20, "offset": 0, "searchText": "", "appliedFacets": {}},
            headers={"Content-Type": "application/json"},
        )
    assert request.headers["user-agent"] == USER_AGENT
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept"] == "application/json"


def test_retry_after_is_read_the_way_the_measurement_found_it():
    """No header, an unparseable one and a negative one all mean "nothing stated"."""
    assert base_mod._retry_after(httpx.Response(429)) is None
    assert base_mod._retry_after(httpx.Response(429, headers={"Retry-After": "soon"})) is None
    assert base_mod._retry_after(httpx.Response(429, headers={"Retry-After": "-5"})) is None
    assert base_mod._retry_after(httpx.Response(429, headers={"Retry-After": "3"})) == 3.0
    capped = base_mod._retry_after(httpx.Response(429, headers={"Retry-After": "99999"}))
    assert capped == base_mod.BACKOFF_CAP, "an absurd wait is capped, not slept through"


# --- a failed poll keeps its explanation ------------------------------------

def test_a_failed_poll_records_what_the_adapter_wrote_down(tmp_path, monkeypatch):
    """The notes used to be kept only when the poll succeeded.

    So a poll that failed was recorded as `error / 429 / HTTP 429` and everything the
    adapter had to say about it - whether a `Retry-After` was offered, whether it was
    asked again, which adverts were refused - was dropped. That is the one case a
    reader goes looking for an explanation, and it was the one case with none.
    """
    from vedetta import db as db_mod
    from vedetta import run as run_mod
    from vedetta.adapters.base import Adapter, AdapterError

    class _Refused(Adapter):
        def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
            self.refused("the listing at offset 0")
            raise AdapterError("HTTP 429", http_status=429)

    monkeypatch.setitem(run_mod.ADAPTERS, "refused", _Refused)

    conn = db_mod.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO employer (id, key, display_name, channel, enabled) "
                 "VALUES (1, 'e', 'E', 'private', 1)")
    conn.execute("INSERT INTO source (id, employer_id, platform, identifier, endpoint, "
                 "enabled, verified_on) VALUES (1, 1, 'refused', 'x', 'https://x/', 1, "
                 "'2026-01-01')")
    conn.commit()
    run_id = run_mod.start_run(conn, trigger="test", seeding=False)

    outcome, items, note = run_mod.poll(
        conn, run_id, {"id": 1, "employer_id": 1, "platform": "refused",
                       "identifier": "x", "endpoint": "https://x/",
                       "employer_name": "E", "params": None})

    assert outcome == "error"
    # RETURNED, not only recorded. The digest is built from what this function returns,
    # so a note that only reaches the table never reaches the reader - which is how
    # "FAILED Zendesk (workday)" stood with no reason under it for two days. A mutation
    # that put `None` back here passed every other test in the suite.
    assert note and "refused with 429 and no Retry-After" in note
    row = list(conn.execute(
        "SELECT outcome, http_status, error, note FROM source_poll WHERE run_id=?",
        (run_id,)))[0]
    assert row[0] == "error" and row[1] == 429, "the failure is recorded as before"
    assert row[2] == "HTTP 429"
    assert row[3] and "refused with 429 and no Retry-After" in row[3], (
        "and the adapter's account of it survives into the record")


# --- and the reader finally sees why -----------------------------------------

def test_a_failed_source_prints_its_reason_in_the_digest():
    """"4 failed" over four names, and nothing about why, for two days.

    SHORT and NOTE both print their explanation under the name. FAILED did not, which
    is backwards: a refusal and an outage look identical in a list of names, and they
    mean completely different things about what to do next.
    """
    from vedetta.digest import render

    report = {
        "run_id": 66, "seeding": False, "sources": 2, "new": [], "excluded": [],
        "excluded_reasons": {}, "closed": 0,
        "polls": [
            {"employer": "Zendesk", "platform": "workday", "outcome": "error",
             "count": 0, "error": "HTTP 429",
             "note": "1 request was refused with 429 and no Retry-After, so it was "
                     "not asked again: the listing at offset 0"},
            {"employer": "Other", "platform": "greenhouse", "outcome": "ok",
             "count": 12, "note": None},
        ],
    }
    body = render.render_text(report)
    assert "FAILED  Zendesk (workday)" in body
    assert "HTTP 429" in body, "the status the platform answered"
    assert "refused with 429 and no Retry-After" in body, "and what it meant"
    assert "1 failed" in body


def test_a_failed_source_with_nothing_to_add_prints_just_the_name():
    """No note, no error: the line stays as short as it always was."""
    from vedetta.digest import render

    report = {
        "run_id": 66, "seeding": False, "sources": 1, "new": [], "excluded": [],
        "excluded_reasons": {}, "closed": 0,
        "polls": [{"employer": "Quiet", "platform": "greenhouse", "outcome": "error",
                   "count": 0, "note": None}],
    }
    body = render.render_text(report)
    righe = body.splitlines()
    i = next(n for n, r in enumerate(righe) if "FAILED  Quiet (greenhouse)" in r)
    # Nothing indented under it: an absent reason is absent, and in particular it is
    # not the word "None" printed where a sentence should be.
    sotto = righe[i + 1] if i + 1 < len(righe) else ""
    assert not sotto.startswith("          "), f"unexpected reason line: {sotto!r}"


# --- six copies of a sentence is a note nobody reads ------------------------

def test_many_refusals_become_one_line_with_a_count():
    """A Workday board whose adverts are refused produces one refusal PER advert.

    The first version wrote them all out: a real poll of Zalando put six copies of the
    same sentence in the digest, 1,100 characters for one fact. This module argues in
    three other comments that a notice nobody finishes reading is worse than none, so
    the count comes first and two examples follow to keep it checkable.
    """
    a = Adapter()
    for n in range(6):
        a.refused(f"the advert at /job/City/Role-{n}")
    linea = "; ".join(a.notes)
    assert linea.startswith("6 requests were refused with 429 and no Retry-After")
    assert "so they were not asked again" in linea, "plural, and it reads as English"
    assert "/job/City/Role-0" in linea and "/job/City/Role-1" in linea
    assert "and 4 more" in linea
    assert "/job/City/Role-5" not in linea, "two examples, not six"
    assert linea.count("refused with 429") == 1, "the sentence is said once"


def test_one_refusal_reads_as_one():
    a = Adapter()
    a.refused("the listing at offset 0")
    linea = "; ".join(a.notes)
    assert linea.startswith("1 request was refused with 429")
    assert "so it was not asked again" in linea, "singular, and it reads as English"
    assert "more" not in linea


def test_refusals_and_ordinary_notes_coexist():
    """A short listing AND a refused advert are two different things to say."""
    a = Adapter()
    a.note("listing was 1 short of its declared 388 postings")
    a.refused("the advert at /job/x")
    linea = "; ".join(a.notes)
    assert "1 short of its declared 388" in linea
    assert "refused with 429" in linea
    assert linea.index("1 short") < linea.index("refused"), "notes first, then refusals"


def test_an_adapter_with_nothing_to_say_records_nothing():
    assert Adapter().notes == []


# --- "nothing new" has to say whether anything was missing ------------------

def _report(polls, **extra):
    base = {"run_id": 2, "seeding": False, "sources": len(polls), "new": [],
            "excluded": [], "excluded_reasons": {}, "closed": 0, "polls": polls}
    base.update(extra)
    return base


def test_nothing_new_with_a_failed_source_does_not_claim_every_source_answered():
    """The subject said "1 source failing" over a body saying every source answered.

    And it is not only a contradiction: when a source fails, "nothing new" may be
    nothing new BECAUSE of the failure. A reader who takes the sentence at face value
    reads a gap as quiet, which is this project's founding failure arriving as a
    reassurance.
    """
    from vedetta.digest import render

    body = render.render_text(_report([
        {"employer": "GitLab", "platform": "greenhouse", "outcome": "ok", "count": 300,
         "note": None},
        {"employer": "Guidewire", "platform": "workday", "outcome": "error",
         "count": 0, "error": "HTTP 429",
         "note": "1 request was refused with 429 and no Retry-After, so it was not "
                 "asked again: the listing at offset 0"},
    ]))
    assert "Every watched source answered" not in body
    assert "1 of 2 did not answer in full" in " ".join(body.split())
    assert "SOURCE HEALTH" in body
    # and it arrives wrapped to the width of the rules around it, not as one long line
    assert max(len(r) for r in body.splitlines()) <= 62 or all(
        len(r) <= 62 for r in body.splitlines()
        if "did not answer" in r or "may be short" in r)
    # and the subject's claim and the body's now agree
    assert "1 source failing" in render.subject(_report([
        {"employer": "A", "platform": "greenhouse", "outcome": "ok", "count": 1,
         "note": None},
        {"employer": "B", "platform": "workday", "outcome": "error", "count": 0,
         "note": None}]))


def test_nothing_new_with_every_source_healthy_still_says_so():
    """The reassurance is worth printing when it is true, so it must survive."""
    from vedetta.digest import render

    body = render.render_text(_report([
        {"employer": "GitLab", "platform": "greenhouse", "outcome": "ok", "count": 300,
         "note": None},
    ]))
    assert "None. Every watched source answered and had nothing new." in body


@pytest.mark.parametrize("outcome", ["empty", "partial"])
def test_a_short_or_empty_listing_also_counts_as_not_answering_in_full(outcome):
    """A board that answered with nothing, or with half of itself, is not silence
    either - and "nothing new" over it would mean the same wrong thing."""
    from vedetta.digest import render

    body = render.render_text(_report([
        {"employer": "A", "platform": "greenhouse", "outcome": "ok", "count": 9,
         "note": None},
        {"employer": "B", "platform": "workday", "outcome": outcome, "count": 0,
         "note": None},
    ]))
    assert "Every watched source answered" not in body
    assert "1 of 2 did not answer in full" in " ".join(body.split())


def test_a_source_that_could_not_be_reached_says_so_in_the_digest(tmp_path, monkeypatch):
    """A dropped connection has no note, so without the error the line is bare.

    Found in the lab on 19/11 by stopping the fake careers server mid-cycle. The row
    said `sitemap unreachable: ConnectError`, the digest said "FAILED Cantiere
    (sitemap)" and nothing else - and the sentence two lines above it, added the same
    morning, said "the reasons are under SOURCE HEALTH". A promise the section did not
    keep.
    """
    from vedetta import db as db_mod
    from vedetta import run as run_mod
    from vedetta.adapters.base import Adapter, AdapterError
    from vedetta.digest import render

    class _Unreachable(Adapter):
        def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
            raise AdapterError("sitemap unreachable: ConnectError")

    monkeypatch.setitem(run_mod.ADAPTERS, "down", _Unreachable)
    conn = db_mod.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO employer (id, key, display_name, channel, enabled) "
                 "VALUES (1, 'c', 'Cantiere', 'private', 1)")
    conn.execute("INSERT INTO source (id, employer_id, platform, identifier, endpoint, "
                 "enabled, verified_on) VALUES (1, 1, 'down', 'c', 'http://x/', 1, "
                 "'2026-01-01')")
    conn.commit()
    run_id = run_mod.start_run(conn, trigger="test", seeding=False)
    source = {"id": 1, "employer_id": 1, "platform": "down", "identifier": "c",
              "endpoint": "http://x/", "employer_name": "Cantiere", "params": None}

    outcome, _, note = run_mod.poll(conn, run_id, source)
    assert outcome == "error" and not note, "a dropped connection leaves no note"

    # what the live digest path builds for it
    report = {"run_id": run_id, "seeding": False, "sources": 1, "new": [],
              "excluded": [], "excluded_reasons": {}, "closed": 0,
              "polls": [{"employer": "Cantiere", "platform": "down",
                         "outcome": "error", "count": 0, "note": note}]}
    riga = conn.execute("SELECT error FROM source_poll WHERE run_id=?",
                        (run_id,)).fetchone()
    assert riga[0] == "sitemap unreachable: ConnectError", "the row knows"
    report["polls"][0]["error"] = riga[0]
    body = render.render_text(report)
    assert "FAILED  Cantiere (down)" in body
    assert "sitemap unreachable: ConnectError" in body, (
        "and so does the reader, now that the digest carries it")


def test_the_live_run_puts_the_error_in_the_report_the_digest_is_built_from(
        tmp_path, offline_config, monkeypatch):
    """The test above builds the report by hand, so it proves the renderer and not the
    path. This one drives `execute_in`, which is what a real run calls, because a
    mutation that removed the read-back passed all 610 other tests.
    """
    from vedetta import config as config_mod
    from vedetta import db as db_mod
    from vedetta import run as run_mod
    from vedetta.adapters.base import Adapter, AdapterError
    from vedetta.digest import render

    class _Unreachable(Adapter):
        platform = "down"

        def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
            raise AdapterError("sitemap unreachable: ConnectError")

    monkeypatch.setitem(run_mod.ADAPTERS, "down", _Unreachable)
    conn = db_mod.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO employer (id, key, display_name, channel, enabled) "
                 "VALUES (90, 'cantiere', 'Cantiere', 'private', 1)")
    conn.execute("INSERT INTO source (id, employer_id, platform, identifier, endpoint, "
                 "enabled, verified_on) VALUES (90, 90, 'down', 'c', 'http://x/', 1, "
                 "'2026-01-01')")
    conn.commit()

    cfg = config_mod.load(tmp_path, offline_config)
    run_id = run_mod.start_run(conn, trigger="test", seeding=False)
    report = run_mod.execute_in(conn, cfg, run_id)

    poll = next(p for p in report["polls"] if p["employer"] == "Cantiere")
    assert poll["outcome"] == "error"
    assert poll.get("error") == "sitemap unreachable: ConnectError", (
        "the report the digest is rendered from carries it")
    assert "sitemap unreachable: ConnectError" in render.render_text(report)
