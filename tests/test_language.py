"""A source answering in the wrong language.

Cisco's robots.txt declares two sitemaps, `/ca/fr/sitemap_index.xml` and
`/global/en/sitemap_index.xml`, and the adapter followed both. Two consequences, and
the second was much worse than the first:

* locations arrived as "Krakow, Pologne" and "Austin, Texas, Etats-Unis d'Amerique".
  City names survive a change of language, so the Polish postings still matched the
  location rules; country names did not, so a posting in Texas read as "location
  unclear - shown rather than guessed away" and counted as workable. The safe
  direction to fail in, and it fills the digest with roles on the wrong continent.
* every opening was stored twice. 2,752 rows for 1,376 real jobs, because a
  translated posting has a different URL and a location that does not normalise to
  the same string, so reconciliation had nothing to match on. The digest reported the
  same job twice, in two languages, as two new openings.

A source answering in another language is not a fault at the source. A reader in
France watching French employers meets French locations as the normal case.
"""
from __future__ import annotations

import pytest

from vedetta import dedupe
from vedetta import db as db_mod
from vedetta.adapters.sitemap import SitemapAdapter
from vedetta.places import extract


# --- the places the digest was getting wrong -------------------------------

@pytest.mark.parametrize("location,expected", [
    ("Krakow, Pologne", ["Krakow", "Poland"]),
    ("Krakow, Pologne; Warsaw, Pologne", ["Krakow", "Poland", "Warsaw"]),
    ("Austin, Texas, États-Unis d'Amérique", ["Austin", "Texas", "United States"]),
    ("Fulton, Maryland, États-Unis d'Amérique", ["Fulton", "Maryland", "United States"]),
    ("Ahmedabad, Inde", ["Ahmedabad", "India"]),
    ("München, Deutschland", ["München", "Germany"]),
    ("Mailand, Italien", ["Mailand", "Italy"]),
    ("Mediolan, Włochy", ["Mediolan", "Italy"]),
    ("Madrid, España", ["Madrid", "Spain"]),
    ("Amsterdam, Nederland", ["Amsterdam", "Netherlands"]),
    ("Lisboa, Países Baixos", ["Lisboa", "Netherlands"]),
])
def test_a_country_named_in_another_language_is_still_that_country(location, expected):
    places, _, _ = extract(location)
    assert places == expected


def test_remote_still_reads_as_a_flag_in_another_language():
    places, is_remote, _ = extract("Remote, Pays-Bas")
    assert (places, is_remote) == (["Netherlands"], True)


def test_accents_are_folded_for_matching_and_kept_for_display():
    """The lookup key drops everything outside a-z, so without folding
    "Etats-Unis d'Amerique" arrives as "tats unis d am rique" and no alias could
    ever reach it. What the reader sees must not change."""
    places, _, _ = extract("Zürich, Suisse")
    assert places == ["Zürich", "Switzerland"]


def test_an_unknown_country_is_still_kept_rather_than_dropped():
    """The standing rule: a fragment this module has never heard of becomes a facet
    the reader can see, under whatever name the platform used. Dropping it would make
    the posting unfilterable, which is the failure this project is organised against -
    so the alias table being incomplete costs tidiness, never a posting."""
    places, _, _ = extract("Tbilisi, Sakartvelo")
    assert places == ["Tbilisi", "Sakartvelo"]


# --- which sitemaps get followed -------------------------------------------

def _kept(urls, language="en", prefer=None):
    adapter = SitemapAdapter()
    return adapter._one_per_language(urls, language, prefer=prefer), adapter.notes


CISCO = ["https://careers.cisco.com/ca/fr/sitemap_index.xml",
         "https://careers.cisco.com/global/en/sitemap_index.xml"]


def test_only_one_translation_of_a_sitemap_is_followed():
    kept, notes = _kept(CISCO)
    assert kept == ["https://careers.cisco.com/global/en/sitemap_index.xml"]
    assert notes and "skipping" in notes[0]


def test_the_reader_can_ask_for_the_other_language():
    kept, _ = _kept(CISCO, language="fr")
    assert kept == ["https://careers.cisco.com/ca/fr/sitemap_index.xml"]


def test_the_choice_is_reported_rather_than_made_silently():
    """It is a guess about someone else's site, and the note says how to override."""
    _, notes = _kept(CISCO)
    assert "language" in notes[0] and "sitemap_include" in notes[0]


