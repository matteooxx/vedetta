"""Regions, legal blocs, and inferring a country from a city.

Three kinds of geographic knowledge that the location rules need and that a reader
should not have to write out by hand.

**Regions and blocs.** A profile that excludes everywhere outside Europe had to list
thirty-nine countries one at a time, and still missed Greece, Hungary and the United
Arab Emirates - which arrived as *unknown* and therefore workable. `EU` is twenty-seven
countries including the ones nobody thought of; `Asia` is one line instead of twenty.

For this reader the boundary that matters is legal rather than geographic: an Italian
citizen can work anywhere in the EEA without asking, while the United Kingdom and
Switzerland are in Europe and need sponsorship. So the vocabulary carries both.

**Platform shorthand.** 63 postings in the watched population give no place at all,
only a region: "Home based - Worldwide", "Home Based - APAC; Home based - EMEA". No
table of cities will ever reach those. Their verdict is **derived** rather than
configured - a region is worth the best verdict among the countries in it, which is
the rule already used for a posting with several locations. A role open to all of EMEA
can be done from Milan, so EMEA reads acceptable; APAC contains nothing acceptable, so
it reads excluded. Nothing new to decide: it falls out of the rules already written.

**A country from a city.** 95 postings name a city and no country - "San Francisco",
"Bengaluru", "Toronto" - so a rule naming countries cannot see them. This is the only
part of this module that guesses, and it guesses in the expensive direction: it can
exclude a posting. So it is deliberately narrow. A city whose name belongs to more
than one country is left out by name, with the reason written down, and the label says
the country was inferred and from what.
"""
from __future__ import annotations

import unicodedata

_UNDECOMPOSABLE = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "þ": "th",
    "ð": "d", "ı": "i", "ʼ": "'",
})


def fold(text: str) -> str:
    """Strip accents for lookup purposes only.

    The key built below removes everything outside a-z, so without this
    "Etats-Unis d'Amerique" arrives as "tats unis d am rique" and matches nothing -
    an accented country name was unreachable however many aliases were listed. The
    display name is taken from the original text, so folding never reaches what the
    reader sees: "Zurich" is matched, "Zürich" is shown.

    A handful of letters do not decompose at all under NFKD - Polish ł, Nordic ø and
    å-as-aa, German ß - so they are translated first. Without that, "Włochy" (Italy,
    in Polish) reduces to "w ochy" and no alias can reach it.
    """
    text = text.translate(_UNDECOMPOSABLE)
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))

# --------------------------------------------------------------------- the blocs

EU = (
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
    "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland",
    "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland",
    "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden",
)

# The EEA adds three; Switzerland is in neither but has free movement by treaty, so
# Schengen is the set that actually describes "can live and work there without a visa
# application" for an EU citizen.
EEA = EU + ("Iceland", "Liechtenstein", "Norway")
SCHENGEN = tuple(sorted(set(EEA) - {"Ireland", "Bulgaria", "Cyprus"} | {"Switzerland"}))

EUROPE = tuple(sorted(set(EEA) | {
    "Switzerland", "United Kingdom", "Serbia", "Albania", "Bosnia and Herzegovina",
    "North Macedonia", "Montenegro", "Kosovo", "Moldova", "Ukraine", "Belarus",
    "Monaco", "Andorra", "San Marino", "Turkey",
}))

NORTH_AMERICA = (
    "United States", "Canada", "Mexico", "Costa Rica", "Panama", "Guatemala",
    "Honduras", "Nicaragua", "El Salvador", "Belize", "Cuba", "Dominican Republic",
    "Jamaica", "Puerto Rico", "Trinidad and Tobago",
)

SOUTH_AMERICA = (
    "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Uruguay", "Paraguay",
    "Bolivia", "Ecuador", "Venezuela",
)

MIDDLE_EAST = (
    "Israel", "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain",
    "Oman", "Jordan", "Lebanon", "Iraq", "Iran", "Egypt",
)

