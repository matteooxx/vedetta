"""Tests for place extraction and the facet query logic.

Both are places where being quietly wrong costs the reader a posting they wanted:
a location that fails to parse makes a posting unfilterable, and a facet count that
is computed against its own filter makes the panel unusable.
"""
from __future__ import annotations

import sqlite3

import pytest

from vedetta import db as db_mod
from vedetta import facets
from vedetta.places import extract


# --- place extraction, against strings taken from the real boards ----------

@pytest.mark.parametrize("raw,expected", [
    ("Remote, Canada; Remote, United Kingdom", ["Canada", "United Kingdom"]),
    ("United States (Remote)", ["United States"]),
    ("Dublin, Ireland", ["Dublin", "Ireland"]),
    ("GB-London", ["United Kingdom", "London"]),
    ("Ireland - Dublin Hub (Hybrid)", ["Ireland", "Dublin"]),
    ("Warsaw pl", ["Warsaw", "Poland"]),
    ("Paris, IDF, fr", ["Paris", "France"]),
    ("Bangalore, India", ["Bangalore", "India"]),
])
def test_places_extracted(raw, expected):
    assert extract(raw)[0] == expected


@pytest.mark.parametrize("raw", [
    "2 Locations", "Remote", "", None,
    # Seen live: "N/A" produced two places called "N" and "A", both of which became
    # facet options.
    "N/A",
])
def test_strings_with_no_place_yield_none(raw):
    assert extract(raw)[0] == []


@pytest.mark.parametrize("raw", [
    "Home based - EMEA", "Home Office, Germany", "Work From Home - United States",
])
def test_home_based_counts_as_remote(raw):
    """A working pattern, not a place - but still worth recording as remote.

    One watched employer writes every posting this way, so losing the flag would
    make its whole board look office-bound.
    """
    assert extract(raw)[1] is True


@pytest.mark.parametrize("raw,expected", [
    ("Home based - EMEA", ["EMEA"]),
    ("EMEA - Remote", ["EMEA"]),
    ("Home Based - Americas; Home Based - APAC", ["Americas", "APAC"]),
    ("Home based - Worldwide", ["Worldwide"]),
    ("Remote - LATAM", ["LATAM"]),
])
def test_a_region_is_a_place(raw, expected):
    """These used to yield nothing, which was the point of the test they were in:
    "Home based - EMEA" had produced a place called "Home". Discarding the whole
    fragment fixed that and went too far - 63 postings in the watched population name
    no place at all, only a region, so they could be neither filtered nor judged.

    A region is now kept. What must not come back is "Home".
    """
    places, remote, _ = extract(raw)
    assert places == expected
    assert "Home" not in places
    assert remote is True


def test_a_real_office_survives_a_home_based_sibling():
    places, remote, _ = extract("Home based - EMEA; Office Based - London, UK")
    assert places == ["EMEA", "London", "United Kingdom"]
    assert remote is True


def test_remote_is_a_flag_not_a_place():
    places, remote, hybrid = extract("Remote, Poland")
    assert places == ["Poland"]
    assert remote and not hybrid


def test_hybrid_is_detected():
    assert extract("Dublin (Hybrid)")[2] is True


def test_an_unknown_place_is_kept_rather_than_dropped():
    """A place this module has never heard of must still become a facet.

    Dropping it would make the posting unfilterable, which is a quiet way of making
    it invisible.
    """
    places, _, _ = extract("Ouagadougou, Burkina Faso")
    assert "Ouagadougou" in places and "Burkina Faso" in places


