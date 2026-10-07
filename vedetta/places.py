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

# A spaced dash separates places ("Ireland - Dublin Hub"); an unspaced one is part of
# a name ("Saint-Denis"), so only the spaced form splits.
SPLIT = re.compile(r"[;/|•]|,|\s[-–—]\s|\sor\s|\sand\s", re.I)
PARENS = re.compile(r"[()\[\]]")
WS = re.compile(r"\s+")

REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed|virtual)\b", re.I)
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
}

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
    lowered = re.sub(r"[^a-z\s]", " ", text.lower())
    lowered = WS.sub(" ", lowered).strip()
    if not lowered or lowered in NOISE:
        return None
    # "2 Locations", "3 offices" and similar carry no place at all.
    if re.fullmatch(r"\d+\s*\w*", lowered):
        return None
    if lowered in ALIASES:
        return ALIASES[lowered]
    # Title-case, but leave an already-capitalised token alone so acronyms survive.
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

    whole = WS.sub(" ", re.sub(r"[^a-z\s]", " ", text.lower())).strip()
    if whole in ALIASES:
        return [ALIASES[whole]]
    if not whole or whole in NOISE or re.fullmatch(r"\d+\s*\w*", whole):
        return []

    out: list[str] = []
    leftovers: list[str] = []
    for token in text.split():
        key = re.sub(r"[^a-z]", "", token.lower())
        if not key:
            continue
        if key in ALIASES:
            canonical = ALIASES[key]
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