ASIA = (
    "India", "China", "Japan", "South Korea", "Singapore", "Hong Kong", "Taiwan",
    "Malaysia", "Thailand", "Vietnam", "Indonesia", "Philippines", "Pakistan",
    "Bangladesh", "Sri Lanka", "Nepal", "Cambodia", "Myanmar", "Laos", "Mongolia",
    "Kazakhstan", "Uzbekistan", "Azerbaijan", "Armenia", "Turkey",
    # Georgia is deliberately absent. It is a country and a US state, and a posting
    # reading "Georgia; North Carolina; Washington, DC" was being excluded as Asian
    # on the strength of the first word. The verdict happened to be right for that
    # profile and the reasoning was wrong, which is the same thing as being wrong.
    # A reader who means the country can name it.
) + MIDDLE_EAST

AFRICA = (
    "South Africa", "Nigeria", "Kenya", "Egypt", "Morocco", "Tunisia", "Algeria",
    "Ghana", "Ethiopia", "Tanzania", "Uganda", "Rwanda", "Senegal", "Ivory Coast",
    "Cameroon", "Zimbabwe", "Zambia", "Botswana", "Mozambique", "Angola",
)

OCEANIA = ("Australia", "New Zealand", "Fiji", "Papua New Guinea")

ALL_COUNTRIES = tuple(sorted({
    country
    for group in (EUROPE, NORTH_AMERICA, SOUTH_AMERICA, ASIA, AFRICA, OCEANIA)
    for country in group
}))

# Every country this module knows, in every group it belongs to. A country may be in
# several: Egypt is in Africa and the Middle East, Turkey in Europe and Asia.
GROUPS: dict[str, tuple[str, ...]] = {
    "EU": EU,
    "European Union": EU,
    "EEA": EEA,
    "Schengen": SCHENGEN,
    "Europe": EUROPE,
    "North America": NORTH_AMERICA,
    "South America": SOUTH_AMERICA,
    "Americas": NORTH_AMERICA + SOUTH_AMERICA,
    "Asia": ASIA,
    "Middle East": MIDDLE_EAST,
    "Africa": AFRICA,
    "Oceania": OCEANIA,
}

# What a platform writes when a role is open to a whole region. These are the 63
# postings that name no place at all. Resolved to the same groups so their verdict is
# derived from the countries in them rather than guessed at.
#
# "Worldwide" and "Global" include the reader's own country, which is why they come
# out acceptable: a role open to everybody is open to them too.
PLATFORM_REGIONS: dict[str, tuple[str, ...]] = {
    "EMEA": EUROPE + MIDDLE_EAST + AFRICA,
    "EMEIA": EUROPE + MIDDLE_EAST + AFRICA + ("India",),
    "APAC": ASIA + OCEANIA,
    "APJ": ASIA + OCEANIA,
    "APJC": ASIA + OCEANIA + ("China",),
    "ASEAN": ("Singapore", "Malaysia", "Thailand", "Vietnam", "Indonesia",
              "Philippines"),
    "SEA": ("Singapore", "Malaysia", "Thailand", "Vietnam", "Indonesia",
            "Philippines"),
    "AMER": NORTH_AMERICA + SOUTH_AMERICA,
    "AMERS": NORTH_AMERICA + SOUTH_AMERICA,
    "Americas": NORTH_AMERICA + SOUTH_AMERICA,
    "NAMER": NORTH_AMERICA,
    "LATAM": SOUTH_AMERICA + ("Mexico", "Costa Rica", "Panama", "Guatemala"),
    "MENA": MIDDLE_EAST + ("Morocco", "Tunisia", "Algeria"),
    "DACH": ("Germany", "Austria", "Switzerland"),
    "Benelux": ("Belgium", "Netherlands", "Luxembourg"),
    "Nordics": ("Sweden", "Denmark", "Norway", "Finland", "Iceland"),
    "Nordic": ("Sweden", "Denmark", "Norway", "Finland", "Iceland"),
    "CEE": ("Poland", "Czechia", "Slovakia", "Hungary", "Romania", "Bulgaria",
            "Croatia", "Slovenia", "Estonia", "Latvia", "Lithuania", "Serbia"),
    "ANZ": ("Australia", "New Zealand"),
    "UKI": ("United Kingdom", "Ireland"),
    "UKANDI": ("United Kingdom", "Ireland"),
    "Worldwide": EUROPE + NORTH_AMERICA + SOUTH_AMERICA + ASIA + AFRICA + OCEANIA,
    "Global": EUROPE + NORTH_AMERICA + SOUTH_AMERICA + ASIA + AFRICA + OCEANIA,
    "International": EUROPE + NORTH_AMERICA + SOUTH_AMERICA + ASIA + AFRICA + OCEANIA,
    "Anywhere": EUROPE + NORTH_AMERICA + SOUTH_AMERICA + ASIA + AFRICA + OCEANIA,
}

