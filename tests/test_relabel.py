"""`relabel`: re-judge every stored posting against the current rules and profile.

Labels are a cached judgement, so after a rules or profile edit the postings already
stored have to be judged again - from the command line or from the interface's
Re-apply Rules button (`web/app.py` `relabel_now`), which call the same function.

What it gets wrong today: the table `posting` keeps no text, only `raw`, and
`relabel` rebuilds a body only from `raw["content"]` / `raw["description"]`, the
Greenhouse shape. Workday and SmartRecruiters store the listing entry as `raw`, the
sitemap adapter drops `description` from it on purpose, and a `raw` cut at 200,000
characters is no longer JSON. For all of those `relabel` judges the title alone, and
since it deletes every label first, whatever the body said is gone without a word.

How this file is built, and why:

* Postings reach the database through `run.execute_in`, with fake adapters registered
  in `run.ADAPTERS`. Greenhouse is the real adapter over a fake HTTP client, because
  the case that passes today depends on its exact text formula (`greenhouse.py:72`).
  The other three emit `RawPosting`s in their adapter's shape: body in `text`, not in
  `raw`. `label_posting` is never called by hand - a state built by hand proves the
  hand, not the path.
* `_forget_text` removes the `posting_text` row when that table exists. Today it does
  nothing. Once P4 stores the text, it recreates a posting collected before P4, which
  is the only way the "no recoverable text" cases keep testing that rule rather than
  quietly passing through the "with text" branch.
* Preconditions use `_precondition` (`pytest.fail`), not `assert`. The known defects
  are `xfail(strict=True, raises=AssertionError)`; a setup that no longer builds the
  situation must show up red, not be counted as the expected failure.
"""
from __future__ import annotations

import copy
import sqlite3

import pytest
import yaml

from vedetta import backfill as backfill_mod
from vedetta import cli as cli_mod
from vedetta import db as db_mod
from vedetta import run as run_mod
from vedetta import triage as triage_mod
from vedetta.adapters.base import RawPosting
from vedetta.adapters.greenhouse import GreenhouseAdapter
from vedetta.config import Config
from vedetta.runlock import acquire
# At import, before any fake adapter is registered: configstore reads ADAPTERS when it
# is first imported, and would otherwise keep the fakes' parameters for the session.
from vedetta.web import app as app_module

# The name of the count P4 adds to what `relabel` returns: postings judged without a
# stored text, whose body labels were kept rather than recomputed. The CLI and the
# interface's message are meant to print it. Chosen here; P4 implements it.
TEXTLESS_STAT = "without_text"

RULES = {
    "profile": {},
    "rules": [
        {"id": "needs-clearance", "kind": "gate", "severity": "blocking",
         "field": "body", "when": r"(?i)security clearance",
         "explain": "requires a security clearance"},
        # No `field`: reads title and body together, the default.
        {"id": "platform-track", "kind": "cluster", "severity": "positive",
         "when": r"(?i)kubernetes", "explain": "platform work"},
        # No `field` either. Hits the location, which the adapters put in `text`.
        {"id": "mentions-dublin", "kind": "note", "severity": "info",
         "when": r"(?i)\bdublin\b", "explain": "names Dublin"},
        {"id": "title-engineer", "kind": "note", "severity": "info",
         "field": "title", "when": r"(?i)engineer", "explain": "an engineering title"},
    ],
}

PROFILE = {
    "experience": {"accept_level": ["senior"], "reject_level": ["principal"]},
    "locations": {"preferred": ["Ireland"]},
    "skills": {"have": ["Python"], "watch": ["Terraform"]},
    "exclude_if": ["needs-clearance", "level-too-senior"],
}

TITLE = "Platform Engineer"
LOCATION = "Dublin, Ireland"
BODY = ("You will run Kubernetes clusters for our customers, write Python every day "
        "and review Terraform. Candidates must hold an active security clearance.")
# Long enough that `json.dumps(raw)` passes the 200,000-character cut (run.py:260).
PADDING = "Lorem ipsum dolor sit amet. " * 8000


# --- the database and the configuration --------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "v.db")
    connection.execute(
        "INSERT INTO employer (id, key, display_name) VALUES (1, 'acme', 'Acme')")
    connection.commit()
    yield connection
    connection.close()


def _config(tmp_path, profile=None) -> Config:
    return Config(root=tmp_path, settings={}, rules=copy.deepcopy(RULES),
                  profile_doc=copy.deepcopy(profile or PROFILE))


def _watch(conn, platform: str) -> int:
    cur = conn.execute(
        "INSERT INTO source (employer_id, platform, identifier, verified_on) "
        "VALUES (1, ?, ?, '2026-10-08')", (platform, f"acme-{platform}"))
    conn.commit()
    return cur.lastrowid


