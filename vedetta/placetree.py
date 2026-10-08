"""Which place is inside which, worked out from the data and written down.

The location filter was one flat list of 102 values at three different levels:
`EMEA` beside `Ireland` beside `Dublin`, ordered by count. Dublin is inside Ireland,
so picking both found nothing more than Ireland alone, and the numbers read as if
they contradicted each other — Ireland 43, Dublin 37.

Worse, the country counts were wrong. They counted only the postings that wrote the
country's name: Germany said 11 while Berlin alone had 17. Rolled up over its cities
Germany is 24, and that is the number a reader is actually asking for.

Two sources for a place's parent, in this order:

1. **the table in `regions.py`**, which knows Krakow is in Poland;
2. **co-occurrence in the postings**, for anything the table does not know. London
   and Dublin are deliberately absent from the table, their names being ambiguous,
   and they are the two largest values in the whole facet — so without this the two
   places that matter most would have no home.

Co-occurrence needs a majority, not a plurality. With a single vote it is wrong:
"Oeiras" landed under Poland and "Ciudad Mexico" under Germany, each from one
posting that happened to list two places. A parent has to be named by at least half
of that place's postings, and by at least two of them.

The result is a table, not a computation hidden inside a query. A reader can look at
`place_meta` and see why Dublin sits under Ireland, and `vedetta check` can report it.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import regions as regions_mod

MIN_VOTES = 2


def kind_of(place: str) -> str:
    """`region`, `country`, or `place` for everything else."""
    if regions_mod.canonical_group(place):
        return "region"
    if place.lower() in {c.lower() for c in regions_mod.ALL_COUNTRIES}:
        return "country"
    return "place"


def derive(rows: list[tuple[int, str]]) -> dict[str, dict]:
    """Work out canon, parent and kind for every place seen.

    `rows` is (posting_id, place) as stored. Returns {stored place: {...}} ready for
    `place_meta`. Pure, so it can be tested without a database.
    """
    by_posting: dict[int, set[str]] = defaultdict(set)
    places: set[str] = set()
    for posting_id, place in rows:
        by_posting[posting_id].add(place)
        places.add(place)

    canon = {place: regions_mod.canonical_place(place) for place in places}
    kind = {name: kind_of(name) for name in set(canon.values())}

    # How often each place's own postings also name each country.
    votes: dict[str, Counter] = defaultdict(Counter)
    seen: Counter = Counter()
    for stored in by_posting.values():
        names = {canon[p] for p in stored}
        countries = {n for n in names if kind[n] == "country"}
        for name in names:
            if kind[name] != "place":
                continue
            seen[name] += 1
            for country in countries:
                votes[name][country] += 1

    parent_of: dict[str, str | None] = {}
    for name, this_kind in kind.items():
        if this_kind != "place":
            parent_of[name] = None
            continue
        parent = regions_mod.infer_country(name)
        if parent is None and votes[name]:
            country, count = votes[name].most_common(1)[0]
            # A majority, not a plurality. One posting listing two places is not
            # evidence about either of them.
            if count >= MIN_VOTES and count * 2 >= seen[name]:
                parent = country
        parent_of[name] = parent

    return {place: {"canon": canon[place],
                    "parent": parent_of[canon[place]],
                    "kind": kind[canon[place]]}
            for place in places}


def rebuild(conn) -> int:
    """Rewrite `place_meta` from the postings as they stand. Returns the row count.

    Called at the end of a run and by `relabel`, the same two places that write the
    places themselves, so the tree can never describe a set of places that no longer
    exists.
    """
    rows = [(r["posting_id"], r["place"]) for r in conn.execute(
        "SELECT posting_id, place FROM posting_place")]
    meta = derive(rows)
    conn.execute("DELETE FROM place_meta")
    conn.executemany(
        "INSERT INTO place_meta (place, canon, parent, kind) VALUES (?,?,?,?)",
        [(place, m["canon"], m["parent"], m["kind"]) for place, m in meta.items()])
    conn.commit()
    return len(meta)
