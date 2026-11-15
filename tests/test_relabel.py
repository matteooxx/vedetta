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

import pytest

from vedetta import db as db_mod
from vedetta import run as run_mod
from vedetta import triage as triage_mod
from vedetta.adapters.base import RawPosting
from vedetta.adapters.greenhouse import GreenhouseAdapter
from vedetta.config import Config

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
def _workday_item(title: str = TITLE) -> RawPosting:
    path = "/job/Dublin/" + title.replace(" ", "-") + "_R101"
    return RawPosting(
        platform_key=path, title=title, location=LOCATION,
        url="https://acme.wd3.myworkdayjobs.com/en-US/Careers" + path,
        published_at="2026-11-01",
        text=" \n".join([title, LOCATION, BODY]),                     # workday.py:92
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


# --- known defects: xfail(strict=True) ------------------------------------------------

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


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="V4/V5: relabel rebuilds the body only from raw['content'|'description'] "
           "(run.py:545) after deleting every label (run.py:552); these shapes keep what "
           "first sight read only in `text`, which is never stored, or in a raw cut "
           "mid-JSON (run.py:260, :550). P4 (posting_text) removes this.")
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


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Rule B: relabel deletes the labels (run.py:552) and label_posting deletes "
           "posting_skill (run.py:317) before judging the title alone; nothing is "
           "counted. P4 keeps body labels, passes matcher=None, and counts them.")
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


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="V19: the body cluster is lost on relabel, so track_label adds "
           "no-target-track and the posting leaves the default view. P4 merges kept "
           "labels before track_label and blocked_by.")
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


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="The body gate is lost on relabel (run.py:552), so the posting turns "
           "workable with no blocked_by. P4 keeps the gate label for text-less postings.")
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