def _run(conn, cfg) -> dict:
    return run_mod.execute_in(conn, cfg, run_mod.start_run(conn, "manual", False))


# --- fake adapters --------------------------------------------------------------------

class _Listing:
    """Returns whatever `items` holds. Subclassed per platform by `_serve`."""
    platform = "stub"
    items: list = []

    def __init__(self):
        self.notes = []
        self.incomplete = False

    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        return list(self.items)


def _serve(monkeypatch, platform: str, items: list) -> None:
    cls = type(f"_Fake_{platform}", (_Listing,), {"platform": platform, "items": items})
    monkeypatch.setitem(run_mod.ADAPTERS, platform, cls)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Board:
    """A Greenhouse board API answering one GET with a fixed list of jobs."""

    def __init__(self, jobs):
        self.jobs = jobs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return _Response({"jobs": self.jobs})


def _serve_greenhouse(monkeypatch, jobs: list) -> None:
    """The real GreenhouseAdapter.fetch, with only the network replaced."""
    cls = type("_GreenhouseOffline", (GreenhouseAdapter,),
               {"client": lambda self: _Board(jobs)})
    monkeypatch.setitem(run_mod.ADAPTERS, "greenhouse", cls)


def _gh_job(job_id: int, title: str, content_text: str = BODY,
            location: str = LOCATION) -> dict:
    """A job as the board API returns it with content=true: escaped HTML."""
    content = f"&lt;p&gt;{content_text}&lt;/p&gt;" if content_text else ""
    return {"id": job_id, "title": title, "location": {"name": location},
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
            "updated_at": "2026-11-01T09:00:00Z", "content": content}


# The other three adapters, in the shape each one stores: body in `text`, not in `raw`.
def _workday_item(title: str = TITLE, body: str = BODY) -> RawPosting:
    path = "/job/Dublin/" + title.replace(" ", "-") + "_R101"
    return RawPosting(
        platform_key=path, title=title, location=LOCATION,
        url="https://acme.wd3.myworkdayjobs.com/en-US/Careers" + path,
        published_at="2026-11-01",
        text=" \n".join([title, LOCATION, body]),                     # workday.py:92
        raw={"title": title, "externalPath": path,                    # workday.py:93
             "locationsText": LOCATION, "postedOn": "Posted Today",
             "bulletFields": ["R101"]})


def _smartrecruiters_item() -> RawPosting:
    entry = {"id": "744000012345678", "name": TITLE,
             "location": {"city": "Dublin", "country": "ie", "remote": False},
             "department": {"label": "Engineering"},
             "releasedDate": "2026-11-01T09:00:00.000Z"}
    return RawPosting(
        platform_key=entry["id"], title=TITLE, location=LOCATION,
        url="https://jobs.smartrecruiters.com/Acme/744000012345678",
        published_at=entry["releasedDate"],
        text=" \n".join([TITLE, LOCATION, "Engineering", BODY]),   # smartrecruiters.py:76
        raw=entry)                                                  # smartrecruiters.py:77


def _sitemap_item() -> RawPosting:
    url = "https://careers.acme.invalid/jobs/platform-engineer-dublin"
    item = {"@type": "JobPosting", "title": TITLE, "datePosted": "2026-11-01",
            "jobLocation": {"@type": "Place", "address": {
                "addressLocality": "Dublin", "addressCountry": "Ireland"}},
            "description": f"<p>{BODY}</p>"}
    return RawPosting(
        platform_key=url, title=TITLE, location=LOCATION, url=url,
        published_at=item["datePosted"],
        text=" \n".join([TITLE, LOCATION, BODY]),                     # sitemap.py:265
        raw={k: v for k, v in item.items() if k != "description"})  # sitemap.py:270


# --- reading the outcome --------------------------------------------------------------

def _precondition(condition: bool, message: str) -> None:
    """Not an assert, so a broken setup is never mistaken for an expected failure."""
    if not condition:
        pytest.fail(f"precondition: {message}")


