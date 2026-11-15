"""`reconcile`: which posting an item from a poll belongs to, or whether it is new.

This is the one place in the program where a real opening can disappear without
anyone being told, which is the failure vedetta exists to prevent. Getting it wrong
in one direction merges two openings into one and hides the second; in the other it
drops an item on the floor. Both are silent: the digest looks normal either way.

The rules, in order of strength:

1. same source, same platform key -> the posting already recorded for it;
2. same employer, identical normalised title AND location -> that posting;
3. same employer, identical normalised title, other location -> a NEW posting,
   flagged `dup_of` the first, because a duplicate costs a glance and a wrong merge
   hides a posting.

Each rule's test is built so that the next-weaker rule would give a different
answer. A test of rule 3 in a database where rules 1 and 2 cannot fire proves rule 3
works, not that it loses to them.

Between rules 1 and 2 sits the re-sighting branch: three adapters emit
`resighting=True` (with an empty payload) for a key they already know, meaning
"still there, not re-read". It used to be signalled by `title=""` alone, which also
swallowed a genuinely new item the platform served with no title, without a trace.
Both items `reconcile` cannot place now leave a note on the poll: the last two tests.
"""
from __future__ import annotations

import pytest

from vedetta import config as config_mod
from vedetta import db as db_mod
from vedetta import run as run_mod
from vedetta.adapters.base import RawPosting, normalise
from vedetta.digest import render


@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "v.db")
    connection.executescript("""
        INSERT INTO employer (id, key, display_name) VALUES (1, 'acme', 'Acme');
        INSERT INTO employer (id, key, display_name) VALUES (2, 'other', 'Other');
        -- Two routes to Acme, which is what makes rule 2 reachable at all.
        INSERT INTO source (id, employer_id, platform, identifier, verified_on)
          VALUES (1, 1, 'stub', 'acme-a', '2026-10-08');
        INSERT INTO source (id, employer_id, platform, identifier, verified_on)
          VALUES (2, 1, 'stub2', 'acme-b', '2026-10-08');
        INSERT INTO source (id, employer_id, platform, identifier, verified_on)
          VALUES (3, 2, 'stub3', 'other', '2026-10-08');
    """)
    connection.commit()
    yield connection
    connection.close()


SOURCE_A = {"id": 1, "employer_id": 1}
SOURCE_B = {"id": 2, "employer_id": 1}
SOURCE_OTHER = {"id": 3, "employer_id": 2}


def _run(conn):
    return run_mod.start_run(conn, "manual", False)


