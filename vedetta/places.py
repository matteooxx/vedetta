"""Turning a posting's location string into something you can filter on.

Platforms write locations half a dozen ways, and all of these are real examples from
the boards being watched:

    "Remote, Canada; Remote, United Kingdom; Remote, United States"
    "United States (Remote)"
    "Dublin, Ireland; Remote, Israel"
    "GB-London"
    "Ireland - Dublin Hub (Hybrid)"
    "2 Locations"
    "Remote"

A free-text column cannot be faceted, so each posting gets a set of normalised
places in a side table. Splitting on commas keeps both the city and the country
("Dublin, Ireland" becomes both), which is what you want for filtering: picking
*Ireland* should find the Dublin roles, and picking *Dublin* should narrow further.

Two rules the extraction follows:

**"Remote" is a modifier, not a place.** It is recorded as a flag on the posting, so
"Remote, Canada" is Canada-and-remote rather than a place called Remote.

**An unrecognised fragment is kept, not dropped.** A place this module has never
heard of still becomes a facet the reader can see and select. Discarding it would
make a posting unfilterable and effectively invisible, which is the failure mode this
project is organised against.
"""
from __future__ import annotations

import re

from . import regions as regions_mod
from .regions import fold as _fold

# A spaced dash separates places ("Ireland - Dublin Hub"); an unspaced one is part of
# a name ("Saint-Denis"), so only the spaced form splits.
# A dot between a letter and a capitalised word separates a country code from a city
# ("IND.Pune", "MEX.Mexico City"). A dot followed by a space does not, or "St. Louis"
# would come apart.
SPLIT = re.compile(r"[;/|•]|,|\s[-–—]\s|\sor\s|\sand\s|(?<=[A-Za-z])\.(?=[A-Z])",
                   re.I)
PARENS = re.compile(r"[()\[\]]")
WS = re.compile(r"\s+")

# "Home based" is a working pattern, not a place. Catching it here is also genuinely
# informative: one watched employer writes every one of its postings that way.
REMOTE = re.compile(
    r"\b(remote|remotely|work from home|home[- ]based|home office|wfh|anywhere"
    r"|distributed|virtual)\b", re.I)
HYBRID = re.compile(r"\b(hybrid|flexible)\b", re.I)

# Fragments that are not places: modifiers, region groupings, filler.
NOISE = {
    "remote", "remotely", "hybrid", "onsite", "on site", "on-site", "in office",
    "office", "offices", "hq", "headquarters", "various", "multiple", "location",
    "locations", "flexible", "optional", "any", "anywhere", "global", "worldwide",
    "international", "emea", "apac", "amer", "amers", "latam", "na", "n a",
    "wfh", "virtual", "distributed", "field", "travel", "tbd", "other", "all",
    "hub", "based", "area", "region", "metro", "and", "or", "the", "work from home",
    # Region groupings and administrative subdivisions that arrive glued to a city,
    # e.g. "Paris, IDF, fr".
    "idf", "anz", "dach", "benelux", "nordics", "nordic", "mena", "cee", "ukandi",
    "us east", "us west", "east", "west", "north", "south", "central", "eastern",
    "western", "northern", "southern", "coast",
    # Seen live: one employer writes every location as "Home based - EMEA" or
    # "Home Based - Americas", which produced a place called "Home".
    "home", "home based", "office based", "americas", "apj", "unknown",
}