ALL_GROUPS: dict[str, tuple[str, ...]] = {**GROUPS, **PLATFORM_REGIONS}
_BY_LOWER = {name.lower(): name for name in ALL_GROUPS}


def is_group(name: str) -> bool:
    """Whether a name written in a profile is a region rather than a place."""
    return name.strip().lower() in _BY_LOWER


def canonical_group(name: str) -> str | None:
    return _BY_LOWER.get(name.strip().lower())


def countries_in(name: str) -> tuple[str, ...]:
    group = canonical_group(name)
    return ALL_GROUPS[group] if group else ()


def is_platform_region(name: str) -> bool:
    """Whether a name is shorthand a platform writes in a location field.

    Distinguished from a bloc because these appear in *postings*, where they need a
    derived verdict, while `EU` and `Asia` appear in *profiles*, where they are a
    shorthand for a list of countries. A few are both.
    """
    canonical = canonical_group(name)
    return canonical in PLATFORM_REGIONS if canonical else False


# ------------------------------------------------------- a country from a city

# Cities deliberately left out, because the name belongs to more than one country and
# a wrong answer here excludes a posting the reader could have taken:
#
#   London      England and Ontario          Hamilton    Ontario and New Zealand
#   Birmingham  England and Alabama          Victoria    British Columbia and Australia
#   Cambridge   England and Massachusetts    Perth       Scotland and Australia
#   Dublin      Ireland, Ohio and California Toledo      Spain and Ohio
#   Richmond    England, Virginia, BC        Newcastle   England and Australia
#   Rochester   England and New York         Windsor     England and Ontario
#   Georgia     a US state and a country     Wellington  New Zealand and Somerset
#
# Several of those are already in the reader's own rules by name, which is the right
# place for them: a judgement about an ambiguous name belongs to the person it
# affects, not to a table shipped with the program.
CITY_COUNTRY: dict[str, str] = {}


def _add(country: str, *cities: str) -> None:
    for city in cities:
        CITY_COUNTRY[city.lower()] = country


_add("United States",
     "San Francisco", "SF", "San Jose", "Santa Clara", "Sunnyvale", "Mountain View",
     "Palo Alto", "Menlo Park", "Cupertino", "Oakland", "Berkeley", "Los Angeles",
     "San Diego", "Sacramento", "Seattle", "Redmond", "Bellevue", "Portland",
     "New York City", "NYC", "Brooklyn", "Manhattan", "Boston", "Somerville",
     "Chicago", "Austin", "Dallas", "Houston", "San Antonio", "Denver", "Boulder",
     "Atlanta", "Miami", "Orlando", "Tampa", "Philadelphia", "Pittsburgh",
     "Baltimore", "Washington DC", "Arlington", "Reston", "McLean", "Herndon",
     "Raleigh", "Durham", "Charlotte", "Nashville", "Minneapolis", "Detroit",
     "Ann Arbor", "Cleveland", "Columbus", "Cincinnati", "Indianapolis",
     "Kansas City", "St. Louis", "Saint Louis", "Salt Lake City", "Phoenix",
     "Tempe", "Scottsdale", "Tucson", "Las Vegas", "Reno", "Honolulu", "Anchorage",
     "New Orleans", "Memphis", "Louisville", "Milwaukee", "Madison", "Omaha",
     "Des Moines", "Fort Lauderdale", "Jacksonville", "Fulton", "Plano", "Irving")

_add("Canada", "Toronto", "Vancouver", "Montreal", "Ottawa", "Calgary", "Edmonton",
     "Quebec City", "Winnipeg", "Halifax", "Kitchener", "Waterloo", "Mississauga")

_add("India", "Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai",
     "Gurugram", "Gurgaon", "Noida", "Kolkata", "Ahmedabad", "Delhi", "New Delhi")

