"""Regions, legal blocs, and inferring a country from a city.

Measured on the live database before any of this existed: 184 of 416 workable
postings had **no location verdict at all** — 44% — and a rule naming countries could
not reach any of them. Three causes, needing three different answers:

* 95 named a city and no country: "San Francisco", "Bengaluru", "Toronto";
* 63 named no place at all, only a region: "Home based - Worldwide",
  "Home Based - APAC; Home based - EMEA". No table of cities will ever reach those;
* 10 named a country nobody had listed — Greece, Hungary, the United Arab Emirates —
  and two of those three are in the EU and should have been *acceptable*. The long
  tail cuts both ways, which is the argument for blocs over hand-written lists.

The dangerous half is the inference: it can **exclude** a posting, which is the
expensive direction to be wrong in. So the tests below spend more effort on what must
*not* happen than on what must.
"""
from __future__ import annotations

import pytest

from vedetta import regions
from vedetta.profile import Profile

PROFILE = {
    "locations": {
        "preferred": ["Dublin", "Ireland"],
        "acceptable": ["EU", "Remote EU", "Italy", "Poland", "Krakow"],
        "conditional": ["United Kingdom", "London", "Switzerland"],
        "excluded": ["Asia", "North America", "South America", "Oceania", "Africa"],
    },
}


@pytest.fixture(scope="module")
def profile():
    return Profile.from_dict(PROFILE)


def verdict(profile, location):
    return profile.location_verdict(location)[0]


def explain(profile, location):
    return profile.location_verdict(location)[1]


# --- the blocs ------------------------------------------------------------

def test_the_eu_is_twenty_seven_countries():
    assert len(set(regions.countries_in("EU"))) == 27
    for member in ("Bulgaria", "Hungary", "Greece", "Croatia", "Malta", "Cyprus"):
        assert member in regions.countries_in("EU")


def test_the_eea_adds_three_and_schengen_swaps_some():
    assert set(regions.countries_in("EEA")) - set(regions.countries_in("EU")) == {
        "Iceland", "Liechtenstein", "Norway"}
    schengen = set(regions.countries_in("Schengen"))
    assert "Switzerland" in schengen
    assert "Ireland" not in schengen, "Ireland is in the EU but not in Schengen"


def test_europe_is_wider_than_the_eu_and_that_is_the_point():
    """For an Italian citizen the boundary that matters is legal, not geographic."""
    europe = set(regions.countries_in("Europe"))
    assert {"United Kingdom", "Switzerland", "Serbia"} <= europe
    assert not {"United Kingdom", "Switzerland", "Serbia"} & set(
        regions.countries_in("EU"))


def test_a_country_nobody_listed_is_reached_by_the_bloc(profile):
    """Greece, Hungary and Bulgaria were all workable-by-accident before this,
    because they were missing from a hand-written list of acceptable countries."""
    for location in ("Athens, Greece", "Budapest, Hungary", "Sofia, Bulgaria",
                     "Zagreb, Croatia"):
        assert verdict(profile, location) == "acceptable", location


def test_a_country_in_no_group_the_reader_named_stays_unknown(profile):
    """Serbia is in Europe but not in the EU, and this profile names neither
    Serbia nor Europe. Unknown, never excluded."""
    assert verdict(profile, "Belgrade, Serbia") == "unknown"


# --- regions a platform writes in a location field ------------------------

@pytest.mark.parametrize("location,expected", [
    ("Home based - Worldwide", "acceptable"),
    ("Home based - EMEA", "acceptable"),
    ("Home Based - APAC", "excluded"),
    ("Home Based - Americas", "excluded"),
    ("Remote - LATAM", "excluded"),
    ("Home Based - APAC; Home based - EMEA", "acceptable"),
])
def test_a_regions_verdict_is_derived_from_the_countries_in_it(profile, location,
                                                               expected):
    """Nothing new to decide: a region is worth the best verdict among its countries,
    which is the rule already used for a posting with several locations. A role open
    to all of EMEA can be done from Milan; APAC contains nothing acceptable."""
    assert verdict(profile, location) == expected


def test_a_region_never_earns_the_preferred_bucket(profile):
    """"Worldwide" contains Ireland, which this profile prefers — but the posting is
    not *in* Dublin, it merely permits it. Reporting it as preferred would put it at
    the top of the digest on a claim the posting never made."""
    assert verdict(profile, "Home based - Worldwide") == "acceptable"
    assert verdict(profile, "Dublin, Ireland") == "preferred"


def test_a_region_on_both_sides_still_matches(profile):
    """APAC in the posting against Asia in the profile: neither names a country, and
    a third of the postings this feature exists for are shaped like that."""
    assert verdict(profile, "Home Based - APAC") == "excluded"
    assert "APAC" in explain(profile, "Home Based - APAC")