def _forget_text(conn, posting_id: int) -> None:
    """Make a posting look collected before P4: no stored text.

    Does nothing while `posting_text` does not exist. After P4 it is what keeps the
    "no recoverable text" cases on the rule they are there to prove.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='posting_text'"
    ).fetchone()
    if exists:
        cur = conn.execute("DELETE FROM posting_text WHERE posting_id=?", (posting_id,))
        conn.commit()
        # Once the table exists, every posting execute_in collected has a row. Zero
        # deleted means the text was never stored or this helper misses it - either
        # way the case would no longer test what it claims to.
        _precondition(cur.rowcount == 1, "posting_text held a row to forget")


def _id(conn, title: str) -> int:
    rows = conn.execute("SELECT id FROM posting WHERE title=?", (title,)).fetchall()
    _precondition(len(rows) == 1, f"exactly one posting titled {title!r}, got {len(rows)}")
    return rows[0][0]


def _state(conn, posting_id: int) -> dict:
    """The four things a relabel at unchanged configuration must not change."""
    labels = sorted(tuple(r) for r in conn.execute(
        "SELECT rule_id, produced_by FROM label WHERE posting_id=?", (posting_id,)))
    skills = sorted(tuple(r) for r in conn.execute(
        "SELECT term, have FROM posting_skill WHERE posting_id=?", (posting_id,)))
    row = conn.execute("SELECT workable, blocked_by FROM posting WHERE id=?",
                       (posting_id,)).fetchone()
    return {"labels": labels, "skills": skills,
            "workable": row["workable"], "blocked_by": row["blocked_by"]}


def _rule_ids(conn, posting_id: int) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT rule_id FROM label WHERE posting_id=?", (posting_id,))}


# --- to keep: green today, and must stay green --------------------------------------

def test_relabel_leaves_triage_and_its_history_exactly_as_they_were(
        conn, tmp_path, monkeypatch):
    """The operator's decisions are the one thing in the database that cannot be
    rebuilt. Compared value by value, so a rewrite with the same row count fails."""
    _watch(conn, "greenhouse")
    _serve_greenhouse(monkeypatch, [_gh_job(1, "Senior Platform Engineer"),
                                    _gh_job(2, "Senior Data Engineer")])
    _run(conn, _config(tmp_path))
    a, b = _id(conn, "Senior Platform Engineer"), _id(conn, "Senior Data Engineer")

    triage_mod.set_stage(conn, a, "applied", "sent the CV through the portal")
    triage_mod.set_stage(conn, a, "interview", "first call on Tuesday")
    triage_mod.set_stage(conn, b, "interested")
    triage_mod.clear(conn, b)
    before = ([tuple(r) for r in conn.execute("SELECT * FROM triage ORDER BY posting_id")],
              [tuple(r) for r in conn.execute("SELECT * FROM triage_event ORDER BY id")])
    _precondition(len(before[0]) == 1 and len(before[1]) == 4, "triage was recorded")

    # A configuration change, so the relabel really rewrites labels on both postings.
    changed = copy.deepcopy(PROFILE)
    changed["experience"] = {"accept_level": ["graduate"], "reject_level": ["senior"]}
    run_mod.relabel(conn, _config(tmp_path, changed))
    _precondition("level-too-senior" in _rule_ids(conn, a), "the relabel did its work")

    after = ([tuple(r) for r in conn.execute("SELECT * FROM triage ORDER BY posting_id")],
             [tuple(r) for r in conn.execute("SELECT * FROM triage_event ORDER BY id")])
    assert after == before


def test_greenhouse_with_a_body_relabels_to_what_first_sight_saw(
        conn, tmp_path, monkeypatch):
    """The one shape `relabel` can read back today. Green now, and not an xfail: the
    only difference between first sight and relabel is the separator (" \\n" at
    greenhouse.py:72, "\\n" at run.py:549), which no rule here depends on."""
    _watch(conn, "greenhouse")
    _serve_greenhouse(monkeypatch, [_gh_job(1, TITLE)])
    cfg = _config(tmp_path)
    _run(conn, cfg)
    pid = _id(conn, TITLE)
    before = _state(conn, pid)
    _precondition({("needs-clearance", "rules"), ("platform-track", "rules")}
                  <= set(before["labels"]), "the body produced labels")
    _precondition(before["skills"] == [("Python", 1), ("Terraform", 0)],
                  "the body produced skills")
    _precondition(before["workable"] == 0, "the body gate excluded it")

    run_mod.relabel(conn, cfg)
    assert _state(conn, pid) == before


def test_an_adapter_that_leaves_text_empty_is_judged_on_its_title_both_times(
        conn, tmp_path, monkeypatch):
    """The engine is given `item.text or item.title` at first sight (run.py:459, :479),
    so with no text the title is read as the body. A `field: body` rule and a skill
    hit on the title there; they must still be there after a relabel."""
    title = "Python Developer, Security Clearance"
    _watch(conn, "stub")
    _serve(monkeypatch, "stub", [RawPosting(
        platform_key="e-1", title=title, location=LOCATION,
        url="https://x.invalid/e-1", text="", raw={"id": "e-1", "title": title})])
    cfg = _config(tmp_path)
    _run(conn, cfg)
    pid = _id(conn, title)
    before = _state(conn, pid)
    _precondition(("needs-clearance", "rules") in before["labels"],
                  "the body rule hit on the title")
    _precondition(("Python", 1) in before["skills"], "the skill hit on the title")

    run_mod.relabel(conn, cfg)
    assert _state(conn, pid) == before


def test_relabel_brings_a_changed_profile_to_open_and_closed_postings(
        conn, tmp_path, monkeypatch):
    """A run labels only what is new, so a profile change reaches the postings already
    stored only through relabel - and relabel takes them all, closed ones included.

    Both level lists change, not only `reject_level`: `level_verdict` reads
    `accept_level` first (profile.py:269-274), so with "senior" still accepted no
    reject word could ever take effect. Changing both keeps the test true before and
    after P1b reverses that order.
    """
    _watch(conn, "greenhouse")
    neutral = "Build and operate internal tooling."
    _serve_greenhouse(monkeypatch, [_gh_job(1, "Senior Platform Engineer", neutral),
                                    _gh_job(2, "Senior Data Engineer", neutral)])
    _run(conn, _config(tmp_path))
    still_open = _id(conn, "Senior Platform Engineer")
    closing = _id(conn, "Senior Data Engineer")
    first = {p: _state(conn, p) for p in (still_open, closing)}
    for p in first:
        _precondition(("level-suitable", "profile") in first[p]["labels"]
                      and first[p]["workable"] == 1, "both start suitable and workable")

    changed = copy.deepcopy(PROFILE)
    changed["experience"] = {"accept_level": ["graduate"], "reject_level": ["senior"]}
    cfg = _config(tmp_path, changed)

    # The next run sees only the first posting again: the second is closed, and
    # nothing is new, so nothing is labelled.
    _serve_greenhouse(monkeypatch, [_gh_job(1, "Senior Platform Engineer", neutral)])
    _run(conn, cfg)
    closed = {r[0]: r[1] for r in conn.execute("SELECT id, closed_run FROM posting")}
    _precondition(closed[still_open] is None and closed[closing] is not None,
                  "one posting open, one closed")
    assert {p: _state(conn, p) for p in first} == first, (
        "a run without new items changes no verdict")

    run_mod.relabel(conn, cfg)
    for p in (still_open, closing):
        state = _state(conn, p)
        assert ("level-suitable", "profile") not in state["labels"]
        assert ("level-too-senior", "profile") in state["labels"]
        assert state["workable"] == 0
        assert "the title asks for a level above yours (senior)" in state["blocked_by"]


def test_a_changed_profile_reaches_a_posting_without_stored_text(
        conn, tmp_path, monkeypatch):
    """The addition (g) waited for P4: the same change, on a posting with no stored
    text. The profile's verdict comes from the title, which is there, so the old
    `level-suitable` does not survive; what the body said is kept."""
    title = "Senior Platform Engineer"
    _watch(conn, "workday")
    _serve(monkeypatch, "workday", [_workday_item(title)])
    _run(conn, _config(tmp_path))
    pid = _id(conn, title)
    _forget_text(conn, pid)
    before = _state(conn, pid)
    body = {("needs-clearance", "rules"), ("platform-track", "rules"),
            ("mentions-dublin", "rules")}
    _precondition(("level-suitable", "profile") in before["labels"]
                  and body <= set(before["labels"]), "level and body labels were set")

    changed = copy.deepcopy(PROFILE)
    changed["experience"] = {"accept_level": ["graduate"], "reject_level": ["senior"]}
    stats = run_mod.relabel(conn, _config(tmp_path, changed))

    after = _state(conn, pid)
    assert stats[TEXTLESS_STAT] == 1
    assert ("level-suitable", "profile") not in after["labels"]
    assert ("level-too-senior", "profile") in after["labels"]
    assert body <= set(after["labels"])
    assert after["skills"] == before["skills"]
    assert after["workable"] == 0
    assert set(after["blocked_by"].split("; ")) == {
        "requires a security clearance",
        "the title asks for a level above yours (senior)"}


# --- the defects P4 repaired (xfail(strict=True) until then) --------------------------

LOSSY_FORMS = {
    "workday": lambda: ("workday", [_workday_item()]),
    "smartrecruiters": lambda: ("smartrecruiters", [_smartrecruiters_item()]),
    "sitemap": lambda: ("sitemap", [_sitemap_item()]),
    # Content empty: the adapter's text is still "title \nlocation" (greenhouse.py:72),
    # while relabel falls back to the title alone (run.py:541, :546).
    "greenhouse-empty-content": lambda: ("greenhouse", [_gh_job(1, TITLE, "")]),
    # Content so long that `raw` is cut mid-JSON (run.py:260): relabel's json.loads
    # fails and `except Exception: pass` (run.py:550) leaves the title alone.
    "greenhouse-truncated-raw": lambda: ("greenhouse", [_gh_job(1, TITLE, BODY + PADDING)]),
}


def _collect(conn, tmp_path, monkeypatch, form: str, cfg=None,
             greenhouse_too: tuple = ()) -> int:
    """One run that collects the posting in `form`, plus any Greenhouse jobs given."""
    platform, items = LOSSY_FORMS[form]()
    jobs = list(greenhouse_too)
    if platform == "greenhouse":
        jobs = items + jobs
    else:
        _watch(conn, platform)
        _serve(monkeypatch, platform, items)
    if jobs:
        _watch(conn, "greenhouse")
        _serve_greenhouse(monkeypatch, jobs)
    _run(conn, cfg or _config(tmp_path))
    pid = _id(conn, TITLE)
    if form == "greenhouse-truncated-raw":
        raw = conn.execute("SELECT raw FROM posting WHERE id=?", (pid,)).fetchone()[0]
        _precondition(len(raw) == 200000, "raw was cut at 200,000 characters")
    return pid


@pytest.mark.parametrize("form", list(LOSSY_FORMS))
def test_relabel_at_unchanged_configuration_changes_nothing(
        conn, tmp_path, monkeypatch, form):
    """(a) Idempotence: the same four equalities as the Greenhouse-with-body case,
    for every shape whose body relabel cannot read back today."""
    pid = _collect(conn, tmp_path, monkeypatch, form)
    before = _state(conn, pid)
    _precondition(("mentions-dublin", "rules") in before["labels"],
                  "first sight read past the title")

    run_mod.relabel(conn, _config(tmp_path))
    assert _state(conn, pid) == before


@pytest.mark.parametrize("form", ["workday", "greenhouse-truncated-raw"])
def test_a_posting_without_recoverable_text_keeps_what_its_body_said(
        conn, tmp_path, monkeypatch, form):
    """(b) What cannot be recomputed is not deleted: the labels of `body` rules and
    rules without `field` stay, `posting_skill` stays row for row, and the posting is
    counted in what relabel returns, so the reader is told how many were judged this
    way. A second posting, with its text, is there so the count has to be exact."""
    textless = _collect(conn, tmp_path, monkeypatch, form,
                        greenhouse_too=(_gh_job(2, "Site Reliability Engineer"),))
    _forget_text(conn, textless)
    with_text = _id(conn, "Site Reliability Engineer")

    before = _state(conn, textless)
    _precondition({("needs-clearance", "rules"), ("platform-track", "rules"),
                   ("mentions-dublin", "rules")} <= set(before["labels"]),
                  "the body produced labels")
    _precondition(before["skills"] == [("Python", 1), ("Terraform", 0)],
                  "the body produced skills")
    _precondition(_state(conn, with_text)["labels"] != [], "the second posting is labelled")

    stats = run_mod.relabel(conn, _config(tmp_path))
    after = _state(conn, textless)
    assert after["labels"] == before["labels"]
    assert after["skills"] == before["skills"]
    assert stats.get(TEXTLESS_STAT) == 1
    assert stats["postings"] == 2 == stats["workable"] + stats["excluded"]


def test_a_cluster_found_in_the_body_keeps_the_posting_workable(
        conn, tmp_path, monkeypatch):
    """(c) With `require_match` on, a posting whose only cluster came from the body
    must not be handed `no-target-track` by the step meant to stop destroying it."""
    profile = copy.deepcopy(PROFILE)
    profile["tracks"] = {"require_match": True}
    profile["exclude_if"] = ["level-too-senior", "no-target-track"]
    cfg = _config(tmp_path, profile)
    pid = _collect(conn, tmp_path, monkeypatch, "workday", cfg)
    _forget_text(conn, pid)

    before = _state(conn, pid)
    _precondition("kubernetes" not in f"{TITLE} {LOCATION}".lower(),
                  "the cluster can only have come from the body")
    _precondition(("platform-track", "rules") in before["labels"]
                  and before["workable"] == 1, "the body cluster made it workable")

    run_mod.relabel(conn, cfg)
    after = _state(conn, pid)
    assert ("no-target-track", "profile") not in after["labels"]
    assert after["workable"] == 1
    assert ("platform-track", "rules") in after["labels"]


def test_a_gate_found_in_the_body_keeps_the_posting_excluded(
        conn, tmp_path, monkeypatch):
    """(d) Excluded by a `field: body` gate listed in `exclude_if`: still excluded,
    for the same stated reason."""
    pid = _collect(conn, tmp_path, monkeypatch, "workday")
    _forget_text(conn, pid)
    before = _state(conn, pid)
    _precondition(before["workable"] == 0
                  and before["blocked_by"] == "requires a security clearance",
                  "the body gate excluded it")

    run_mod.relabel(conn, _config(tmp_path))
    after = _state(conn, pid)
    assert (after["workable"], after["blocked_by"]) == (0, before["blocked_by"])


# --- P4: what is kept follows the rules as they are written now ------------------------

def test_a_kept_label_follows_the_rule_as_it_is_written_now(
        conn, tmp_path, monkeypatch):
    """Rule B, point 3. Without a text, a body label is kept only while its rule
    exists and still reads the body: a deleted rule takes its label with it, a rule
    moved to `field: title` is recomputed on the title, and a kept label carries the
    rule's current wording, so `blocked_by` says what rules.yaml says today."""
    pid = _collect(conn, tmp_path, monkeypatch, "workday")
    _forget_text(conn, pid)
    _precondition({"needs-clearance", "platform-track", "mentions-dublin"}
                  <= _rule_ids(conn, pid), "the body produced labels")

    cfg = _config(tmp_path)
    rules = {r["id"]: r for r in cfg.rules["rules"]}
    rules["needs-clearance"]["explain"] = "asks for a clearance you do not hold"
    rules["needs-clearance"]["severity"] = "warning"
    rules["mentions-dublin"]["field"] = "title"    # the title has no Dublin in it
    cfg.rules["rules"] = [r for r in cfg.rules["rules"] if r["id"] != "platform-track"]
    run_mod.relabel(conn, cfg)

    ids = _rule_ids(conn, pid)
    assert "platform-track" not in ids
    assert "mentions-dublin" not in ids
    kept = conn.execute("SELECT kind, severity, explain FROM label WHERE posting_id=? "
                        "AND rule_id='needs-clearance'", (pid,)).fetchone()
    assert tuple(kept) == ("gate", "warning", "asks for a clearance you do not hold")
    row = conn.execute("SELECT workable, blocked_by FROM posting WHERE id=?",
                       (pid,)).fetchone()
    assert tuple(row) == (0, "asks for a clearance you do not hold")