_add("Ireland", "Cork", "Galway", "Limerick")
_add("United Kingdom", "Edinburgh", "Glasgow", "Manchester", "Leeds", "Bristol",
     "Belfast", "Sheffield", "Nottingham", "Reading", "Cardiff", "Liverpool")
# Both transliterations of a German umlaut, because the folding produces one and
# the ue-style spelling produces the other: "Munchen" from Munchen, "Muenchen" from
# the way the city often writes itself in ASCII. Missing one of the two left
# "Munchen" unresolved.
_add("Germany", "Berlin", "Munich", "Muenchen", "Munchen", "Hamburg", "Frankfurt",
     "Cologne", "Koeln", "Koln", "Stuttgart", "Duesseldorf", "Dusseldorf",
     "Dortmund", "Leipzig", "Dresden", "Nuremberg", "Nurnberg", "Karlsruhe",
     "Darmstadt", "Wurzburg", "Wuerzburg")
_add("France", "Paris", "Lyon", "Marseille", "Toulouse", "Bordeaux", "Lille",
     "Nantes", "Sophia Antipolis", "Grenoble", "Nice")
_add("Spain", "Madrid", "Barcelona", "Valencia", "Seville", "Sevilla", "Malaga",
     "Bilbao", "Zaragoza")
_add("Portugal", "Lisbon", "Lisboa", "Porto", "Braga", "Coimbra")
_add("Italy", "Milan", "Milano", "Rome", "Roma", "Turin", "Torino", "Bologna",
     "Naples", "Napoli", "Florence", "Firenze", "Venice", "Padua", "Padova")
_add("Netherlands", "Amsterdam", "Rotterdam", "Utrecht", "Eindhoven", "The Hague",
     "Den Haag", "Delft", "Groningen")
_add("Belgium", "Brussels", "Bruxelles", "Antwerp", "Antwerpen", "Ghent", "Leuven")
_add("Austria", "Vienna", "Wien", "Graz", "Linz", "Salzburg")
_add("Switzerland", "Zurich", "Zuerich", "Geneva", "Geneve", "Basel", "Lausanne",
     "Bern", "Lugano")
_add("Poland", "Warsaw", "Warszawa", "Krakow", "Cracow", "Wroclaw", "Gdansk",
     "Poznan", "Katowice", "Lodz")
_add("Czechia", "Prague", "Praha", "Brno", "Ostrava")
_add("Sweden", "Stockholm", "Gothenburg", "Goteborg", "Goeteborg", "Malmo",
     "Lund", "Uppsala")
_add("Denmark", "Copenhagen", "Kobenhavn", "Koebenhavn", "Aarhus", "Arhus",
     "Odense")
_add("Norway", "Oslo", "Bergen", "Trondheim", "Stavanger")
_add("Finland", "Helsinki", "Espoo", "Tampere", "Oulu")
_add("Estonia", "Tallinn", "Tartu")
_add("Latvia", "Riga")
_add("Lithuania", "Vilnius", "Kaunas")
_add("Romania", "Bucharest", "Bucuresti", "Cluj", "Cluj-Napoca", "Timisoara",
     "Iasi", "Brasov")
_add("Bulgaria", "Sofia", "Plovdiv", "Varna", "Burgas")
_add("Hungary", "Budapest", "Debrecen", "Szeged")
_add("Greece", "Athens", "Thessaloniki", "Patras")
_add("Croatia", "Zagreb", "Split", "Rijeka")
_add("Slovakia", "Bratislava", "Kosice")
_add("Slovenia", "Ljubljana", "Maribor")
_add("Serbia", "Belgrade", "Beograd", "Novi Sad", "Nis")
_add("Ukraine", "Kyiv", "Kiev", "Lviv", "Kharkiv", "Odesa")
_add("Turkey", "Istanbul", "Ankara", "Izmir")
_add("Luxembourg", "Luxembourg City")
_add("Iceland", "Reykjavik")
_add("Malta", "Valletta")
_add("Cyprus", "Nicosia", "Limassol")

