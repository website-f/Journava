"""Reading fares out of a browsed page.

The previous approach was a bare price regex over a Google results snippet: it
found numbers, could not say which airline or departure they belonged to, and
happily mistook "Save RM 5 with the app" for a fare.

An accessibility snapshot of a fare list is more structured than raw text — each
result is a cluster of lines holding a carrier, times, a duration, a stop count
and a price. So this parses *result blocks* rather than isolated numbers, and a
block without a plausible price is discarded rather than guessed at.

Everything here is best-effort by nature: these are public pages that change
layout without notice. The guard against that is conservatism — a fare is only
emitted when the evidence is there, and every fare keeps the page it came from
so a person can check it.
"""

from __future__ import annotations

import re
from typing import Any

#: "RM 1,234" · "MYR 1234.50" · "$421" · "1 234 €"
_PRICE = re.compile(
    r"(?P<pre>RM|MYR|USD|SGD|EUR|GBP|AUD|THB|IDR|JPY|\$|€|£|¥)\s?"
    r"(?P<amt>\d[\d,\s]{1,9}(?:\.\d{1,2})?)"
    r"|(?P<amt2>\d[\d,\s]{1,9}(?:\.\d{1,2})?)\s?"
    r"(?P<post>RM|MYR|USD|SGD|EUR|GBP|AUD|THB|IDR|JPY|€|£|¥)",
    re.IGNORECASE,
)

_CURRENCY_ALIASES = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "RM": "MYR",
}

#: "07:35" / "7:35 AM" / "19:05"
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s?(am|pm)?\b", re.IGNORECASE)

#: "2h 40m" / "2 hr 40 min" / "2h40"
_DURATION = re.compile(
    r"\b(?P<h>\d{1,2})\s?(?:h|hr|hour)s?\s*(?P<m>\d{1,2})?\s?(?:m|min)?", re.IGNORECASE
)

_STOPS = re.compile(r"\b(nonstop|non-stop|direct|(?P<n>\d)\s?stop)", re.IGNORECASE)

#: Carriers worth recognising by name; the code form is matched separately.
_AIRLINES = {
    "airasia": "AirAsia",
    "air asia": "AirAsia",
    "malaysia airlines": "Malaysia Airlines",
    "malindo": "Batik Air",
    "batik air": "Batik Air",
    "firefly": "Firefly",
    "scoot": "Scoot",
    "jetstar": "Jetstar",
    "singapore airlines": "Singapore Airlines",
    "cathay": "Cathay Pacific",
    "emirates": "Emirates",
    "qatar": "Qatar Airways",
    "etihad": "Etihad",
    "turkish": "Turkish Airlines",
    "vietjet": "VietJet",
    "vietnam airlines": "Vietnam Airlines",
    "thai airways": "Thai Airways",
    "lion air": "Lion Air",
    "citilink": "Citilink",
    "garuda": "Garuda Indonesia",
    "cebu pacific": "Cebu Pacific",
    "philippine airlines": "Philippine Airlines",
    "ana": "ANA",
    "japan airlines": "Japan Airlines",
    "korean air": "Korean Air",
    "china airlines": "China Airlines",
    "eva air": "EVA Air",
    "british airways": "British Airways",
    "lufthansa": "Lufthansa",
    "klm": "KLM",
    "air france": "Air France",
    "ryanair": "Ryanair",
    "easyjet": "easyJet",
    "wizz": "Wizz Air",
    "united": "United",
    "delta": "Delta",
    "american airlines": "American Airlines",
    "qantas": "Qantas",
    "batik": "Batik Air",
}

#: Text that means the number nearby is not a fare.
_NOISE_LINES = (
    "save",
    "discount",
    "off",
    "cashback",
    "promo code",
    "voucher",
    "points",
    "per night",
    "hotel",
    "insurance",
    "baggage fee",
    "seat fee",
    "cookie",
    "sign in",
    "log in",
    "subscribe",
    "newsletter",
    "advert",
)

#: A one-way regional fare outside this band is almost certainly page furniture.
_MIN_FARE, _MAX_FARE = 30.0, 40_000.0


def _to_amount(raw: str) -> float | None:
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _find_price(text: str) -> tuple[float, str | None] | None:
    """First plausible price in `text`, with its currency."""
    for match in _PRICE.finditer(text):
        raw = match.group("amt") or match.group("amt2")
        token = (match.group("pre") or match.group("post") or "").upper()
        amount = _to_amount(raw or "")
        if amount is None or not _MIN_FARE <= amount <= _MAX_FARE:
            continue
        currency = _CURRENCY_ALIASES.get(token, token or None)
        return amount, currency
    return None


def _find_airline(text: str) -> str | None:
    """The carrier named earliest in the block.

    Position matters, not dictionary order: a result block usually starts with
    its carrier and may mention others further down (a "compare with…" row, or
    the next result bleeding into the window). Returning the first match by dict
    order attributed a Batik Air fare to Malaysia Airlines purely because "m"
    sorted earlier.
    """
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for needle, name in _AIRLINES.items():
        position = lowered.find(needle)
        if position == -1:
            continue
        # Prefer the earliest mention; on a tie prefer the longer, more specific
        # name ("batik air malaysia" over "malaysia airlines").
        if best is None or position < best[0]:
            best = (position, name)
    if best:
        return best[1]

    # Bare two-letter carrier code followed by a flight number, e.g. "AK 5104".
    match = re.search(r"\b([A-Z]{2})\s?(\d{2,4})\b", text)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    return None