def test_a_profile_label_is_never_kept_even_when_a_rule_shares_its_id(
        conn, tmp_path, monkeypatch):
    """Rule B, point 1: only `rules` labels are read to be kept. Profile labels come
    from the title and location, which are there. Rule and profile labels share one
    namespace of ids, so a rule named like a profile label must not turn the old
    profile verdict into a rule label the body never gave."""
    pid = _collect(conn, tmp_path, monkeypatch, "workday")
    _forget_text(conn, pid)
    _precondition(("location-preferred", "profile") in _state(conn, pid)["labels"],
                  "the profile placed it")

    cfg = _config(tmp_path)
    cfg.rules["rules"].append({"id": "location-preferred", "kind": "note",
                               "severity": "info", "when": r"(?i)\bnever-in-any-text\b"})
    run_mod.relabel(conn, cfg)
    assert ("location-preferred", "rules") not in _state(conn, pid)["labels"]


# --- P4b: without a text, only `field: title` rules are judged again --------------------

@pytest.mark.parametrize("field", [None, "body"])
def test_an_unless_the_body_satisfied_does_not_come_back_without_a_text(
        conn, tmp_path, monkeypatch, field):
    """The live `language-gate`: no `field`, an `unless`, and listed in `exclude_if`.
    The title asks for German, the body says German is a plus, so first sight gives
    no label. Judged again on the title alone, the `when` still hits and the `unless`
    has nothing to read: the gate would be added, and the posting hidden by a body
    that said the opposite. Without a text, a rule that reads the body keeps its
    verdict from first sight - here, its absence."""
    gate = {"id": "language-gate", "kind": "gate", "severity": "blocking",
            "when": r"(?i)fluent in german", "unless": r"(?i)german[^.]{0,40}a plus",
            "explain": "asks for a language you do not speak"}
    if field:
        gate["field"] = field
    profile = copy.deepcopy(PROFILE)
    profile["exclude_if"] = profile["exclude_if"] + ["language-gate"]
    cfg = _config(tmp_path, profile)
    cfg.rules["rules"].append(gate)
    title = "Project Manager (Fluent in German)"
    _watch(conn, "workday")
    _serve(monkeypatch, "workday", [_workday_item(
        title, "Business German is a plus. You will run our delivery reviews.")])
    _run(conn, cfg)
    pid = _id(conn, title)
    _forget_text(conn, pid)
    before = _state(conn, pid)
    _precondition("language-gate" not in _rule_ids(conn, pid) and before["workable"] == 1,
                  "the body's unless suppressed the gate at first sight")
    _precondition("language-gate" in {l.rule_id for l in run_mod.RuleEngine(
        cfg.rules).apply(title, title=title)},
                  "on the title alone the gate fires, so this case can catch the defect")

    stats = run_mod.relabel(conn, cfg)
    assert stats[TEXTLESS_STAT] == 1
    assert _state(conn, pid) == before