# --- facet queries ----------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "t.db")
    connection.execute("INSERT INTO run (id, started_at, trigger) VALUES (1,'now','test')")
    rows = [
        (1, "alpha", "Alpha", "Cloud Engineer", "Dublin, Ireland", 1, 1, 0),
        (2, "alpha", "Alpha", "Senior Architect", "Bangalore, India", 0, 0, 0),
        (3, "beta", "Beta", "Platform Engineer", "Remote, Poland", 1, 1, 0),
        (4, "beta", "Beta", "Account Executive", "Dublin, Ireland", 0, 0, 0),
    ]
    for pid, key, name, title, location, workable, remote, hybrid in rows:
        connection.execute(
            "INSERT OR IGNORE INTO employer (key, display_name) VALUES (?,?)", (key, name))
        emp = connection.execute("SELECT id FROM employer WHERE key=?", (key,)).fetchone()[0]
        connection.execute(
            """INSERT INTO posting (id, employer_id, title, title_norm, location,
                    location_norm, first_seen_run, last_seen_run, workable,
                    is_remote, is_hybrid)
               VALUES (?,?,?,?,?,?,1,1,?,?,?)""",
            (pid, emp, title, title.lower(), location, (location or "").lower(),
             workable, remote, hybrid))
        for place in extract(location)[0]:
            connection.execute(
                "INSERT INTO posting_place (posting_id, place) VALUES (?,?)", (pid, place))
    connection.execute(
        """INSERT INTO label (posting_id, rule_id, kind, severity, explain,
                produced_by, created_at)
           VALUES (2,'level-too-senior','gate','blocking','too senior','profile','now')""")
    connection.commit()
    return connection


def test_scope_counts_always_report_both_halves(conn):
    counts = facets.scope_counts(conn, facets.Selection())
    assert counts == {"workable": 2, "excluded": 2, "all": 4}


def test_one_place_narrows(conn):
    sel = facets.Selection(scope="all", place=["Ireland"])
    assert facets.total(conn, sel) == 2


def test_two_places_are_a_union_not_an_intersection(conn):
    """Selecting two values in one facet must widen, not narrow to nothing."""
    sel = facets.Selection(scope="all", place=["Ireland", "Poland"])
    assert facets.total(conn, sel) == 3


def test_two_employers_are_a_union(conn):
    sel = facets.Selection(scope="all", employer=["alpha", "beta"])
    assert facets.total(conn, sel) == 4


def test_facets_combine_as_an_intersection(conn):
    sel = facets.Selection(scope="all", place=["Ireland"], employer=["alpha"])
    assert facets.total(conn, sel) == 1


def test_a_facet_counts_its_own_options_ignoring_itself(conn):
    """The property that makes the panel usable.

    With Ireland selected, Poland must still show its real count - otherwise you can
    never tell whether widening the selection would find anything.
    """
    sel = facets.Selection(scope="all", place=["Ireland"])
    places = {o["value"]: o["n"] for o in facets.options(conn, sel)["place"]}
    assert places["Ireland"] == 2
    assert places["Poland"] == 1


def test_other_facets_do_constrain_a_facets_counts(conn):
    sel = facets.Selection(scope="all", employer=["beta"])
    places = {o["value"]: o["n"] for o in facets.options(conn, sel)["place"]}
    assert places.get("India") is None       # India belongs only to alpha
    assert places["Poland"] == 1


def test_mode_facet(conn):
    sel = facets.Selection(scope="all", mode=["remote"])
    assert facets.total(conn, sel) == 2


def test_label_facet(conn):
    sel = facets.Selection(scope="all", label=["level-too-senior"])
    assert facets.total(conn, sel) == 1


def test_untriaged_filter(conn):
    conn.execute("INSERT INTO triage (posting_id, state, decided_at) VALUES (1,'applied','now')")
    conn.commit()
    assert facets.total(conn, facets.Selection(scope="all", triage=["none"])) == 3
    assert facets.total(conn, facets.Selection(scope="all", triage=["applied"])) == 1
    assert facets.total(conn, facets.Selection(scope="all", triage=["applied", "none"])) == 4


def test_toggling_adds_then_removes(conn):
    sel = facets.Selection(place=["Ireland"])
    assert sel.toggled("place", "Poland")["place"] == ["Ireland", "Poland"]
    assert "place" not in sel.toggled("place", "Ireland")


def test_active_count_sees_every_facet():
    sel = facets.Selection(place=["Ireland"], employer=["a", "b"], q="cloud")
    assert sel.active_count == 4