def _posting(conn, run_id, title, location=None, employer_id=1, closed_run=None,
             dup_of=None):
    cur = conn.execute(
        """INSERT INTO posting (employer_id, title, title_norm, location, location_norm,
                first_seen_run, last_seen_run, closed_run, dup_of)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (employer_id, title, normalise(title), location, normalise(location),
         run_id, run_id, closed_run, dup_of))
    return cur.lastrowid


def _sighting(conn, run_id, source_id, posting_id, key, digest="h-earlier"):
    conn.execute(
        """INSERT INTO sighting (run_id, source_id, posting_id, platform_key, content_hash)
           VALUES (?,?,?,?,?)""", (run_id, source_id, posting_id, key, digest))


def _row(conn, posting_id):
    return conn.execute("SELECT * FROM posting WHERE id=?", (posting_id,)).fetchone()


def _count(conn):
    return conn.execute("SELECT count(*) FROM posting").fetchone()[0]


# --- a new item ---------------------------------------------------------------

def test_a_new_key_with_a_title_creates_a_posting_and_its_sighting(conn):
    """The baseline every other test leans on. Without it, an implementation that
    returned `(None, False)` for everything would pass the re-sighting tests."""
    run_id = _run(conn)
    item = RawPosting(platform_key="gh-101", title="Platform Engineer (m/f/d)",
                      location="Dublin, Ireland", url="https://x.invalid/101")

    posting_id, is_new = run_mod.reconcile(conn, run_id, SOURCE_A, item)
    assert posting_id is not None
    assert is_new is True

    row = _row(conn, posting_id)
    assert row["employer_id"] == 1
    assert row["title"] == "Platform Engineer (m/f/d)", "the raw title is kept"
    assert row["title_norm"] == "platform engineer"
    assert row["location_norm"] == "dublin ireland"
    assert (row["first_seen_run"], row["last_seen_run"]) == (run_id, run_id)
    assert row["closed_run"] is None
    assert row["dup_of"] is None

    # The caller's next step, exactly as run.execute_in does it.
    run_mod.record_sighting(conn, run_id, SOURCE_A, posting_id, item)
    sighting = conn.execute(
        "SELECT run_id, posting_id, content_hash FROM sighting "
        "WHERE source_id=1 AND platform_key='gh-101'").fetchall()
    assert [tuple(s) for s in sighting] == [(run_id, posting_id, item.content_hash())]
    assert _count(conn) == 1


# --- rule 1 -------------------------------------------------------------------

def test_rule_1_the_known_key_wins_over_a_title_match_elsewhere(conn):
    """The key points at A; the title and location point at B, which rule 2 would
    pick (lower id, identical normalised strings). Rule 1 must win, and must do so
    even though the posting has since been retitled - that is what a key is for."""
    first = _run(conn)
    b = _posting(conn, first, "Data Engineer", "Dublin")
    a = _posting(conn, first, "Old Title", "Dublin")
    _sighting(conn, first, 1, a, "k-1")
    closing = _run(conn)
    conn.execute("UPDATE posting SET closed_run=? WHERE id=?", (closing, a))
    assert b < a, "precondition: rule 2 would choose B"

    now = _run(conn)
    item = RawPosting(platform_key="k-1", title="Data Engineer", location="Dublin")
    assert run_mod.reconcile(conn, now, SOURCE_A, item) == (a, False)

    assert _row(conn, a)["last_seen_run"] == now
    assert _row(conn, a)["closed_run"] is None, "a re-sighting reopens"
    assert _row(conn, b)["last_seen_run"] == first, "B must not be touched"
    assert _count(conn) == 2


def test_rule_1_is_scoped_to_its_source(conn):
    """Platform keys are only unique within a source: two Workday tenants can both
    have `/job/1`. The same key from another employer's source is a new posting."""
    first = _run(conn)
    a = _posting(conn, first, "Old Title")
    _sighting(conn, first, 1, a, "/job/1")

    now = _run(conn)
    item = RawPosting(platform_key="/job/1", title="Nurse", location="Lyon")
    posting_id, is_new = run_mod.reconcile(conn, now, SOURCE_OTHER, item)
    assert is_new is True
    assert posting_id != a
    assert _row(conn, posting_id)["employer_id"] == 2


# --- the re-sighting convention ------------------------------------------------

def test_an_empty_title_on_a_known_key_is_a_re_sighting(conn):
    """`resighting=True` on a key already recorded: the sitemap, Workday and SmartRecruiters
    adapters' way of saying "still there, not re-read". It must keep the posting
    open, create nothing, and not overwrite what was recorded about it."""
    first = _run(conn)
    a = _posting(conn, first, "Site Reliability Engineer", "Berlin")
    _sighting(conn, first, 1, a, "https://x.invalid/jobs/7", digest="h-real-payload")
    closing = _run(conn)
    conn.execute("UPDATE posting SET closed_run=? WHERE id=?", (closing, a))

    now = _run(conn)
    item = RawPosting(platform_key="https://x.invalid/jobs/7", title="",
                      url="https://x.invalid/jobs/7", resighting=True)
    assert run_mod.reconcile(conn, now, SOURCE_A, item) == (a, False)

    row = _row(conn, a)
    assert row["last_seen_run"] == now
    assert row["closed_run"] is None
    assert (row["title"], row["location"]) == ("Site Reliability Engineer", "Berlin")
    assert _count(conn) == 1

    # The hash of an empty payload would make every re-sighting look like an edit.
    assert item.content_hash() != "h-real-payload", "precondition"
    run_mod.record_sighting(conn, now, SOURCE_A, a, item)
    carried = conn.execute(
        "SELECT content_hash, posting_id FROM sighting WHERE run_id=? AND source_id=1",
        (now,)).fetchone()
    assert tuple(carried) == ("h-real-payload", a)


# --- rule 2 -------------------------------------------------------------------

def test_rule_2_another_route_with_the_same_title_and_location_is_the_same_posting(conn):
    """A new key, from the second route, for an opening already recorded. Rule 3
    would create a second posting flagged as a duplicate; rule 2 must catch it first.
    """
    first = _run(conn)
    a = _posting(conn, first, "Data Engineer", "Dublin")
    _sighting(conn, first, 1, a, "a-1")
    closing = _run(conn)
    conn.execute("UPDATE posting SET closed_run=? WHERE id=?", (closing, a))

    now = _run(conn)
    item = RawPosting(platform_key="b-99", title="Data Engineer", location="Dublin")
    assert run_mod.reconcile(conn, now, SOURCE_B, item) == (a, False)
    assert _count(conn) == 1, "rule 3 would have created a flagged duplicate here"
    assert _row(conn, a)["last_seen_run"] == now
    assert _row(conn, a)["closed_run"] is None


@pytest.mark.parametrize("stored,seen", [
    # A European gender tag on one route only.
    (("Backend Engineer (m/w/d)", "Zürich"), ("Backend Engineer", "Zürich")),
    # Punctuation and case, in both title and location.
    (("Site-Reliability Engineer", "Dublin, Ireland"),
     ("site reliability engineer!", "Dublin Ireland")),
])
def test_rule_2_compares_normalised_strings_not_raw_ones(conn, stored, seen):
    assert stored != seen
    assert normalise(stored[0]) == normalise(seen[0]), "precondition"
    assert normalise(stored[1]) == normalise(seen[1]), "precondition"

    first = _run(conn)
    a = _posting(conn, first, *stored)
    now = _run(conn)
    item = RawPosting(platform_key="b-1", title=seen[0], location=seen[1])
    assert run_mod.reconcile(conn, now, SOURCE_B, item) == (a, False)
    assert _count(conn) == 1


def test_rule_2_does_not_reach_across_employers(conn):
    first = _run(conn)
    _posting(conn, first, "Data Engineer", "Dublin", employer_id=1)
    now = _run(conn)
    item = RawPosting(platform_key="o-1", title="Data Engineer", location="Dublin")
    posting_id, is_new = run_mod.reconcile(conn, now, SOURCE_OTHER, item)
    assert is_new is True
    assert _row(conn, posting_id)["dup_of"] is None, "rule 3 is per employer too"


# --- rule 3 -------------------------------------------------------------------

def test_rule_3_same_title_other_location_keeps_both_and_flags_the_newcomer(conn):
    """Rule 2 would merge this if it ignored the location; the merge would hide the
    Berlin opening. Both are kept, and further ones point at the original rather
    than chaining onto a duplicate."""
    first = _run(conn)
    dublin = _posting(conn, first, "Data Engineer", "Dublin")

    now = _run(conn)
    berlin_item = RawPosting(platform_key="b-2", title="Data Engineer (m/f/d)",
                             location="Berlin")
    berlin, is_new = run_mod.reconcile(conn, now, SOURCE_B, berlin_item)
    assert is_new is True
    assert berlin != dublin
    assert _row(conn, berlin)["dup_of"] == dublin
    assert _row(conn, berlin)["location"] == "Berlin"
    assert _row(conn, dublin)["last_seen_run"] == first, "the original is not touched"

    paris, is_new = run_mod.reconcile(
        conn, now, SOURCE_B,
        RawPosting(platform_key="b-3", title="Data Engineer", location="Paris"))
    assert is_new is True
    assert _row(conn, paris)["dup_of"] == dublin
    assert _count(conn) == 3


# --- through the run loop -------------------------------------------------------

class _MixedAdapter:
    """One new titled posting, one re-sighting, one new posting served untitled."""
    platform = "stub"

    def __init__(self):
        self.notes = []
        self.incomplete = False

    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        assert "k-known" in (known_keys or set()), "precondition: seeded below"
        return [
            RawPosting(platform_key="k-new", title="Platform Engineer",
                       location="Dublin", url="https://x.invalid/k-new"),
            RawPosting(platform_key="k-known", title="",
                       url="https://x.invalid/k-known", resighting=True),
            RawPosting(platform_key="k-untitled", title="",
                       url="https://x.invalid/k-untitled"),
        ]


def _run_mixed_batch(conn, tmp_path, offline_config, monkeypatch):
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _MixedAdapter)
    # Only source 1 polls; the other two would need adapters of their own.
    conn.execute("UPDATE source SET enabled=0 WHERE id IN (2, 3)")
    first = _run(conn)
    known = _posting(conn, first, "Known Role", "Dublin")
    _sighting(conn, first, 1, known, "k-known")
    run_mod.finish_run(conn, first)
    conn.commit()

    cfg = config_mod.load(tmp_path, offline_config)
    run_id = _run(conn)
    report = run_mod.execute_in(conn, cfg, run_id)
    return run_id, known, report