def test_a_new_rule_on_the_body_reaches_only_the_postings_with_a_text(
        conn, tmp_path, monkeypatch):
    """The price of the test above, photographed so that it reads as a decision. A
    rule added after first sight is judged on every posting with a stored text; on one
    without, only if it is `field: title`. A rule that reads the body is not judged on
    less evidence than first sight had."""
    textless = _collect(conn, tmp_path, monkeypatch, "workday",
                        greenhouse_too=(_gh_job(2, "Site Reliability Engineer"),))
    _forget_text(conn, textless)
    with_text = _id(conn, "Site Reliability Engineer")
    cfg = _config(tmp_path)
    cfg.rules["rules"] += [
        {"id": "new-on-all", "when": r"(?i)engineer"},
        {"id": "new-on-body", "field": "body", "when": r"(?i)engineer"},
        {"id": "new-on-title", "field": "title", "when": r"(?i)engineer"}]
    _precondition("engineer" in TITLE.lower(), "every new rule hits the title")

    run_mod.relabel(conn, cfg)
    new = {"new-on-all", "new-on-body", "new-on-title"}
    assert _rule_ids(conn, with_text) & new == new
    assert _rule_ids(conn, textless) & new == {"new-on-title"}


def test_a_kept_gate_keeps_its_place_in_blocked_by(conn, tmp_path, monkeypatch):
    """`blocked_by` is written in label order, which is rules.yaml order. A body gate
    kept from first sight must still come before a title gate listed after it, or a
    relabel at unchanged configuration rewrites the reason line of every such posting."""
    profile = copy.deepcopy(PROFILE)
    profile["exclude_if"] = profile["exclude_if"] + ["title-gate"]
    cfg = _config(tmp_path, profile)
    cfg.rules["rules"].append({"id": "title-gate", "kind": "gate", "field": "title",
                               "when": r"(?i)engineer", "explain": "an engineering title"})
    pid = _collect(conn, tmp_path, monkeypatch, "workday", cfg)
    _forget_text(conn, pid)
    before = _state(conn, pid)
    _precondition(before["blocked_by"]
                  == "requires a security clearance; an engineering title",
                  "the body gate and the title gate both excluded it, in rule order")

    run_mod.relabel(conn, cfg)
    assert _state(conn, pid) == before


