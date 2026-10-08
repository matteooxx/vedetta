"""The location filter as a tree, and the counts that made it necessary.

The flat version listed 102 values at three levels in one column ordered by count,
and two things were wrong with it at once.

The levels were mixed, so `EMEA` sat beside `Ireland` beside `Dublin`. Dublin is
inside Ireland, so picking both found nothing that Ireland alone had not.

And the country counts were simply wrong: they counted only the postings that wrote
the country's name. Germany read 11 while Berlin alone had 17. The number a reader is
asking for when they click Germany is 24.
"""
from __future__ import annotations

import pytest

from vedetta import db as db_mod
from vedetta import facets
from vedetta import placetree


# --- working out the hierarchy ---------------------------------------------

def test_the_table_places_a_city_it_knows():
    meta = placetree.derive([(1, "Krakow"), (1, "Poland")])
    assert meta["Krakow"]["parent"] == "Poland"
    assert meta["Krakow"]["kind"] == "place"
    assert meta["Poland"]["kind"] == "country"


def test_co_occurrence_places_a_city_the_table_cannot():
    """London and Dublin are deliberately absent from the table, their names being
    ambiguous - and they are the two largest values in the whole facet. Without this
    the two places that matter most would have no home."""
    rows = [(1, "Dublin"), (1, "Ireland"), (2, "Dublin"), (2, "Ireland"),
            (3, "Dublin"), (3, "Ireland")]
    assert placetree.derive(rows)["Dublin"]["parent"] == "Ireland"


def test_one_posting_is_not_evidence_about_a_place():
    """With a plurality rather than a majority this was wrong in the live data:
    "Oeiras" landed under Poland and "Ciudad Mexico" under Germany, each from a
    single posting that happened to list two places."""
    rows = [(1, "Oeiras"), (1, "Poland")]
    assert placetree.derive(rows)["Oeiras"]["parent"] is None


def test_a_minority_of_sightings_is_not_enough():
    rows = [(1, "Springfield"), (1, "Ireland"), (2, "Springfield"), (3, "Springfield"),
            (4, "Springfield"), (5, "Springfield")]
    assert placetree.derive(rows)["Springfield"]["parent"] is None


def test_a_majority_is():
    rows = [(1, "Springfield"), (1, "Ireland"), (2, "Springfield"), (2, "Ireland"),
            (3, "Springfield")]
    assert placetree.derive(rows)["Springfield"]["parent"] == "Ireland"


def test_two_spellings_of_one_place_share_a_row():
    """Milan beside Milano was two filter options with a fraction of the count each,
    and a reader who picked one silently missed the other."""
    meta = placetree.derive([(1, "Milano"), (1, "Italy"), (2, "Milan"), (2, "Italy")])
    assert meta["Milano"]["canon"] == "Milan"
    assert meta["Milan"]["canon"] == "Milan"


def test_a_county_and_its_city_share_a_row():
    rows = [(1, "County Dublin"), (1, "Ireland"), (2, "Dublin"), (2, "Ireland")]
    meta = placetree.derive(rows)
    assert meta["County Dublin"]["canon"] == "Dublin"
    assert meta["County Dublin"]["parent"] == "Ireland"


def test_a_region_has_no_parent_and_is_marked_as_one():
    meta = placetree.derive([(1, "EMEA"), (2, "Worldwide")])
    assert meta["EMEA"] == {"canon": "EMEA", "parent": None, "kind": "region"}
    assert meta["Worldwide"]["kind"] == "region"


def test_region_shorthand_meaning_the_same_scope_is_merged():
    meta = placetree.derive([(1, "Global"), (2, "Worldwide"), (3, "APJ")])
    assert meta["Global"]["canon"] == "Worldwide"
    assert meta["APJ"]["canon"] == "APAC"


# --- the facet, against a database -----------------------------------------

@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "v.db")
    connection.execute(
        "INSERT INTO employer (id, key, display_name) VALUES (1,'x','Example Co')")
    connection.execute("INSERT INTO run (id, started_at) VALUES (1,'2026-10-09')")
    connection.commit()
    return connection


def _posting(conn, posting_id, title, places):
    conn.execute(
        "INSERT INTO posting (id, employer_id, title, title_norm, first_seen_run, "
        "last_seen_run, workable) VALUES (?,1,?,?,1,1,1)",
        (posting_id, title, title.lower()))
    for place in places:
        conn.execute(
            "INSERT INTO posting_place (posting_id, place) VALUES (?,?)",
            (posting_id, place))
    conn.commit()