def test_the_run_loop_records_the_new_posting_and_keeps_the_known_one_open(
        conn, tmp_path, offline_config, monkeypatch):
    run_id, known, report = _run_mixed_batch(conn, tmp_path, offline_config,
                                             monkeypatch)
    assert [p["title"] for p in report["new"] + report["excluded"]] == [
        "Platform Engineer"]
    assert _row(conn, known)["last_seen_run"] == run_id
    assert _row(conn, known)["closed_run"] is None
    keys = {r[0] for r in conn.execute(
        "SELECT platform_key FROM sighting WHERE run_id=?", (run_id,))}
    assert {"k-new", "k-known"} <= keys


def test_an_untitled_posting_with_a_new_key_does_not_vanish_silently(
        conn, tmp_path, offline_config, monkeypatch):
    """Not a re-sighting: the key has never been recorded for this source, so this
    is an opening the platform served without a title. Greenhouse, Workday and
    SmartRecruiters all build the title as `(... or "").strip()`, so this is reachable
    from every adapter, not just the ones that use the convention.

    The trace asked for is the poll's own `note`:
      * `source_poll.note` for this run and source - the column that exists for
        "something survivable worth saying", already shown on the dashboard and
        already read back by digest/rebuild.py;
      * the same note in the run report, which is what the digest is rendered from;
      * the digest text itself. Today render.py prints a note only for a `partial`
        poll, so this part needs a change there as well.

    And two things it must NOT do:
      * mark the poll `partial`. Nothing was recorded for this key, so there is
        nothing close_missing could wrongly retire - while `partial` would stop this
        employer ever closing anything for as long as the source keeps serving it;
      * note the genuine re-sighting. A note on every known URL every day is how a
        reader learns to stop reading notes.
    """
    run_id, _, report = _run_mixed_batch(conn, tmp_path, offline_config, monkeypatch)
    poll = conn.execute(
        "SELECT outcome, note FROM source_poll WHERE run_id=? AND source_id=1",
        (run_id,)).fetchone()

    assert poll["outcome"] == "ok"
    assert "k-untitled" in (poll["note"] or ""), "recorded against the poll"
    assert "k-known" not in poll["note"], "a re-sighting is not news"
    assert "k-untitled" in (report["polls"][0]["note"] or ""), "in the report"
    assert "k-untitled" in render.render_text(report), "in the digest the reader gets"