# --- a country from a city ------------------------------------------------

@pytest.mark.parametrize("location,expected", [
    ("San Francisco", "excluded"),
    ("San Francisco, California", "excluded"),
    ("Seattle", "excluded"),
    ("New York", "excluded"),
    ("Chicago", "excluded"),
    ("Toronto", "excluded"),
    ("Bengaluru", "excluded"),
    ("Gurugram", "excluded"),
    ("Kuala Lumpur", "excluded"),
    ("Sao Jose dos Campos", "excluded"),
    ("Milan", "acceptable"),
    ("Krakow", "acceptable"),
])
def test_a_city_with_no_country_can_be_judged(location, expected, profile):
    assert verdict(profile, location) == expected


def test_the_inference_says_what_it_inferred_and_from_what(profile):
    """This is the one guess here that can exclude a posting. An exclusion whose
    reasoning the reader cannot see is one they cannot argue with."""
    assert "inferred from San Francisco" in explain(profile, "San Francisco")


def test_a_stated_country_explains_itself_rather_than_the_city(profile):
    """"Austin, Texas, United States" must not report itself through a city this
    module looked up when the platform printed the country."""
    assert "inferred" not in (explain(profile, "Austin, Texas, United States") or "")


@pytest.mark.parametrize("city", [
    # Each of these belongs to more than one country, and a wrong answer excludes a
    # posting the reader could have taken. They are left out of the table by name.
    "London", "Birmingham", "Cambridge", "Richmond", "Newcastle", "Rochester",
    "Windsor", "Hamilton", "Victoria", "Perth", "Wellington", "Toledo", "Georgia",
])
def test_an_ambiguous_city_is_never_resolved(city):
    assert regions.infer_country(city) is None, (
        f"{city} belongs to more than one country")


def test_an_unknown_city_is_not_invented():
    assert regions.infer_country("Tbilisi") is None
    assert regions.infer_country("Narnia") is None


def test_a_state_code_that_collides_with_a_country_is_left_out():
    """CA is Canada before California, IL is Israel before Illinois, IN is India
    before Indiana. Getting one of those wrong excludes the wrong continent."""
    for code in ("CA", "IL", "IN", "DE", "SE", "NO", "IT", "ES", "IE"):
        assert regions.infer_country(code) is None, code
    # And the ones that do not collide are kept, because they arrive constantly.
    assert regions.infer_country("WA") == "United States"
    assert regions.infer_country("NY") == "United States"


# --- specificity: a narrow rule beats a broad one -------------------------

def test_a_named_country_beats_a_region_that_contains_it(profile):
    """With `EU` acceptable and `United Kingdom` conditional, a London posting has to
    stay conditional. Without this the broad rule would silently erase the visa
    warning on the narrow one — and losing that warning means applying for a job that
    needs sponsorship without knowing it."""
    assert verdict(profile, "London, United Kingdom") == "conditional"
    assert verdict(profile, "London") == "conditional"
    assert verdict(profile, "Manchester, United Kingdom") == "conditional"


def test_a_conditional_country_inside_an_acceptable_bloc_stays_conditional():
    """Ireland is in the EU. A reader who marks Ireland conditional means it."""
    profile = Profile.from_dict({"locations": {
        "acceptable": ["EU"], "conditional": ["Ireland"]}})
    assert profile.location_verdict("Dublin, Ireland")[0] == "conditional"


def test_the_best_verdict_still_wins_across_real_alternatives(profile):
    """Specificity decides within one location. Between two locations the best
    verdict wins, because one workable office makes the posting workable."""
    assert verdict(profile, "Dublin, Ireland; Austin, United States") == "preferred"
    assert verdict(profile, "San Francisco; Krakow, Poland") == "acceptable"


# --- the direction that matters -------------------------------------------

def test_nothing_usable_is_still_unknown_rather_than_excluded(profile):
    for location in ("N/A", "2 Locations", "LOCATION", "", None, "various"):
        assert verdict(profile, location) == "unknown", repr(location)


def test_an_acceptable_city_is_never_excluded_by_an_inference(profile):
    """The inference runs only where no country is stated, and it must never turn a
    posting the reader could take into one they cannot."""
    for location in ("Dublin", "Milan", "Krakow", "Berlin", "Amsterdam", "Lisbon",
                     "Warsaw", "Madrid", "Paris", "Vienna", "Prague"):
        assert verdict(profile, location) in ("preferred", "acceptable"), location


# --- the ways a broad rule can let a continent in -------------------------