@pytest.mark.parametrize("urls", [
    # Same file name, different content. Both must survive, or a whole section of a
    # site stops being watched.
    ["https://x.test/sitemap.xml", "https://x.test/news/sitemap.xml"],
    ["https://x.test/sitemap-jobs.xml", "https://x.test/sitemap-pages.xml"],
])
def test_sitemaps_that_are_not_translations_are_all_followed(urls):
    kept, notes = _kept(urls)
    assert kept == urls
    assert notes == []


def test_the_canonical_sitemap_wins_when_the_language_is_not_on_offer():
    kept, _ = _kept(["https://x.test/sitemap.xml", "https://x.test/de/sitemap.xml"])
    assert kept == ["https://x.test/sitemap.xml"]


def test_a_hand_recorded_endpoint_is_never_dropped_for_a_guess():
    """Somebody looked at this sitemap during discovery and wrote it down. That
    beats an inference from a URL's shape."""
    urls = ["https://x.test/fr/sitemap.xml", "https://x.test/en/sitemap.xml"]
    kept, _ = _kept(urls, language="en", prefer="https://x.test/fr/sitemap.xml")
    assert kept == ["https://x.test/fr/sitemap.xml"]


# --- the duplicates already in the database --------------------------------

EN = ("https://careers.cisco.com/global/en/job/"
      "CISCISGLOBAL2025805EXTERNALENGLOBAL/Full-Stack-Engineer")
FR = ("https://careers.cisco.com/ca/fr/job/"
      "CISCISGLOBAL2025805EXTERNALFRCA/Full-Stack-Engineer")


@pytest.fixture()
def conn(tmp_path):
    connection = db_mod.connect(tmp_path / "v.db")
    connection.execute(
        "INSERT INTO employer (id, key, display_name) VALUES (1,'cisco','Cisco')")
    connection.execute(
        "INSERT INTO run (id, started_at) VALUES (1,'2026-10-07T00:00:00+00:00')")
    connection.execute(
        "INSERT INTO run (id, started_at) VALUES (2,'2026-10-08T00:00:00+00:00')")
    connection.commit()
    yield connection
    connection.close()


def _store(conn, posting_id, title, location, url, first_run):
    conn.execute(
        "INSERT INTO posting (id, employer_id, title, title_norm, location, "
        "location_norm, url, first_seen_run, last_seen_run) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (posting_id, 1, title, title.lower(), location, (location or "").lower(),
         url, first_run, first_run))
    conn.commit()


def test_the_same_opening_in_two_languages_is_one_pair(conn):
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland", EN, 1)
    _store(conn, 2, "Full Stack Engineer", "Krakow, Pologne", FR, 2)
    pairs = dedupe.find(conn)
    assert len(pairs) == 1
    # The older row is kept: it holds the first sighting and any decision made since.
    assert (pairs[0].keep_id, pairs[0].drop_id) == (1, 2)


def test_two_real_openings_with_the_same_title_and_slug_are_left_alone(conn):
    """Cisco posts one title in several cities, under URLs ending in the same slug.
    Folding those together would hide an opening, which costs more than a duplicate
    ever does.

    The first version of this test gave the two openings different slugs, so it
    never asked the question - and the implementation it was passing against would
    have folded them.
    """
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland",
           "https://careers.cisco.com/global/en/job/AAA/Full-Stack-Engineer", 1)
    _store(conn, 2, "Full Stack Engineer", "Dublin, Ireland",
           "https://careers.cisco.com/global/en/job/BBB/Full-Stack-Engineer", 1)
    assert dedupe.find(conn) == []


def test_two_rows_in_the_same_language_are_never_a_translation(conn):
    """Everything else about them can agree. Same language is a full stop."""
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland",
           "https://careers.cisco.com/global/en/job/AAA/Full-Stack-Engineer", 1)
    _store(conn, 2, "Full Stack Engineer", "Krakow, Poland",
           "https://careers.cisco.com/global/en/job/BBB/Full-Stack-Engineer", 2)
    assert dedupe.find(conn) == []


def test_the_same_slug_in_two_languages_but_two_cities_is_left_alone(conn):
    """A translated posting keeps its city. Two cities means two openings, even
    across languages."""
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland",
           "https://careers.cisco.com/global/en/job/AAA/Full-Stack-Engineer", 1)
    _store(conn, 2, "Full Stack Engineer", "Dublin, Irlande",
           "https://careers.cisco.com/ca/fr/job/AAAFRCA/Full-Stack-Engineer", 2)
    assert dedupe.find(conn) == []