# Variants collapsed so the facet list is short and obvious rather than a long tail
# of spellings for the same country.
ALIASES = {
    "us": "United States", "usa": "United States", "u s": "United States",
    "u s a": "United States", "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom", "gb": "United Kingdom", "u k": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom",
    "nl": "Netherlands", "holland": "Netherlands", "the netherlands": "Netherlands",
    "de": "Germany", "deutschland": "Germany",
    "fr": "France", "es": "Spain", "espana": "Spain", "it": "Italy", "italia": "Italy",
    "ie": "Ireland", "eire": "Ireland", "republic of ireland": "Ireland",
    "pt": "Portugal", "be": "Belgium", "lu": "Luxembourg", "at": "Austria",
    "ch": "Switzerland", "se": "Sweden", "dk": "Denmark", "no": "Norway",
    "fi": "Finland", "pl": "Poland", "cz": "Czechia", "czech republic": "Czechia",
    "ro": "Romania", "ee": "Estonia", "lt": "Lithuania", "lv": "Latvia",
    "ca": "Canada", "in": "India", "sg": "Singapore", "jp": "Japan",
    "au": "Australia", "nz": "New Zealand", "br": "Brazil", "mx": "Mexico",
    "il": "Israel", "ae": "United Arab Emirates", "uae": "United Arab Emirates",
    "za": "South Africa", "cn": "China", "hk": "Hong Kong", "kr": "South Korea",
    "eu": "European Union",
    # Spellings seen live that the title-casing path cannot reach.
    "turkiye": "Turkey", "korea": "South Korea",
    "republic of korea": "South Korea", "korea republic of": "South Korea",
    "viet nam": "Vietnam", "czech": "Czechia",
    # Three-letter country codes, which arrive glued to a city on some platforms:
    # "IND.Pune", "MEX.Mexico City". Ambiguous ones are left out - MAR is Morocco
    # and also the start of half a dozen city names.
    "ind": "India", "mex": "Mexico", "gbr": "United Kingdom", "deu": "Germany",
    "fra": "France", "esp": "Spain", "ita": "Italy", "irl": "Ireland",
    "nld": "Netherlands", "pol": "Poland", "bra": "Brazil", "chn": "China",
    "jpn": "Japan", "aus": "Australia", "phl": "Philippines", "mys": "Malaysia",
    "sgp": "Singapore", "kor": "South Korea", "isr": "Israel",
    "are": "United Arab Emirates", "zaf": "South Africa", "che": "Switzerland",
    "aut": "Austria", "swe": "Sweden", "dnk": "Denmark", "nor": "Norway",
    "fin": "Finland", "cze": "Czechia", "rou": "Romania", "hun": "Hungary",
    "bgr": "Bulgaria", "grc": "Greece", "prt": "Portugal", "bel": "Belgium",
    "lux": "Luxembourg", "ury": "Uruguay", "arg": "Argentina", "chl": "Chile",
    "col": "Colombia", "per": "Peru", "tha": "Thailand", "idn": "Indonesia",
    "vnm": "Vietnam", "pak": "Pakistan", "egy": "Egypt", "sau": "Saudi Arabia",
}