def test_first_sight_stores_exactly_the_text_the_engine_read(
        conn, tmp_path, monkeypatch):
    """Decision A: one variable is read by the engine and written to posting_text. An
    adapter that leaves `text` empty is judged on its title, so the title is what is
    stored, and `origin` says it was a fallback."""
    _watch(conn, "stub")
    _serve(monkeypatch, "stub", [RawPosting(
        platform_key="e-1", title="Untexted Role", location=LOCATION,
        url="https://x.invalid/e-1", text="", raw={"id": "e-1"})])
    _watch(conn, "greenhouse")
    _serve_greenhouse(monkeypatch, [_gh_job(1, TITLE)])
    _run(conn, _config(tmp_path))

    rows = {r["title"]: (r["text"], r["origin"]) for r in conn.execute(
        "SELECT p.title, t.text, t.origin FROM posting p "
        "JOIN posting_text t ON t.posting_id = p.id")}
    assert rows["Untexted Role"] == ("Untexted Role", "title-fallback")
    assert rows[TITLE] == (f"{TITLE} \n{LOCATION} \n{BODY}", "first-sight")


# --- P4: backfill-text ------------------------------------------------------------------

def _texts(conn) -> dict:
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT posting_id, text, origin FROM posting_text")}


def test_backfill_rebuilds_what_greenhouse_first_sight_stored_and_counts_the_rest(
        conn, tmp_path, monkeypatch):
    """The Greenhouse formula (greenhouse.py:72), empty content included, gives back
    the text first sight stored. Every other platform has no body in `raw` and is left
    to rule B; a `raw` cut mid-JSON is counted apart. The three add up to what was read."""
    _watch(conn, "workday")
    _serve(monkeypatch, "workday", [_workday_item("Workday Engineer")])
    _watch(conn, "greenhouse")
    _serve_greenhouse(monkeypatch, [
        _gh_job(1, TITLE), _gh_job(2, "Data Engineer", ""),
        _gh_job(3, "Site Reliability Engineer", BODY + PADDING)])
    _run(conn, _config(tmp_path))
    ids = {t: _id(conn, t) for t in (TITLE, "Data Engineer", "Site Reliability Engineer",
                                     "Workday Engineer")}
    first_sight = _texts(conn)
    for pid in ids.values():
        _forget_text(conn, pid)

    report = backfill_mod.backfill(conn, apply=False)
    assert _texts(conn) == {}, "nothing is written without apply"
    assert report.read == 4
    assert report.read == report.with_text + report.without_text + report.unreadable
    assert (report.with_text, report.without_text, report.unreadable) == (2, 1, 1)
    assert report.by_platform["workday"]["without_text"] == 1
    assert report.by_platform["greenhouse"]["unreadable"] == 1

    report = backfill_mod.backfill(conn, apply=True)
    assert report.with_text == 2
    stored = _texts(conn)
    for title in (TITLE, "Data Engineer"):
        assert stored[ids[title]] == (first_sight[ids[title]][0], "backfill-greenhouse")
    assert ids["Workday Engineer"] not in stored
    assert ids["Site Reliability Engineer"] not in stored

    # Nothing left to rebuild, and what was stored is not rewritten.
    again = backfill_mod.backfill(conn, apply=True)
    assert (again.read, again.with_text) == (2, 0)
    assert _texts(conn) == stored


