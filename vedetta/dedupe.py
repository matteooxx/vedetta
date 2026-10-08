"""Finding postings stored twice because a source answered in two languages.

Cisco's robots.txt declares two sitemaps, one French-Canadian and one English, and
the adapter followed both. Every opening was therefore recorded twice - 2,752 rows
for 1,376 real jobs - under two URLs, with its location in two languages. Nothing
reconciled them: reconciliation matches on employer, normalised title and normalised
location, and "Krakow, Pologne" does not normalise to "Krakow, Poland".

The adapter no longer follows translations of one sitemap, so no new pairs appear.
This is for the pairs already in the database, which will not clear themselves in
any useful way: left alone, the abandoned language simply stops being seen and gets
closed, which puts 1,376 closures in one digest and reads as a thousand jobs
disappearing overnight.

What it does NOT do is delete anything. The duplicate is linked to the original
through `dup_of` and marked closed, which is what the schema already means by a
duplicate and what the interface already hides. Triage decisions, labels and history
stay exactly where they are, because a decision recorded against a row is the one
thing here that cannot be rebuilt by polling again.

It reports and changes nothing unless asked. A guess about which of two rows is the
real one is a guess, and this one is made by URL shape rather than by content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import places as places_mod
from .adapters.sitemap import _locales_in


@dataclass
class Pair:
    keep_id: int
    keep_url: str
    drop_id: int
    drop_url: str
    title: str
    employer: str
    locales: str


# A job id's stable part ends at its last digit. Cisco writes
# CISCISGLOBAL2021327EXTERNALENGLOBAL in English and CISCISGLOBAL2021327EXTERNALFRCA
# in French: the same opening, the same number, a different language tacked on the
# end. Four digits are required before this counts as an identifier at all, so a
# slug that merely happens to contain a number proves nothing.
_ID_CORE = re.compile(r"^(.*\d{4,}\d*?)(?=[^\d]*$)")


def _id_core(path: str) -> str | None:
    """The job identifier with any trailing language marker removed."""
    segments = [s for s in path.rstrip("/").split("/") if s]
    if len(segments) < 2:
        return None
    match = _ID_CORE.match(segments[-2])
    return match.group(1).lower() if match else None


def _identifier_tail(path: str) -> str:
    """The last two path segments, which is where a platform puts its job id.

    Cisco writes `/job/CISCISGLOBAL2025805EXTERNALENGLOBAL/Full-Stack-Engineer`,
    where the id itself carries the language - EXTERNALENGLOBAL against
    EXTERNALFRCA - so the ids differ even though the opening is the same. The
    comparison therefore leans on the title, which is why this is only ever applied
    within one employer and one normalised title.
    """
    return path.rstrip("/").rsplit("/", 1)[-1].lower()


def find(conn) -> list[Pair]:
    """Every pair of postings that are one opening written in two languages.

    Four things have to agree before two rows are called the same opening, and each
    one is there to keep a real posting from being folded away:

    * the same employer and the same normalised title;
    * the same URL tail - the platform's slug for the job, which survives
      translation;
    * **either** the same places, compared after normalisation, so "Krakow, Pologne"
      and "Krakow, Poland" match while Krakow and Dublin never do - **or** the same
      job identifier, read from the URL with any trailing language marker removed,
      which is the platform itself saying the two are one job. The places test alone
      left two thirds of the Cisco pairs standing, because Cisco translates the city
      as well: Bruxelles does not normalise to Brussels. Either way the test
      separates a translation from two genuine openings that share a title, which
      Cisco posts constantly;
    * **different** languages in the URL. Two rows in the same language are never a
      translation of each other, whatever else they have in common.

    A first version keyed on employer, title and URL tail alone. Cisco posts one
    title in several cities under URLs ending in the same slug, so that version
    would have folded real openings together - the one outcome this project treats as
    unacceptable. It passed its test, because the test gave the two openings
    different slugs and so never asked the question.

    Rows already flagged `dup_of` are included. That flag means "possibly the same
    as", shows as a tag and hides nothing, which is right for a suspected duplicate
    and not enough for a proven one.
    """
    rows = conn.execute(
        """SELECT p.id, p.employer_id, p.title, p.title_norm, p.location, p.url,
                  p.first_seen_run, p.closed_run, e.display_name AS employer
           FROM posting p JOIN employer e ON e.id = p.employer_id
           WHERE p.url IS NOT NULL
           ORDER BY p.id""").fetchall()

    buckets: dict[tuple, list] = {}
    for row in rows:
        locales = _locales_in(row["url"])
        if not locales:
            # No language in the URL at all: nothing here can call it a translation.
            continue
        path = urlparse(row["url"]).path
        places, _, _ = places_mod.extract(row["location"])
        key = (row["employer_id"], row["title_norm"], _identifier_tail(path))
        buckets.setdefault(key, []).append(
            (row, tuple(locales), frozenset(places), _id_core(path)))

    pairs: list[Pair] = []
    for group in buckets.values():
        if len({item[1] for item in group}) < 2:
            continue
        # The oldest row is kept. It holds the history - the first sighting, and any
        # triage decision made since - and the newer ones are the copies that
        # arrived when the second language appeared.
        group.sort(key=lambda item: (item[0]["first_seen_run"], item[0]["id"]))
        keep, keep_locales, keep_places, keep_core = group[0]
        for drop, drop_locales, drop_places, drop_core in group[1:]:
            if drop["closed_run"] is not None or drop_locales == keep_locales:
                continue
            # Either proof will do, and neither is a guess. Matching places say the
            # two describe the same job in the same city; a matching identifier says
            # the platform itself calls them the same job. The second exists because
            # the first fails wherever the *city* is translated too - Bruxelles
            # against Brussels - which left two thirds of the Cisco pairs standing.
            same_place = keep_places == drop_places
            same_job = keep_core is not None and keep_core == drop_core
            if not (same_place or same_job):
                continue
            pairs.append(Pair(
                keep_id=keep["id"], keep_url=keep["url"],
                drop_id=drop["id"], drop_url=drop["url"],
                title=keep["title"], employer=keep["employer"],
                locales=f"{'/'.join(keep_locales)} kept, "
                        f"{'/'.join(drop_locales)} folded, matched on "
                        f"{'the job id' if same_job else 'the places'}"))
    return pairs


def apply(conn, pairs: list[Pair], run_id: int) -> int:
    """Link each duplicate to its original and close it. Deletes nothing.

    `run_id` is the run the closure is recorded against - the latest one, so the
    1,376 rows are already closed by the time the next run looks. Leaving them for
    close_missing to find would put every one of them in a single digest's closure
    count, which reads as a thousand openings vanishing overnight.
    """
    for pair in pairs:
        conn.execute(
            "UPDATE posting SET dup_of=?, closed_run=COALESCE(closed_run, ?) "
            "WHERE id=?",
            (pair.keep_id, run_id, pair.drop_id))
    conn.commit()
    return len(pairs)