# The same countries in the languages the watched boards actually answer in.
#
# This is not a nicety. Cisco's careers site served its sitemap in French-Canadian,
# so postings arrived as "Krakow, Pologne" and "Austin, Texas, Etats-Unis
# d'Amerique". City names survive a change of language, which is why the Polish
# postings still matched the location rules - country names do not, so a posting in
# Texas read as "location unclear" and was shown rather than guessed away. That is
# the safe direction to fail in and it fills the digest with roles on the wrong
# continent.
#
# A source answering in another language is not a fault to be fixed at the source,
# either: a reader in France watching French employers will meet French locations as
# the normal case. The lookup is accent-folded (see `_fold`), so an entry here is
# written without accents and matches either spelling.
ALIASES.update({
    # France
    "allemagne": "Germany", "autriche": "Austria", "belgique": "Belgium",
    "danemark": "Denmark", "espagne": "Spain", "etats unis": "United States",
    "etats unis d amerique": "United States", "finlande": "Finland",
    "grece": "Greece", "hongrie": "Hungary", "inde": "India", "irlande": "Ireland",
    "italie": "Italy", "japon": "Japan", "norvege": "Norway",
    "pays bas": "Netherlands", "pologne": "Poland", "roumanie": "Romania",
    "royaume uni": "United Kingdom", "suede": "Sweden", "suisse": "Switzerland",
    "tchequie": "Czechia", "republique tcheque": "Czechia", "bresil": "Brazil",
    "mexique": "Mexico", "chine": "China", "coree du sud": "South Korea",
    "afrique du sud": "South Africa", "emirats arabes unis": "United Arab Emirates",
    "singapour": "Singapore", "australie": "Australia",
    "nouvelle zelande": "New Zealand", "israel": "Israel", "pologne pl": "Poland",
    # Germany
    "deutschland de": "Germany", "frankreich": "France", "spanien": "Spain",
    "italien": "Italy", "irland": "Ireland", "niederlande": "Netherlands",
    "polen": "Poland", "schweden": "Sweden", "schweiz": "Switzerland",
    "osterreich": "Austria", "danemark de": "Denmark", "daenemark": "Denmark",
    "finnland": "Finland", "norwegen": "Norway", "tschechien": "Czechia",
    "rumanien": "Romania", "ungarn": "Hungary", "griechenland": "Greece",
    "vereinigtes konigreich": "United Kingdom",
    "vereinigte staaten": "United States", "indien": "India",
    "grossbritannien": "United Kingdom", "belgien": "Belgium",
    "portugal de": "Portugal", "japan": "Japan",
    # Spain and Portugal
    "alemania": "Germany", "francia": "France", "irlanda": "Ireland",
    "paises bajos": "Netherlands", "polonia": "Poland", "suecia": "Sweden",
    "suiza": "Switzerland", "dinamarca": "Denmark", "noruega": "Norway",
    "finlandia": "Finland", "republica checa": "Czechia", "rumania": "Romania",
    "hungria": "Hungary", "grecia": "Greece", "reino unido": "United Kingdom",
    "estados unidos": "United States", "paises baixos": "Netherlands",
    "polonia pt": "Poland", "alemanha": "Germany", "franca": "France",
    "irlanda pt": "Ireland", "suecia pt": "Sweden", "suica": "Switzerland",
    # Italy
    "germania": "Germany", "spagna": "Spain", "olanda": "Netherlands",
    "paesi bassi": "Netherlands", "svezia": "Sweden", "svizzera": "Switzerland",
    "danimarca": "Denmark", "norvegia": "Norway", "finlandia it": "Finland",
    "repubblica ceca": "Czechia", "romania it": "Romania", "ungheria": "Hungary",
    "regno unito": "United Kingdom", "stati uniti": "United States",
    "stati uniti d america": "United States", "irlanda it": "Ireland",
    # Netherlands
    "duitsland": "Germany", "frankrijk": "France", "spanje": "Spain",
    "ierland": "Ireland", "polen nl": "Poland", "zweden": "Sweden",
    "zwitserland": "Switzerland", "denemarken": "Denmark",
    "noorwegen": "Norway", "verenigd koninkrijk": "United Kingdom",
    "verenigde staten": "United States", "belgie": "Belgium",
    "nederland": "Netherlands", "oostenrijk": "Austria", "italie": "Italy",
    # Poland
    "polska": "Poland", "niemcy": "Germany", "francja": "France",
    "hiszpania": "Spain", "irlandia": "Ireland", "holandia": "Netherlands",
    "szwecja": "Sweden", "szwajcaria": "Switzerland", "dania": "Denmark",
    "norwegia": "Norway", "czechy": "Czechia", "wegry": "Hungary",
    "wielka brytania": "United Kingdom",
    "stany zjednoczone": "United States", "wlochy": "Italy",
    "wloch": "Italy", "austria pl": "Austria",
})

# Every country name the region tables know, for the whole-fragment check below.
#
# Without it the token loop takes "South Africa" apart, discards "south" as a
# direction word and leaves a place called "Africa" - and now that Africa is a region
# name, that was about to start deciding continents. "South Korea" became "Korea" the
# same way and then matched nothing at all.
KNOWN_COUNTRIES = {name.lower(): name for name in regions_mod.ALL_COUNTRIES}

# Cities and subdivisions, for the same reason one step down. A name beginning with a
# direction word was being taken apart by the token loop, which strips "north" and
# "south" as positional noise: "South Carolina" came out as "Carolina", "West
# Virginia" as "Virginia", and "New South Wales" as "New" plus the United Kingdom,
# because Wales resolves to a country. A posting in Sydney therefore read as British,
# which for a reader needing a visa is the difference between two answers.
#
# Checked whole, before anything is split, and the name is kept AS WRITTEN - this
# module reports what the platform said. Working out the country from it is the
# judging layer's job.
def _key(text: str) -> str:
    """The lookup key: folded, lowercased, punctuation to spaces, spaces collapsed.

    One function, used to build the tables and to look in them. The first version
    built the keys one way and searched them another, so "North Rhine-Westphalia"
    missed its own entry over a hyphen.
    """
    return WS.sub(" ", re.sub(r"[^a-z\s]", " ",
                              regions_mod.fold(text).lower())).strip()


KNOWN_PLACES = {_key(name): name for name in regions_mod.CITY_COUNTRY}

