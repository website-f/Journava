"""Deterministic goal parsing — a floor under the Chief Agent.

The Chief normally parses a free-form goal with an LLM. When no model is
configured (or every provider is down), that parse fails and every specialist
plans for `destination=None` — so *"cheap flights from KLIA to BKI on 6 November
night"* produced a placeholder for "KUL → unknown".

That is a bad failure: the sentence is entirely parseable without a model. This
module extracts what can be extracted from the text itself — route, dates, party
size, budget, time-of-day, cabin hints — and the Chief uses it two ways:

- as the **fallback** when the LLM is unavailable, and
- as a **backstop** afterwards, filling any field the model left null.

It is deliberately conservative: a pattern either matches clearly or is skipped.
A wrong confident guess is worse than a null the specialist can search around.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

#: Place name → IATA. Shared with the flight agent's resolver.
CITY_CODES: dict[str, str] = {
    # Malaysia
    "klia": "KUL",
    "klia2": "KUL",
    "kuala lumpur": "KUL",
    "kl": "KUL",
    "subang": "SZB",
    "kota kinabalu": "BKI",
    "bki": "BKI",
    "kk": "BKI",
    "penang": "PEN",
    "langkawi": "LGK",
    "kuching": "KCH",
    "johor bahru": "JHB",
    "ipoh": "IPH",
    "kota bharu": "KBR",
    "kuala terengganu": "TGG",
    "alor setar": "AOR",
    "miri": "MYY",
    "sibu": "SBW",
    "sandakan": "SDK",
    "tawau": "TWU",
    "labuan": "LBU",
    "melaka": "MKZ",
    # South-east Asia
    "singapore": "SIN",
    "changi": "SIN",
    "bangkok": "BKK",
    "phuket": "HKT",
    "chiang mai": "CNX",
    "krabi": "KBV",
    "jakarta": "CGK",
    "bali": "DPS",
    "denpasar": "DPS",
    "surabaya": "SUB",
    "medan": "KNO",
    "yogyakarta": "JOG",
    "manila": "MNL",
    "cebu": "CEB",
    "hanoi": "HAN",
    "ho chi minh": "SGN",
    "saigon": "SGN",
    "da nang": "DAD",
    "phnom penh": "PNH",
    "siem reap": "REP",
    "vientiane": "VTE",
    "yangon": "RGN",
    "brunei": "BWN",
    # East Asia
    "tokyo": "NRT",
    "haneda": "HND",
    "osaka": "KIX",
    "kyoto": "KIX",
    "sapporo": "CTS",
    "fukuoka": "FUK",
    "okinawa": "OKA",
    "seoul": "ICN",
    "busan": "PUS",
    "jeju": "CJU",
    "beijing": "PEK",
    "shanghai": "PVG",
    "guangzhou": "CAN",
    "shenzhen": "SZX",
    "chengdu": "CTU",
    "hong kong": "HKG",
    "macau": "MFM",
    "taipei": "TPE",
    "kaohsiung": "KHH",
    # South Asia / Middle East
    "delhi": "DEL",
    "new delhi": "DEL",
    "mumbai": "BOM",
    "bangalore": "BLR",
    "chennai": "MAA",
    "kolkata": "CCU",
    "kochi": "COK",
    "colombo": "CMB",
    "male": "MLE",
    "maldives": "MLE",
    "kathmandu": "KTM",
    "dhaka": "DAC",
    "karachi": "KHI",
    "lahore": "LHE",
    "islamabad": "ISB",
    "dubai": "DXB",
    "abu dhabi": "AUH",
    "doha": "DOH",
    "jeddah": "JED",
    "riyadh": "RUH",
    "medina": "MED",
    "muscat": "MCT",
    "kuwait": "KWI",
    "bahrain": "BAH",
    "amman": "AMM",
    "istanbul": "IST",
    "cairo": "CAI",
    # Europe
    "london": "LHR",
    "heathrow": "LHR",
    "gatwick": "LGW",
    "manchester": "MAN",
    "paris": "CDG",
    "amsterdam": "AMS",
    "frankfurt": "FRA",
    "munich": "MUC",
    "berlin": "BER",
    "zurich": "ZRH",
    "geneva": "GVA",
    "vienna": "VIE",
    "rome": "FCO",
    "milan": "MXP",
    "venice": "VCE",
    "florence": "FLR",
    "naples": "NAP",
    "barcelona": "BCN",
    "madrid": "MAD",
    "lisbon": "LIS",
    "porto": "OPO",
    "athens": "ATH",
    "santorini": "JTR",
    "dublin": "DUB",
    "copenhagen": "CPH",
    "stockholm": "ARN",
    "oslo": "OSL",
    "helsinki": "HEL",
    "prague": "PRG",
    "budapest": "BUD",
    "warsaw": "WAW",
    "krakow": "KRK",
    "reykjavik": "KEF",
    "moscow": "SVO",
    "brussels": "BRU",
    # Americas / Oceania / Africa
    "new york": "JFK",
    "los angeles": "LAX",
    "san francisco": "SFO",
    "chicago": "ORD",
    "miami": "MIA",
    "seattle": "SEA",
    "boston": "BOS",
    "las vegas": "LAS",
    "toronto": "YYZ",
    "vancouver": "YVR",
    "mexico city": "MEX",
    "sao paulo": "GRU",
    "rio de janeiro": "GIG",
    "buenos aires": "EZE",
    "lima": "LIM",
    "santiago": "SCL",
    "sydney": "SYD",
    "melbourne": "MEL",
    "brisbane": "BNE",
    "perth": "PER",
    "auckland": "AKL",
    "christchurch": "CHC",
    "nadi": "NAN",
    "johannesburg": "JNB",
    "cape town": "CPT",
    "nairobi": "NBO",
    "casablanca": "CMN",
    "marrakech": "RAK",
    "addis ababa": "ADD",
}

MONTHS: dict[str, int] = {
    name.lower(): index for index, name in enumerate(calendar.month_name) if name
}
MONTHS.update({name.lower(): index for index, name in enumerate(calendar.month_abbr) if name})
MONTHS.update({"sept": 9})

#: "8,000" / "8000" / "8k" / "8.5k"
_AMOUNT = r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<k>k\b)?"

_CURRENCY_WORDS: dict[str, str] = {
    "rm": "MYR",
    "myr": "MYR",
    "ringgit": "MYR",
    "sgd": "SGD",
    "s$": "SGD",
    "usd": "USD",
    "$": "USD",
    "dollars": "USD",
    "eur": "EUR",
    "€": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "£": "GBP",
    "pounds": "GBP",
    "aed": "AED",
    "dirham": "AED",
    "jpy": "JPY",
    "¥": "JPY",
    "yen": "JPY",
    "thb": "THB",
    "baht": "THB",
    "idr": "IDR",
    "rupiah": "IDR",
}

#: Time-of-day words → a rough departure window, used for ranking only.
TIME_WINDOWS: dict[str, tuple[int, int]] = {
    "red eye": (22, 6),
    "red-eye": (22, 6),
    "redeye": (22, 6),
    "overnight": (22, 6),
    "night": (20, 6),
    "late night": (22, 6),
    "evening": (17, 22),
    "afternoon": (12, 17),
    "morning": (5, 12),
    "early morning": (5, 9),
    "midday": (11, 14),
}


def parse_goal(goal: str, *, today: date | None = None) -> dict[str, Any]:
    """Extract every field we can be confident about from `goal`.

    Only keys with a confident value are present, so the caller can merge this
    over (or under) an LLM parse without a null overwriting a real answer.
    """
    text = (goal or "").strip()
    if not text:
        return {}
    lowered = text.lower()
    reference = today or datetime.now(UTC).date()

    parsed: dict[str, Any] = {}

    origin, destination = _route(lowered)
    if origin:
        parsed["origin"] = origin
    if destination:
        parsed["destination"] = destination

    start, end = _dates(lowered, reference)
    if start:
        parsed["start_date"] = start.isoformat()
    if end:
        parsed["end_date"] = end.isoformat()

    travellers = _travellers(lowered)
    if travellers:
        parsed["travellers"] = travellers

    amount, currency = _budget(lowered)
    if amount is not None:
        parsed["budget_amount"] = amount
    if currency:
        parsed["budget_currency"] = currency

    window = _time_window(lowered)
    if window:
        parsed["preferred_departure_window"] = window

    pace = _pace(lowered)
    if pace:
        parsed["pace"] = pace

    stops = _max_stops(lowered)
    if stops is not None:
        parsed["max_connections"] = stops

    interests = _interests(lowered)
    if interests:
        parsed["interests_detected"] = interests

    return parsed


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

#: Longest names first, so "kota kinabalu" wins over "kota".
_CITY_ALTERNATION = "|".join(re.escape(name) for name in sorted(CITY_CODES, key=len, reverse=True))

#: A place is either a known city name or a bare three-letter code. Keeping them
#: in one alternation lets a mixed phrase like "KUL to Tokyo" match, which the
#: city-only and code-only patterns both miss.
_PLACE = rf"(?:{_CITY_ALTERNATION}|[a-z]{{3}})"

_ROUTE_PATTERNS = (
    # "from KLIA to BKI" / "from Kuala Lumpur to Kota Kinabalu"
    re.compile(rf"\bfrom\s+(?P<origin>{_PLACE})\b.*?\bto\s+(?P<dest>{_PLACE})\b"),
    # "KLIA to BKI", "KUL-BKI", "KUL → BKI", "KUL to Tokyo"
    re.compile(rf"\b(?P<origin>{_PLACE})\s*(?:to|-|–|→|>)\s*(?P<dest>{_PLACE})\b"),
)

_DEST_ONLY = (
    re.compile(rf"\b(?:to|in|at|around|visit(?:ing)?|explore)\s+(?P<dest>{_CITY_ALTERNATION})\b"),
    re.compile(rf"\b(?P<dest>{_CITY_ALTERNATION})\s+(?:trip|holiday|vacation|itinerary|getaway)\b"),
)

#: Words that look like IATA codes but never are, so the bare-pair pattern
#: doesn't turn "get me to bki" into an origin of "get".
_NOT_CODES = frozenset(
    {
        "the",
        "and",
        "for",
        "get",
        "not",
        "any",
        "all",
        "can",
        "you",
        "our",
        "day",
        "one",
        "two",
        "six",
        "ten",
        "cheap",
        "fly",
        "buy",
        "add",
        "how",
        "who",
        "why",
        "was",
        "are",
        "has",
        "had",
        "but",
        "off",
        "out",
        "per",
        "via",
        "min",
        "max",
        "new",
        "old",
        "top",
        "see",
        "eat",
        "let",
        "may",
        "jun",
        "jul",
        "night",
        "trip",
        "food",
        "book",
        "find",
        "want",
        "need",
        "from",
        "with",
    }
)


def _code_for(token: str) -> str | None:
    token = token.strip()
    if token in CITY_CODES:
        return CITY_CODES[token]
    if len(token) == 3 and token.isalpha() and token not in _NOT_CODES:
        return token.upper()
    return None


def _route(text: str) -> tuple[str | None, str | None]:
    for pattern in _ROUTE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        origin = _code_for(match.group("origin"))
        destination = _code_for(match.group("dest"))
        if origin and destination and origin != destination:
            return origin, destination

    for pattern in _DEST_ONLY:
        match = pattern.search(text)
        if match:
            destination = _code_for(match.group("dest"))
            if destination:
                return None, destination
    return None, None


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

_ORDINAL = r"(?:st|nd|rd|th)?"
_DAY_MONTH = re.compile(rf"\b(?P<day>\d{{1,2}}){_ORDINAL}\s+(?:of\s+)?(?P<month>[a-z]{{3,9}})\b")
_MONTH_DAY = re.compile(rf"\b(?P<month>[a-z]{{3,9}})\s+(?P<day>\d{{1,2}}){_ORDINAL}\b")
_ISO_DATE = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
_SLASH_DATE = re.compile(r"\b(?P<day>\d{1,2})/(?P<month>\d{1,2})(?:/(?P<year>\d{2,4}))?\b")
_DURATION = re.compile(
    r"\b(?P<count>\d{1,2})\s*[- ]?\s*(?P<unit>day|days|night|nights|week|weeks)\b"
)
_RELATIVE = {
    "today": 0,
    "tomorrow": 1,
    "next week": 7,
    "next month": 30,
    "this weekend": None,
    "next weekend": None,
}


def _resolve_year(month: int, day: int, reference: date) -> date | None:
    """Pick the next occurrence of month/day, so a bare date is never in the past."""
    for year in (reference.year, reference.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= reference:
            return candidate
    return None


def _explicit_date(text: str, reference: date) -> date | None:
    match = _ISO_DATE.search(text)
    if match:
        try:
            return date(
                int(match.group("year")), int(match.group("month")), int(match.group("day"))
            )
        except ValueError:
            return None

    match = _SLASH_DATE.search(text)
    if match:
        year_raw = match.group("year")
        year = reference.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            candidate = date(year, int(match.group("month")), int(match.group("day")))
        except ValueError:
            return None
        return candidate if year_raw else _resolve_year(candidate.month, candidate.day, reference)

    # `finditer`, not `search`: the first candidate is often a false positive
    # ("3 nights" looks like day-3-of-month-"nights"), and stopping there loses
    # the real date later in the sentence.
    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for match in pattern.finditer(text):
            month = MONTHS.get(match.group("month"))
            if not month:
                continue
            day = int(match.group("day"))
            if not 1 <= day <= 31:
                continue
            resolved = _resolve_year(month, day, reference)
            if resolved:
                return resolved
    return None


def _dates(text: str, reference: date) -> tuple[date | None, date | None]:
    start = _explicit_date(text, reference)

    if start is None:
        for phrase, offset in _RELATIVE.items():
            if phrase not in text:
                continue
            if offset is None:
                # Next Saturday, for "this/next weekend".
                ahead = (5 - reference.weekday()) % 7
                if "next" in phrase:
                    ahead += 7
                start = reference + timedelta(days=ahead or 7)
            else:
                start = reference + timedelta(days=offset)
            break

    end: date | None = None
    duration = _DURATION.search(text)
    if duration and start:
        count = int(duration.group("count"))
        unit = duration.group("unit")
        days = count * 7 if unit.startswith("week") else count
        # "7-day trip" spans 7 days → 6 nights; "7 nights" → 7.
        end = start + timedelta(days=days if unit.startswith("night") else max(0, days - 1))

    return start, end


# --------------------------------------------------------------------------- #
# Party size, budget, preferences
# --------------------------------------------------------------------------- #

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
#: Words that name a party size on their own, without a following noun.
_STANDALONE_PARTY = {"solo": 1, "myself": 1, "couple": 2, "pair": 2}

_TRAVELLERS = re.compile(
    r"\b(?P<for>for\s+)?"
    r"(?P<count>\d{1,2}|one|two|three|four|five|six|seven|eight|nine)\s*"
    r"(?P<noun>people|persons?|pax|adults?|travellers?|travelers?|of\s+us|guests?)?\b"
)


def _travellers(text: str) -> int | None:
    """Party size, only when the phrasing actually says so.

    Ambiguity is everywhere here: "6 november" is a date, "7-day" is a duration,
    and "a 7-day trip" is not one traveller. So a number counts only when it is
    followed by a person-noun or preceded by "for" — and the best-evidence match
    wins rather than the first one in the string.
    """
    for word, count in _STANDALONE_PARTY.items():
        if re.search(rf"\b{word}\b", text):
            return count

    best: tuple[int, int] | None = None  # (confidence, count)
    for match in _TRAVELLERS.finditer(text):
        raw = match.group("count")
        noun = match.group("noun")
        has_for = bool(match.group("for"))
        count = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw)
        if not count or not 1 <= count <= 9:
            continue

        # A trailing person-noun is the strongest signal; "for N" is next. A bare
        # number is never a party size.
        confidence = 2 if noun else (1 if has_for else 0)
        if confidence == 0:
            continue
        # A "for N day(s)" phrase is a duration, not a headcount.
        tail = text[match.end() : match.end() + 12]
        if not noun and re.match(r"\s*(?:day|night|week|hour)", tail):
            continue
        if best is None or confidence > best[0]:
            best = (confidence, count)
    return best[1] if best else None


#: The currency can lead ("RM 250") or trail ("1200 EUR", "400 ringgit"), so both
#: positions are captured.
_CURRENCY_TOKEN = r"rm|myr|sgd|usd|eur|gbp|aed|jpy|thb|idr|\$|€|£|¥"
_CURRENCY_TRAILING = rf"{_CURRENCY_TOKEN}|ringgit|dollars|euros|pounds|yen|baht|rupiah|dirham"
_BUDGET = re.compile(
    rf"(?:budget\s*(?:of|is|:)?\s*)?(?P<cur>{_CURRENCY_TOKEN})?\s*{_AMOUNT}"
    rf"(?:\s*(?P<cur2>{_CURRENCY_TRAILING})\b)?"
)


def _budget(text: str) -> tuple[float | None, str | None]:
    # Anchor on an explicit budget word so a flight time or a year isn't a budget.
    anchor = re.search(
        r"\b(?:budget|under|below|max(?:imum)?|around|about|up to|less than|within)\b", text
    )
    region = text[anchor.start() :] if anchor else text
    if not anchor and not re.search(r"\b(?:rm|myr|sgd|usd|\$|€|£)\b", text):
        return None, None

    for match in _BUDGET.finditer(region):
        raw = match.group("amount").replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            continue
        if match.group("k"):
            amount *= 1000
        # Below 20 is nearly always a count or a date, not money.
        if amount < 20:
            continue
        currency_token = (match.group("cur") or match.group("cur2") or "").lower()
        currency = _CURRENCY_WORDS.get(currency_token)
        return amount, currency
    return None, None


def _time_window(text: str) -> dict[str, Any] | None:
    for phrase, (start_hour, end_hour) in sorted(
        TIME_WINDOWS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return {"label": phrase, "from_hour": start_hour, "to_hour": end_hour}
    return None


def _pace(text: str) -> str | None:
    if re.search(r"\b(relaxed|slow|chill|easy|leisurely|lazy)\b", text):
        return "relaxed"
    if re.search(r"\b(packed|intense|see everything|jam[- ]packed|maximise|maximize)\b", text):
        return "packed"
    if re.search(r"\bbalanced\b", text):
        return "balanced"
    return None


def _max_stops(text: str) -> int | None:
    if re.search(r"\b(direct|non[- ]?stop|nonstop)\b", text):
        return 0
    match = re.search(r"\bmax(?:imum)?\s*(?P<n>\d)\s*(?:stop|connection|layover)", text)
    if match:
        return int(match.group("n"))
    match = re.search(r"\b(?P<n>\d)\s*(?:stop|connection|layover)s?\s*max", text)
    if match:
        return int(match.group("n"))
    return None


_INTEREST_WORDS = {
    "food": ("food", "eat", "restaurant", "cuisine", "street food", "dining", "makan"),
    "culture": ("culture", "museum", "temple", "heritage", "historic", "history"),
    "nature": ("nature", "hiking", "island", "beach", "mountain", "park", "diving", "snorkel"),
    "nightlife": ("nightlife", "bar", "club", "party"),
    "shopping": ("shopping", "market", "mall", "souvenir"),
    "adventure": ("adventure", "trek", "climb", "surf", "rafting"),
    "photography": ("photography", "photo", "instagram", "scenic"),
    "relaxation": ("spa", "resort", "relax", "wellness"),
}


def _interests(text: str) -> list[str]:
    found = [
        interest
        for interest, words in _INTEREST_WORDS.items()
        if any(word in text for word in words)
    ]
    return found


def to_iata(value: str | None) -> str | None:
    """Normalise a place into an IATA code where we confidently can.

    The Chief's LLM parse returns whatever the traveller typed — "KLIA",
    "Kuala Lumpur", "kul". Downstream every agent and the booking API want a
    three-letter code, so normalising once here keeps one canonical value
    instead of each consumer guessing. Anything unrecognised passes through
    unchanged rather than being mangled.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in CITY_CODES:
        return CITY_CODES[lowered]
    if len(text) == 3 and text.isalpha():
        return text.upper()
    match = re.search(r"\(([A-Za-z]{3})\)", text)
    if match:
        return match.group(1).upper()
    for name, code in CITY_CODES.items():
        if name in lowered:
            return code
    return text