_add("Israel", "Tel Aviv", "Jerusalem", "Haifa", "Herzliya", "Ra'anana")
_add("United Arab Emirates", "Dubai", "Abu Dhabi", "Sharjah")
_add("Saudi Arabia", "Riyadh", "Jeddah", "Dammam")
_add("Qatar", "Doha")
_add("Egypt", "Cairo", "Alexandria", "Giza")
_add("Japan", "Tokyo", "Osaka", "Kyoto", "Yokohama", "Nagoya", "Minato")
_add("China", "Shanghai", "Beijing", "Shenzhen", "Guangzhou", "Hangzhou", "Suzhou")
_add("Hong Kong", "Kowloon")
_add("Taiwan", "Taipei", "Hsinchu")
_add("South Korea", "Seoul", "Busan", "Incheon")
_add("Singapore", "Singapore City")
_add("Malaysia", "Kuala Lumpur", "Penang", "Johor Bahru", "Cyberjaya")
_add("Thailand", "Bangkok", "Chiang Mai", "Phuket")
_add("Vietnam", "Hanoi", "Ho Chi Minh City", "Saigon", "Da Nang")
_add("Indonesia", "Jakarta", "Surabaya", "Bandung")
_add("Philippines", "Manila", "Makati", "Cebu", "Taguig", "Quezon City")
_add("Pakistan", "Karachi", "Lahore", "Islamabad")
_add("Bangladesh", "Dhaka")
_add("Sri Lanka", "Colombo")
_add("Australia", "Sydney", "Melbourne", "Brisbane", "Adelaide", "Canberra")
_add("New Zealand", "Auckland", "Christchurch")
_add("Brazil", "Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Campinas",
     "Porto Alegre", "Brasilia", "Recife", "Curitiba", "Sao Jose dos Campos")
_add("Argentina", "Buenos Aires", "Cordoba", "Rosario")
_add("Chile", "Santiago")
_add("Colombia", "Bogota", "Medellin")
_add("Peru", "Lima")
_add("Uruguay", "Montevideo")
_add("Mexico", "Mexico City", "Guadalajara", "Monterrey", "Queretaro")
_add("Costa Rica", "San Jose Costa Rica", "Heredia")
_add("South Africa", "Cape Town", "Johannesburg", "Durban", "Pretoria")
_add("Nigeria", "Lagos", "Abuja")
_add("Kenya", "Nairobi")
_add("Morocco", "Casablanca", "Rabat")

# US states and provinces. More reliable than a city name, and they arrive constantly
# in schema.org addresses - "San Francisco, California" with no country at all.
#
# Georgia is left out: it is a US state and a country, and the country is the one a
# European job search is more likely to mean. Two-letter codes that collide with a
# country code the place extractor already knows are left out too - CA is Canada
# before California, IL is Israel before Illinois, IN is India before Indiana, DE is
# Germany before Delaware, and getting that wrong would exclude the wrong continent.
_add("United States",
     "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
     "Connecticut", "Delaware", "Florida", "Hawaii", "Idaho", "Illinois", "Indiana",
     "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
     "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
     "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico",
     "New York",
     "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
     "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee",
     "Texas", "Utah", "Vermont", "Virginia", "West Virginia", "Wisconsin",
     "Wyoming", "District of Columbia",
     "NY", "WA", "TX", "FL", "MA", "NC", "NJ", "PA", "OH", "MI", "MN", "WI", "VA",
     "CO", "AZ", "OR", "UT", "NV", "TN", "MO", "MD", "OK", "KY", "SC", "IA", "KS",
     "AR", "MS", "NE", "NM", "ND", "SD", "WV", "RI", "NH", "VT", "ME", "AK", "HI")

_add("Canada", "Ontario", "British Columbia", "Alberta", "Manitoba", "Saskatchewan",
     "Nova Scotia", "New Brunswick", "Newfoundland and Labrador")


def infer_country(place: str) -> str | None:
    """The country a city or subdivision belongs to, or None when it is not certain.

    Only ever consulted for a location that names no country of its own, and the
    label it produces says the country was inferred and from what - because this is
    the one piece of guesswork that can exclude a posting, and an exclusion the
    reader cannot see the reasoning for is one they cannot argue with.
    """
    # Folded, because the table is written without accents and the platforms are
    # not: "Sao Paulo" here against "São Paulo" on the page, "Dusseldorf" against
    # "Düsseldorf". Without this the six remaining unjudged postings were all
    # accents.
    return CITY_COUNTRY.get(fold(place.strip()).lower())