# Cities worth keeping even when they arrive glued to a country code, e.g. "GB-London".
GLUED = re.compile(r"^([A-Z]{2})[-–](.+)$")


def _clean(fragment: str) -> str:
    text = PARENS.sub(" ", fragment)
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[^\w\s'\-\.]", " ", text, flags=re.UNICODE)
    return WS.sub(" ", text).strip(" -.")


def _canonical(fragment: str) -> str | None:
    text = _clean(fragment)
    if not text:
        return None
    lowered = re.sub(r"[^a-z\s]", " ", _fold(text).lower())
    lowered = WS.sub(" ", lowered).strip()
    if not lowered:
        return None
    # "2 Locations", "3 offices" and similar carry no place at all.
    if re.fullmatch(r"\d+\s*\w*", lowered):
        return None
    if lowered in ALIASES:
        return ALIASES[lowered]
    if lowered in KNOWN_COUNTRIES:
        return KNOWN_COUNTRIES[lowered]
    if lowered in KNOWN_PLACES:
        return _title(text)
    # A region is a place, not noise. 63 postings in the watched population give no
    # place at all, only a region - "Home based - Worldwide", "Home Based - APAC" -
    # and they were being discarded here, which left them unfilterable and
    # unjudgeable. Checked after the aliases so nothing that already resolved to a
    # country changes meaning.
    group = regions_mod.canonical_group(lowered)
    if group is not None:
        return group
    if lowered in NOISE:
        return None
    return _title(text)


def _title(text: str) -> str:
    """Title-case, leaving an already-capitalised token alone so acronyms survive."""
    def cap(word: str) -> str:
        if word.isupper():
            return word
        return "-".join(part.capitalize() for part in word.split("-"))

    return " ".join(cap(w) for w in text.split())


def _places_in(fragment: str) -> list[str]:
    """Pull every place out of one fragment.

    Handles the three shapes that defeated a simpler version: a modifier glued to a
    name ("United States (Remote)"), a trailing country code ("Warsaw pl"), and an
    administrative subdivision in the middle ("Paris, IDF, fr").
    """
    # "Remote" and "Hybrid" are already recorded as flags; as words they only get in
    # the way of the name.
    stripped = HYBRID.sub(" ", REMOTE.sub(" ", fragment))
    text = _clean(stripped)
    if not text:
        return []

    whole = WS.sub(" ", re.sub(r"[^a-z\s]", " ", _fold(text).lower())).strip()
    if whole in ALIASES:
        return [ALIASES[whole]]
    if whole in KNOWN_COUNTRIES:
        return [KNOWN_COUNTRIES[whole]]
    if whole in KNOWN_PLACES:
        return [_title(text)]
    group = regions_mod.canonical_group(whole)
    if group is not None:
        return [group]
    if not whole or whole in NOISE or re.fullmatch(r"\d+\s*\w*", whole):
        return []
    if len(whole.replace(" ", "")) < 2:
        return []

    out: list[str] = []
    leftovers: list[str] = []
    for token in text.split():
        key = re.sub(r"[^a-z]", "", _fold(token).lower())
        if not key:
            continue
        if key in ALIASES:
            canonical = ALIASES[key]
            if canonical not in out:
                out.append(canonical)
        elif regions_mod.canonical_group(key) is not None:
            canonical = regions_mod.canonical_group(key)
            if canonical not in out:
                out.append(canonical)
        elif key in NOISE:
            continue
        else:
            leftovers.append(token)

    if leftovers:
        name = _canonical(" ".join(leftovers))
        if name and name not in out:
            out.insert(0, name)
    return out


def extract(location: str | None) -> tuple[list[str], bool, bool]:
    """Return (places, is_remote, is_hybrid)."""
    if not location or not location.strip():
        return [], False, False

    is_remote = bool(REMOTE.search(location))
    is_hybrid = bool(HYBRID.search(location))

    expanded: list[str] = []
    for fragment in SPLIT.split(location):
        fragment = fragment.strip()
        if not fragment:
            continue
        glued = GLUED.match(fragment)
        if glued:
            expanded.extend([glued.group(1), glued.group(2)])
        else:
            expanded.append(fragment)

    places: list[str] = []
    for fragment in expanded:
        for place in _places_in(fragment):
            if place not in places:
                places.append(place)
    return places, is_remote, is_hybrid