# --- P4: the command line, and the run lock ---------------------------------------------

@pytest.fixture()
def stored(tmp_path, monkeypatch):
    """A root and a config directory the CLI can be pointed at, with a Greenhouse
    posting whose text was forgotten and a Workday one, both collected by execute_in."""
    root, cfgdir = tmp_path / "root", tmp_path / "cfg"
    cfgdir.mkdir()
    (cfgdir / "rules.yaml").write_text(yaml.safe_dump(RULES), encoding="utf-8")
    (cfgdir / "profile.yaml").write_text(yaml.safe_dump(PROFILE), encoding="utf-8")
    cfg = Config(root=root, settings={}, rules=copy.deepcopy(RULES),
                 profile_doc=copy.deepcopy(PROFILE))
    connection = db_mod.connect(cfg.db_path)
    connection.execute(
        "INSERT INTO employer (id, key, display_name) VALUES (1, 'acme', 'Acme')")
    _watch(connection, "workday")
    _serve(monkeypatch, "workday", [_workday_item("Workday Engineer")])
    _watch(connection, "greenhouse")
    _serve_greenhouse(monkeypatch, [_gh_job(1, TITLE)])
    _run(connection, cfg)
    for title in (TITLE, "Workday Engineer"):
        _forget_text(connection, _id(connection, title))
    connection.close()
    return {"root": root, "cfg": cfgdir, "db": cfg.db_path,
            "argv": ["--root", str(root), "--config-dir", str(cfgdir)]}