def _find_times(text: str) -> tuple[str | None, str | None]:
    times = _TIME.findall(text)
    formatted = []
    for hour, minute, meridiem in times[:4]:
        value = f"{int(hour):02d}:{minute}"
        if meridiem and meridiem.lower() == "pm" and int(hour) < 12:
            value = f"{int(hour) + 12:02d}:{minute}"
        if meridiem and meridiem.lower() == "am" and int(hour) == 12:
            value = f"00:{minute}"
        formatted.append(value)
    if not formatted:
        return None, None
    return formatted[0], (formatted[1] if len(formatted) > 1 else None)


def _find_duration(text: str) -> float | None:
    match = _DURATION.search(text)
    if not match:
        return None
    hours = int(match.group("h"))
    minutes = int(match.group("m") or 0)
    total = hours + minutes / 60
    return round(total, 1) if 0.3 <= total <= 48 else None


def _find_stops(text: str) -> int | None:
    match = _STOPS.search(text)
    if not match:
        return None
    if match.group("n"):
        return int(match.group("n"))
    return 0


def _strip_noise(text: str) -> str:
    """Drop promotional lines, keeping the rest of the block.

    Rejecting a whole block because it contains one "Save RM 5 with the app"
    banner threw away real fares — a promo line sits *next to* results, not
    instead of them. So the noise is removed line by line and the fare survives.
    """
    kept = [
        line for line in text.splitlines() if not any(word in line.lower() for word in _NOISE_LINES)
    ]
    return "\n".join(kept)


def _blocks(snapshot: str, *, window: int = 6) -> list[str]:
    """Split a snapshot into candidate result blocks.

    A fare listing renders as a run of adjacent lines, so a sliding window over
    non-empty lines keeps a carrier, its times and its price together — which is
    what makes the difference between "a number" and "a fare".
    """
    lines = [line.strip() for line in (snapshot or "").splitlines() if line.strip()]
    if not lines:
        return []
    return ["\n".join(lines[index : index + window]) for index in range(0, max(1, len(lines) - 1))]


def extract_fares(
    snapshot: str,
    *,
    source_url: str | None = None,
    site_name: str | None = None,
    max_results: int = 6,
    min_signals: int = 2,
) -> list[dict[str, Any]]:
    """Extract fare candidates from one browsed page.

    Returns dicts shaped for `Option`, each carrying the page it came from. A
    block must yield a plausible price *and* at least one corroborating detail
    (airline, time, duration or stop count) — a lone number is not a fare.
    """
    found: list[dict[str, Any]] = []
    seen_prices: set[tuple[float, str | None]] = set()

    for raw_block in _blocks(snapshot):
        block = _strip_noise(raw_block)
        if not block.strip():
            continue
        price = _find_price(block)
        if price is None:
            continue
        amount, currency = price
        if (amount, currency) in seen_prices:
            continue

        airline = _find_airline(block)
        departure, arrival = _find_times(block)
        duration = _find_duration(block)
        stops = _find_stops(block)

        # Corroboration: a price with no flight-ish detail beside it is noise.
        # Corroboration. A search results page is full of numbers that look
        # like money — an unrelated "USD 56" beside a carrier name is not a
        # fare for this route. Requiring two independent flight signals (a
        # carrier, a clock time, a duration, a stop count) is what separates a
        # real result row from a coincidence.
        signals = sum(1 for value in (airline, departure, duration, stops) if value is not None)
        if signals < min_signals:
            continue

        seen_prices.add((amount, currency))
        found.append(
            {
                "price_amount": amount,
                "price_currency": currency,
                "airline": airline,
                "departure_time": departure,
                "arrival_time": arrival,
                "duration_hours": duration,
                "stops": stops,
                "site": site_name,
                "source_url": source_url,
                "confidence": "high" if signals >= 3 else ("medium" if signals == 2 else "low"),
            }
        )
        if len(found) >= max_results:
            break

    found.sort(key=lambda fare: fare["price_amount"])
    return found


def summarise_sites(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-site tally: what each page yielded, and which was cheapest.

    This is what turns "we looked at six sites" into a claim the traveller can
    act on — including naming the site that actually had the lowest fare.
    """
    per_site: dict[str, dict[str, Any]] = {}
    for fare in results:
        site = fare.get("site") or "unknown"
        entry = per_site.setdefault(
            site, {"count": 0, "cheapest": None, "currency": None, "url": fare.get("source_url")}
        )
        entry["count"] += 1
        amount = fare["price_amount"]
        if entry["cheapest"] is None or amount < entry["cheapest"]:
            entry["cheapest"] = amount
            entry["currency"] = fare.get("price_currency")
            entry["url"] = fare.get("source_url")

    cheapest_site = None
    cheapest_value = None
    for site, entry in per_site.items():
        if entry["cheapest"] is None:
            continue
        if cheapest_value is None or entry["cheapest"] < cheapest_value:
            cheapest_value = entry["cheapest"]
            cheapest_site = site

    return {
        "per_site": per_site,
        "cheapest_site": cheapest_site,
        "cheapest_amount": cheapest_value,
        "sites_with_fares": sum(1 for e in per_site.values() if e["count"]),
    }
