"""``fetch`` end to end for Greenhouse and SmartRecruiters, on stand-in clients.

No network. Each stand-in implements only the verbs its adapter calls, as in
test_partial_listings.py.
"""
from __future__ import annotations

import pytest

from vedetta.adapters import smartrecruiters
from vedetta.adapters.base import AdapterError
from vedetta.adapters.greenhouse import GreenhouseAdapter
from vedetta.adapters.smartrecruiters import SmartRecruitersAdapter


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Base:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --- Greenhouse -------------------------------------------------------------

class _GreenhouseClient(_Base):
    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return self.response


JOBS = dict(jobs=[
    dict(id=101, title=" Backend Engineer ", location=dict(name="Dublin, Ireland"),
         absolute_url="https://boards.example/101", first_published="2026-01-02",
         updated_at="2026-02-02",
         content="&lt;p&gt;Fluent&nbsp;German &amp; Python&lt;/p&gt;"),
    dict(id=102, title="Designer", location=None,
         absolute_url="https://boards.example/102", updated_at="2026-03-03"),
])


def _greenhouse(monkeypatch, response):
    adapter = GreenhouseAdapter()
    client = _GreenhouseClient(response)
    monkeypatch.setattr(adapter, "client", lambda: client)
    return adapter, client


def test_greenhouse_fetch_returns_one_posting_per_job(monkeypatch):
    adapter, client = _greenhouse(monkeypatch, _Response(JOBS))
    seen = []
    items = adapter.fetch(dict(identifier="acme"), known_keys=set(), detail_budget=None,
                          progress=lambda *a: seen.append(a))
    assert [i.platform_key for i in items] == ["101", "102"]
    first, second = items
    assert first.title == "Backend Engineer"
    assert first.location == "Dublin, Ireland"
    assert first.url == "https://boards.example/101"
    assert first.published_at == "2026-01-02"          # first_published wins
    assert second.published_at == "2026-03-03"         # falls back to updated_at
    assert "Fluent German & Python" in first.text      # escaped HTML flattened
    assert "<p>" not in first.text
    assert client.urls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs"
                           "?content=true"]
    assert seen == [(2, 2)]


def test_greenhouse_fetch_runs_without_the_optional_arguments(monkeypatch):
    adapter, _ = _greenhouse(monkeypatch, _Response(JOBS))
    assert len(adapter.fetch(dict(identifier="acme"))) == 2


def test_greenhouse_a_404_names_the_identifier_not_the_employer(monkeypatch):
    adapter, _ = _greenhouse(monkeypatch, _Response({}, status=404))
    with pytest.raises(AdapterError) as err:
        adapter.fetch(dict(identifier="nope"))
    assert err.value.http_status == 404


def test_greenhouse_a_payload_without_jobs_is_an_error(monkeypatch):
    adapter, _ = _greenhouse(monkeypatch, _Response(dict(meta={})))
    with pytest.raises(AdapterError):
        adapter.fetch(dict(identifier="acme"))


# --- SmartRecruiters --------------------------------------------------------

class _SRClient(_Base):
    def __init__(self, listing, details):
        self.listing = listing
        self.details = details
        self.detail_calls = []

    def get(self, url, params=None):
        if params is not None:
            offset = params["offset"]
            page = self.listing[offset: offset + params["limit"]]
            return _Response(dict(content=page, totalFound=len(self.listing)))
        posting = url.rsplit("/", 1)[1]
        self.detail_calls.append(posting)
        if posting not in self.details:
            return _Response({}, status=404)
        sections = dict(jobDescription=dict(text=self.details[posting]))
        return _Response(dict(jobAd=dict(sections=sections)))


LISTING = [
    dict(id="a1", name="Data Analyst",
         location=dict(city="Berlin", country="de"),
         releasedDate="2026-04-01",
         experienceLevel=dict(label="Associate")),
    dict(id="b2", name="Chef", location=dict(city="Lyon", remote=True),
         createdOn="2026-05-01"),
    dict(id="c3", name="Nurse", location=dict(city="Cork")),
]
DETAILS = dict(a1="<p>Needs SQL</p>", b2="<b>Knife skills</b>", c3="Night shifts")


def _sr(monkeypatch, client):
    monkeypatch.setattr(smartrecruiters, "POLITE_DELAY", 0)
    adapter = SmartRecruitersAdapter()
    monkeypatch.setattr(adapter, "client", lambda: client)
    return adapter


def test_smartrecruiters_fetch_reads_the_advert_for_each_new_posting(monkeypatch):
    client = _SRClient(LISTING, DETAILS)
    seen = []
    items = _sr(monkeypatch, client).fetch(
        dict(identifier="acme"), known_keys=set(), detail_budget=None,
        progress=lambda *a: seen.append(a))
    assert [i.platform_key for i in items] == ["a1", "b2", "c3"]
    a1 = items[0]
    assert a1.title == "Data Analyst"
    assert a1.url == "https://jobs.smartrecruiters.com/acme/a1"
    assert a1.published_at == "2026-04-01"
    assert "Needs SQL" in a1.text and "<p>" not in a1.text
    assert "Associate" in a1.text                       # experienceLevel reaches the text
    assert items[1].published_at == "2026-05-01"        # createdOn fallback
    assert "Remote" in items[1].location
    assert client.detail_calls == ["a1", "b2", "c3"]
    assert seen[0] == (0, None, "listing postings")
    assert seen[-1] == (3, 3, "adverts read")


def test_smartrecruiters_a_known_posting_is_a_minimal_entry_and_not_reread(monkeypatch):
    client = _SRClient(LISTING, DETAILS)
    items = _sr(monkeypatch, client).fetch(dict(identifier="acme"), known_keys={"b2"})
    by_key = {i.platform_key: i for i in items}
    assert set(by_key) == {"a1", "b2", "c3"}            # still present, so not "closed"
    assert by_key["b2"].title == "" and by_key["b2"].text == ""
    assert "b2" not in client.detail_calls


def test_smartrecruiters_the_detail_budget_caps_second_requests(monkeypatch):
    client = _SRClient(LISTING, DETAILS)
    items = _sr(monkeypatch, client).fetch(dict(identifier="acme"), detail_budget=1)
    assert len(items) == 3                              # all recorded, only one read
    assert client.detail_calls == ["a1"]
    assert items[2].title == "Nurse"


def test_smartrecruiters_a_failed_detail_does_not_drop_the_posting(monkeypatch):
    client = _SRClient(LISTING, {})                     # every detail answers 404
    items = _sr(monkeypatch, client).fetch(dict(identifier="acme"))
    assert [i.platform_key for i in items] == ["a1", "b2", "c3"]


def test_smartrecruiters_a_404_listing_is_an_error(monkeypatch):
    class Gone(_Base):
        def get(self, url, params=None):
            return _Response({}, status=404)

    with pytest.raises(AdapterError) as err:
        _sr(monkeypatch, Gone()).fetch(dict(identifier="nope"))
    assert err.value.http_status == 404