def _dump(path) -> list[str]:
    connection = sqlite3.connect(str(path))
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


def test_backfill_text_without_apply_writes_nothing(stored, capsys):
    before = _dump(stored["db"])
    assert cli_mod.main(stored["argv"] + ["backfill-text"]) == 0
    assert _dump(stored["db"]) == before
    out = capsys.readouterr().out
    assert "read 2 posting(s) with no stored text" in out
    assert "Nothing written" in out


def test_backfill_text_apply_stores_the_text(stored, capsys):
    assert cli_mod.main(stored["argv"] + ["backfill-text", "--apply"]) == 0
    connection = sqlite3.connect(str(stored["db"]))
    origins = [r[0] for r in connection.execute("SELECT origin FROM posting_text")]
    connection.close()
    assert origins == ["backfill-greenhouse"]


@pytest.mark.parametrize("command", [["backfill-text", "--apply"], ["relabel"]])
def test_a_bulk_write_waits_for_a_run_in_progress(stored, command, capsys):
    """Decision I: with the run lock held, exit 3 and write nothing."""
    before = _dump(stored["db"])
    with acquire(stored["db"].parent / "run.lock", owner="test:run"):
        assert cli_mod.main(stored["argv"] + command) == 3
    assert _dump(stored["db"]) == before
    assert "still in progress" in capsys.readouterr().err


def test_relabel_says_how_many_had_no_stored_text(stored, capsys):
    """Rule B, point 6, on the command line."""
    assert cli_mod.main(stored["argv"] + ["relabel"]) == 0
    out = capsys.readouterr().out
    assert "re-evaluated 2 postings" in out
    assert "2 without a stored text" in out
    # P4b: an edit to a body rule has no effect on these, and the reader is told so.
    assert "rules that read the body NOT re-evaluated" in out


def test_the_interface_says_how_many_had_no_stored_text(stored, monkeypatch):
    """Rule B, point 6, in the message of the Re-apply Rules button."""
    monkeypatch.setenv("VEDETTA_ROOT", str(stored["root"]))
    monkeypatch.setenv("VEDETTA_CONFIG_DIR", str(stored["cfg"]))
    import importlib
    importlib.reload(app_module)   # app.py reads the two variables at import
    application = app_module.create_app()
    application.config.update(TESTING=True)
    client = application.test_client()
    client.post("/relabel")
    with client.session_transaction() as session:
        messages = [m for _, m in session.get("_flashes", [])]
    assert any("2 without a stored text" in m for m in messages), messages
    assert any("rules that read the body were not re-evaluated" in m
               for m in messages), messages