def test_a_row_already_flagged_as_a_suspected_duplicate_is_still_considered(conn):
    """`dup_of` means "possibly the same as": it shows a tag and hides nothing,
    which is right for a suspicion and not enough for a proven translation."""
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland", EN, 1)
    _store(conn, 2, "Full Stack Engineer", "Krakow, Pologne", FR, 2)
    conn.execute("UPDATE posting SET dup_of=1 WHERE id=2")
    conn.commit()
    pairs = dedupe.find(conn)
    assert [(p.keep_id, p.drop_id) for p in pairs] == [(1, 2)]


def test_a_posting_with_no_language_in_its_url_is_never_folded(conn):
    _store(conn, 1, "Platform Engineer", "Dublin, Ireland",
           "https://boards.greenhouse.io/x/jobs/1", 1)
    _store(conn, 2, "Platform Engineer", "Dublin, Ireland",
           "https://boards.greenhouse.io/x/jobs/2", 2)
    assert dedupe.find(conn) == []


def test_applying_links_and_closes_without_deleting(conn):
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland", EN, 1)
    _store(conn, 2, "Full Stack Engineer", "Krakow, Pologne", FR, 2)
    conn.execute(
        "INSERT INTO label (posting_id, rule_id, kind, severity, explain, "
        "produced_by, created_at) VALUES (2,'r','cluster','positive','x','rules','t')")
    conn.commit()

    assert dedupe.apply(conn, dedupe.find(conn), run_id=2) == 1
    row = conn.execute(
        "SELECT dup_of, closed_run FROM posting WHERE id=2").fetchone()
    assert (row["dup_of"], row["closed_run"]) == (1, 2)
    # Nothing was deleted, and the row the reader keeps is untouched.
    assert conn.execute("SELECT count(*) FROM posting").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM label").fetchone()[0] == 1
    kept = conn.execute("SELECT dup_of, closed_run FROM posting WHERE id=1").fetchone()
    assert (kept["dup_of"], kept["closed_run"]) == (None, None)


def test_a_translated_city_is_matched_on_the_job_id_instead(conn):
    """Cisco translates the city too - Bruxelles, not Brussels - so the places no
    longer agree. The job identifier does: the same number with a different language
    marker after it. Without this proof two thirds of the real pairs stood."""
    _store(conn, 1, "Client Executive", "Brussels, Belgium",
           "https://careers.cisco.com/global/en/job/"
           "CISCISGLOBAL2021327EXTERNALENGLOBAL/Client-Executive", 1)
    _store(conn, 2, "Client Executive", "Bruxelles, Belgique",
           "https://careers.cisco.com/ca/fr/job/"
           "CISCISGLOBAL2021327EXTERNALFRCA/Client-Executive", 2)
    pairs = dedupe.find(conn)
    assert [(p.keep_id, p.drop_id) for p in pairs] == [(1, 2)]
    assert "the job id" in pairs[0].locales


def test_a_different_job_id_is_not_folded_however_alike(conn):
    """One digit apart is a different opening. Same slug, same title, two languages
    and still not the same job."""
    _store(conn, 1, "Client Executive", "Brussels, Belgium",
           "https://careers.cisco.com/global/en/job/"
           "CISCISGLOBAL2021327EXTERNALENGLOBAL/Client-Executive", 1)
    _store(conn, 2, "Client Executive", "Milano, Italia",
           "https://careers.cisco.com/ca/fr/job/"
           "CISCISGLOBAL2021328EXTERNALFRCA/Client-Executive", 2)
    assert dedupe.find(conn) == []


def test_an_identifier_too_short_to_be_one_proves_nothing(conn):
    """Four digits are required. A slug that happens to contain a number is not an
    identifier, and treating it as one would fold openings together."""
    _store(conn, 1, "Engineer", "Brussels, Belgium",
           "https://x.test/en/job/12/Engineer", 1)
    _store(conn, 2, "Engineer", "Milano, Italia",
           "https://x.test/it/job/12/Engineer", 2)
    assert dedupe.find(conn) == []


def test_running_it_twice_changes_nothing_the_second_time(conn):
    _store(conn, 1, "Full Stack Engineer", "Krakow, Poland", EN, 1)
    _store(conn, 2, "Full Stack Engineer", "Krakow, Pologne", FR, 2)
    dedupe.apply(conn, dedupe.find(conn), run_id=2)
    assert dedupe.find(conn) == []