class _BothDropsAdapter:
    """One titled posting, plus one of each kind of item `reconcile` cannot place."""
    platform = "stub"

    def __init__(self):
        self.notes = []
        self.incomplete = False

    def fetch(self, source, known_keys=None, detail_budget=None, progress=None):
        assert "k-ghost" not in (known_keys or set()), "precondition: never recorded"
        return [
            RawPosting(platform_key="k-new", title="Platform Engineer",
                       location="Dublin", url="https://x.invalid/k-new"),
            # Declared a re-sighting, of a key this source has no record of. Only an
            # adapter bug produces it, since known_keys comes from the same table.
            RawPosting(platform_key="k-ghost", title="",
                       url="https://x.invalid/k-ghost", resighting=True),
            RawPosting(platform_key="k-untitled", title="",
                       url="https://x.invalid/k-untitled"),
        ]


def test_a_declared_re_sighting_of_an_unknown_key_is_not_silent_either(
        conn, tmp_path, offline_config, monkeypatch):
    """The other half of the convention: the flag says "you know this one", the
    database says it does not. Nothing can be created from an empty payload, so the
    item is dropped - with a note, on the same three surfaces as the untitled case.

    The two notes must say different things. Which case it was is the whole
    diagnosis: an untitled posting is the platform's doing, an unknown re-sighting is
    the adapter's. This is also what proves the flag replaced the empty-title
    convention rather than joining it: read `not item.title` as a re-sighting again
    and the untitled key lands in the wrong sentence.
    """
    monkeypatch.setitem(run_mod.ADAPTERS, "stub", _BothDropsAdapter)
    conn.execute("UPDATE source SET enabled=0 WHERE id IN (2, 3)")
    conn.commit()
    cfg = config_mod.load(tmp_path, offline_config)
    run_id = _run(conn)
    report = run_mod.execute_in(conn, cfg, run_id)

    poll = conn.execute(
        "SELECT outcome, note FROM source_poll WHERE run_id=? AND source_id=1",
        (run_id,)).fetchone()
    assert poll["outcome"] == "ok", "nothing recorded, so nothing to wrongly close"
    segments = (poll["note"] or "").split("; ")
    ghost = [s for s in segments if "k-ghost" in s]
    untitled = [s for s in segments if "k-untitled" in s]
    assert len(ghost) == 1 and len(untitled) == 1, segments
    assert ghost != untitled, f"the two cases share one sentence: {segments}"
    assert "no record" in ghost[0] and "no title" not in ghost[0], ghost[0]
    assert "no title" in untitled[0] and "no record" not in untitled[0], untitled[0]

    assert report["polls"][0]["note"] == poll["note"]
    assert "k-ghost" in render.render_text(report)
    assert _count(conn) == 1, "only the titled posting is created"