@pytest.mark.parametrize("location", [
    # Found by predicting the change against the live database before applying it.
    # "EU" is a substring of both of these, and `EU` is the broadest rule in the
    # file: the two together made a Brazilian and a Korean posting acceptable.
    "Eus\u00e9bio, Ceara, Brazil",
    "Seoul, Seoul Teugbyeolsi, Korea, Republic of",
    "Busan, Busan Gwang'yeogsi, Korea, Republic of",
])
def test_a_region_name_is_not_matched_inside_a_place_name(profile, location):
    assert verdict(profile, location) == "excluded", location


def test_a_short_place_name_needs_a_whole_word():
    """"US" is inside "Prussia". Substring matching is right for "Ireland" catching
    "Remote - Ireland" and wrong below about four characters."""
    p = Profile.from_dict({"locations": {"excluded": ["US"]}})
    assert p.location_verdict("Prussia, Germany")[0] == "unknown"
    assert p.location_verdict("Austin, US")[0] == "excluded"


@pytest.mark.parametrize("location,expected", [
    # A direction word in a country name was being discarded by the token loop,
    # leaving a place called "Africa" - which, now that Africa is a region name, was
    # about to start deciding continents on its own.
    ("Cape Town, South Africa", "excluded"),
    ("Remote, South Korea", "excluded"),
    ("Seoul, Korea, Republic of", "excluded"),
    ("Istanbul, T\u00fcrkiye", "excluded"),
    # A country code glued to a city, seen on two platforms.
    ("IND.Pune", "excluded"),
    ("MEX.Mexico City", "excluded"),
])
def test_a_country_survives_the_way_the_platform_wrote_it(profile, location,
                                                          expected):
    assert verdict(profile, location) == expected


def test_a_city_name_with_a_dot_is_not_taken_apart():
    """The dot rule splits "IND.Pune"; it must not split "St. Louis".

    Note what `extract` returns: the places the platform named, and not the country
    worked out from them. The inference lives in the judging layer on purpose, so the
    facet list stays a record of what was actually published.
    """
    from vedetta.places import extract
    assert extract("St. Louis, Missouri")[0] == ["St. Louis", "Missouri"]


def test_georgia_decides_nothing_by_itself():
    """A country and a US state. A posting reading "Georgia; North Carolina;
    Washington, DC" was excluded as Asian on the strength of the first word - right
    verdict, wrong reasoning, which is the same thing as wrong."""
    assert "Georgia" not in regions.countries_in("Asia")
    assert regions.infer_country("Georgia") is None


@pytest.mark.parametrize("city,country", [
    ("S\u00e3o Paulo", "Brazil"),
    ("D\u00fcsseldorf", "Germany"),
    ("Krak\u00f3w", "Poland"),
    ("Z\u00fcrich", "Switzerland"),
    ("Malm\u00f6", "Sweden"),
    ("Gda\u0144sk", "Poland"),
    ("M\u00fcnchen", "Germany"),
])
def test_the_inference_folds_accents(city, country):
    """The table is written without accents and the platforms are not. Before this,
    every posting still unjudged after the region work was an accent."""
    assert regions.infer_country(city) == country


# --- names that begin with a direction word -------------------------------

@pytest.mark.parametrize("location,expected", [
    # Every one of these was being taken apart by the token loop, which strips
    # "north" and "south" as positional noise.
    ("Raleigh, North Carolina, United States",
     ["Raleigh", "North Carolina", "United States"]),
    ("Charleston, South Carolina", ["Charleston", "South Carolina"]),
    ("West Virginia", ["West Virginia"]),
    ("North Dakota", ["North Dakota"]),
    ("South Holland, Netherlands", ["South Holland", "Netherlands"]),
    ("North Rhine-Westphalia, Germany", ["North Rhine-Westphalia", "Germany"]),
    ("Western Australia", ["Western Australia"]),
    # The worst of them: "Wales" resolves to a country, so a Sydney posting read as
    # British - which for a reader needing a visa is the difference between
    # "acceptable" and "needs sponsorship".
    ("New South Wales, Australia", ["New South Wales", "Australia"]),
])
def test_a_place_beginning_with_a_direction_survives_whole(location, expected):
    from vedetta.places import extract
    assert extract(location)[0] == expected


def test_a_trailing_country_code_still_resolves():
    """The token loop earns its place: "Warsaw pl" has to become Warsaw in Poland.
    The fix above must not take that away."""
    from vedetta.places import extract
    assert extract("Warsaw pl")[0] == ["Warsaw", "Poland"]
    assert extract("GB-London")[0] == ["United Kingdom", "London"]
    assert extract("Paris, IDF, fr")[0] == ["Paris", "France"]


def test_a_regional_grouping_is_still_dropped():
    """And so does the noise list: "US East" must not produce a place called East."""
    from vedetta.places import extract
    assert extract("US East")[0] == []