@pytest.fixture()
def board(conn):
    """A board shaped like the real one: some postings name the country, some only
    the city, one names two cities in the same country, and one names a region and
    nothing else."""
    _posting(conn, 1, "Backend Engineer", ["Dublin", "Ireland"])
    _posting(conn, 2, "Platform Engineer", ["Dublin"])
    _posting(conn, 3, "Data Engineer", ["Galway", "Ireland"])
    _posting(conn, 4, "SRE", ["County Dublin", "Ireland"])
    _posting(conn, 5, "Frontend Engineer", ["Berlin"])
    _posting(conn, 6, "Security Engineer", ["Berlin", "Germany"])
    _posting(conn, 7, "Support Engineer", ["EMEA"])
    _posting(conn, 8, "Staff Engineer", ["Dublin", "Galway", "Ireland"])
    placetree.rebuild(conn)
    return conn


def _tree(conn, **kwargs):
    return facets.place_tree(conn, facets.Selection(**kwargs))


def _row(tree, value):
    return next(t for t in tree if t["value"] == value)


def test_a_country_counts_everything_inside_it(board):
    """Five postings are in Ireland and only four say so. The fifth says Dublin."""
    tree = _tree(board)
    assert _row(tree, "Ireland")["n"] == 5
    assert _row(tree, "Germany")["n"] == 2


def test_a_posting_tagged_both_ways_counts_once(board):
    """Most postings name the country AND the city. A country row summing its
    children would double them."""
    ireland = _row(_tree(board), "Ireland")
    assert ireland["n"] == 5
    # Dublin 4 plus Galway 2 is 6, because one posting is in both.
    assert sum(child["n"] for child in ireland["children"]) == 6


def test_the_children_sit_under_their_country(board):
    children = {c["value"]: c["n"] for c in _row(_tree(board), "Ireland")["children"]}
    assert children == {"Dublin": 4, "Galway": 2}


def test_regions_come_first_and_are_marked(board):
    tree = _tree(board)
    assert tree[0]["kind"] == "region"
    assert tree[0]["value"] == "EMEA"
    assert tree[0]["children"] == []


def test_countries_follow_in_size_order(board):
    kinds = [t["kind"] for t in _tree(board)]
    assert kinds == ["region", "country", "country"]
    assert [t["value"] for t in _tree(board) if t["kind"] == "country"] == [
        "Ireland", "Germany"]


# --- choosing a value ------------------------------------------------------

def _matching(conn, **kwargs):
    selection = facets.Selection(**kwargs)
    where, params = facets._clauses(selection)
    sql = ("SELECT count(DISTINCT p.id) FROM posting p "
           "JOIN employer e ON e.id = p.employer_id"
           + (" WHERE " + " AND ".join(where) if where else ""))
    return conn.execute(sql, params).fetchone()[0]


def test_choosing_a_country_finds_what_is_inside_it(board):
    """The defect that started this. Ireland used to match only the postings that
    wrote the word Ireland, so the filter said one number and the panel beside it
    said another, and picking Dublin as well found nothing new."""
    assert _matching(board, place=["Ireland"]) == 5


def test_choosing_a_city_finds_its_other_spelling(board):
    """Dublin covers "County Dublin", which is the same place."""
    assert _matching(board, place=["Dublin"]) == 4


def test_choosing_a_region_stays_literal(board):
    """A region means "advertised for that whole region", not "anywhere in it".
    Otherwise EMEA would match every European posting and mean nothing."""
    assert _matching(board, place=["EMEA"]) == 1


def test_choosing_two_values_unions_them(board):
    assert _matching(board, place=["Ireland", "Germany"]) == 7


def test_choosing_a_country_and_a_city_inside_it_changes_nothing(board):
    """It did not before either - that was the confusing part. Now the counts say so
    up front, because Ireland reads 5 and Dublin reads 4 of those 5."""
    assert _matching(board, place=["Ireland"]) == 5
    assert _matching(board, place=["Ireland", "Dublin"]) == 5


def test_the_counts_in_the_panel_are_the_counts_you_get(board):
    """The whole point of the exercise: every number shown is the number of postings
    that clicking it returns."""
    for top in _tree(board):
        assert _matching(board, place=[top["value"]]) == top["n"], top["value"]
        for child in top["children"]:
            assert _matching(board, place=[child["value"]]) == child["n"], child["value"]
