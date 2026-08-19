"""Where to look for fares — the breadth behind "broad research".

The complaint this answers: a search for KUL→BKI came back with the AirAsia
website while Cheapflights had a lower fare. That happened because the research
step only ever read one page, so it saw whichever brand ranks first rather than
the market.

Real fare research means opening the engines a person would open. This module is
the list, with per-site URL builders, because each one encodes the route, date
**and currency** differently:

    Trip.com     ?dcity=kul&acity=bki&ddate=2026-11-06&curr=MYR
    Momondo      /flight-search/KUL-BKI/2026-11-06?currency=MYR
    Skiplagged   /flights/KUL/BKI/2026-11-06
    Traveloka    ?ap=KUL.BKI&dt=20261106.NA        (en-my locale implies MYR)

Ordering is deliberate: **metasearch first**. An aggregator compares many
airlines, so it is where a cheaper fare actually surfaces; an airline's own site
can only ever quote itself.

Three access categories, and the difference matters:

- **crawlable** — robots.txt permits it and it serves real content.
- **link-only** — robots.txt disallows the results path (Google Flights, Kayak,
  Expedia). Offered as links, never fetched. Linking is not crawling.
- **challenge-prone** — permitted by robots but gated behind a bot challenge
  (Skyscanner's "Are you a person or a robot?", Wego's "security verification",
  AirAsia's, CheapOair's). §15 says never bypass a captcha, so these are
  attempted politely once and reported honestly when they refuse.

Nothing here logs in, pays, or defeats a captcha. Camoufox's fingerprint
resistance keeps an ordinary browser from being *misclassified* as a bot; it is
not a licence to walk through a door a site has closed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

SiteKind = Literal["metasearch", "ota", "airline"]

#: `(origin, destination, depart, return_date, adults, currency) -> url`
UrlBuilder = Callable[[str, str, date, "date | None", int, str], str]


@dataclass(frozen=True)
class FlightSite:
    """One place to look, and how to ask it about a route."""

    slug: str
    name: str
    kind: SiteKind
    build_url: UrlBuilder
    #: Lower runs earlier. Metasearch before OTA before a single airline.
    priority: int = 50
    #: Regions where this site is especially strong, for route-aware selection.
    regions: tuple[str, ...] = ()
    #: Heavy JavaScript pages need more scroll passes to render their results.
    scrolls: int = 4
    note: str = ""
    #: False when the site's robots.txt disallows its results path.
    #:
    #: Verified 2026-08-18: Google Flights, Kayak and Expedia all `Disallow` the
    #: flight-search paths. §8 commits us to honouring that, so these are never
    #: crawled — but they are still offered as links, because linking is not
    #: crawling and the traveller may well want to open them.
    crawlable: bool = True
    #: True when the site is known to answer with a bot challenge. Still tried
    #: (they vary by region and time), but a refusal is expected and reported
    #: rather than treated as a bug — and never worked around (§15).
    challenge_prone: bool = False
    #: True when the site honours a currency parameter we can set.
    supports_currency: bool = True

    def url_for(
        self,
        origin: str,
        destination: str,
        depart: date,
        return_date: date | None = None,
        adults: int = 1,
        currency: str = "MYR",
    ) -> str:
        return self.build_url(origin, destination, depart, return_date, adults, currency)


def _ymd(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _yymmdd(value: date) -> str:
    return value.strftime("%y%m%d")


def _compact(value: date) -> str:
    return value.strftime("%Y%m%d")


def _us(value: date) -> str:
    return value.strftime("%m/%d/%Y")


SITES: tuple[FlightSite, ...] = (
    # ----------------------------------------------------------------- #
    # Metasearch — compares many airlines and agencies at once.
    # ----------------------------------------------------------------- #
    FlightSite(
        slug="google_flights",
        name="Google Flights",
        kind="metasearch",
        crawlable=False,
        priority=10,
        note="Broadest coverage, but robots.txt disallows /travel/flights — link only.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.google.com/travel/flights?q="
            + f"Flights%20from%20{o}%20to%20{d}%20on%20{_ymd(dep)}"
            + (f"%20returning%20{_ymd(ret)}" if ret else "%20one%20way")
            + f"&curr={cur}"
        ),
    ),
    FlightSite(
        slug="trip_com",
        name="Trip.com",
        kind="ota",
        priority=12,
        scrolls=5,
        regions=("sea", "apac"),
        note="Reliable reader and honours `curr` — the most dependable source so far.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.trip.com/flights/showfarefirst?"
            f"dcity={o.lower()}&acity={d.lower()}&ddate={_ymd(dep)}"
            + (f"&rdate={_ymd(ret)}&triptype=rt" if ret else "&triptype=ow")
            + f"&class=y&quantity={adults}&curr={cur}&locale=en-MY"
        ),
    ),
    FlightSite(
        slug="momondo",
        name="Momondo",
        kind="metasearch",
        priority=18,
        scrolls=5,
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.momondo.com/flight-search/{o}-{d}/{_ymd(dep)}"
            + (f"/{_ymd(ret)}" if ret else "")
            + f"?sort=price_a&currency={cur}"
        ),
    ),
    FlightSite(
        slug="skiplagged",
        name="Skiplagged",
        kind="metasearch",
        priority=20,
        scrolls=4,
        supports_currency=False,
        note="Renders server-side, so it reads reliably. Quotes USD only.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://skiplagged.com/flights/{o}/{d}/{_ymd(dep)}" + (f"/{_ymd(ret)}" if ret else "")
        ),
    ),
    FlightSite(
        slug="cheapflights",
        name="Cheapflights",
        kind="metasearch",
        priority=25,
        scrolls=5,
        note="The site the traveller named — often undercuts the airline direct.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.cheapflights.com/flights/{o}-{d}/{_ymd(dep)}"
            + (f"/{_ymd(ret)}" if ret else "")
            + f"?sort=price_a&currency={cur}"
        ),
    ),
    FlightSite(
        slug="mytrip",
        name="Mytrip",
        kind="ota",
        priority=28,
        scrolls=5,
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.mytrip.com/rf/start?type="
            + ("return" if ret else "oneway")
            + f"&dep0={o}&arr0={d}&outbound0={_ymd(dep)}"
            + (f"&dep1={d}&arr1={o}&outbound1={_ymd(ret)}" if ret else "")
            + f"&adults={adults}&currency={cur}"
        ),
    ),
    FlightSite(
        slug="flightsfinder",
        name="FlightsFinder",
        kind="metasearch",
        priority=32,
        scrolls=4,
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.flightsfinder.com/flights/{o}/{d}/{_ymd(dep)}"
            + (f"/{_ymd(ret)}" if ret else "")
            + f"?currency={cur}"
        ),
    ),
    FlightSite(
        slug="skyscanner",
        name="Skyscanner",
        kind="metasearch",
        priority=35,
        scrolls=4,
        regions=("global", "sea"),
        challenge_prone=True,
        note='Often answers "Are you a person or a robot?" — never bypassed (§15).',
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.skyscanner.net/transport/flights/{o.lower()}/{d.lower()}/"
            f"{_yymmdd(dep)}/"
            + (f"{_yymmdd(ret)}/" if ret else "")
            + f"?adults={adults}&cabinclass=economy&currency={cur}"
        ),
    ),
    FlightSite(
        slug="wego",
        name="Wego",
        kind="metasearch",
        priority=38,
        scrolls=4,
        regions=("sea", "mena"),
        challenge_prone=True,
        note="Strong on SEA low-cost carriers, but usually gated by a security check.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.wego.com/flights/searches/{o}-{d}-{_ymd(dep)}"
            + (f"-{_ymd(ret)}" if ret else "")
            + f"/economy/{adults}adult?currency={cur}"
        ),
    ),
    FlightSite(
        slug="traveloka",
        name="Traveloka",
        kind="ota",
        priority=40,
        scrolls=6,
        regions=("sea",),
        note="Malaysian locale already quotes MYR; renders slowly inside an iframe.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.traveloka.com/en-my/flight/fullsearch?ap="
            f"{o}.{d}&dt={_compact(dep)}."
            + (f"{_compact(ret)}" if ret else "NA")
            + f"&ps={adults}.0.0&sc=ECONOMY"
        ),
    ),
    FlightSite(
        slug="kayak",
        name="Kayak",
        kind="metasearch",
        crawlable=False,
        priority=42,
        note="robots.txt disallows /flights — link only, never crawled.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.kayak.com/flights/{o}-{d}/{_ymd(dep)}"
            + (f"/{_ymd(ret)}" if ret else "")
            + (f"/{adults}adults" if adults > 1 else "")
            + f"?sort=price_a&currency={cur}"
        ),
    ),
    FlightSite(
        slug="expedia",
        name="Expedia",
        kind="ota",
        crawlable=False,
        priority=48,
        note="robots.txt disallows Flights-Search — link only, never crawled.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.expedia.com/Flights-Search?trip="
            + ("roundtrip" if ret else "oneway")
            + f"&leg1=from:{o},to:{d},departure:{_us(dep)}TANYT"
            + (f"&leg2=from:{d},to:{o},departure:{_us(ret)}TANYT" if ret else "")
            + f"&passengers=adults:{adults}&options=cabinclass:economy&mode=search"
        ),
    ),
    FlightSite(
        slug="cheapoair",
        name="CheapOair",
        kind="ota",
        priority=55,
        challenge_prone=True,
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.cheapoair.com/air/listing?d1={o}&a1={d}&dt1={_us(dep)}"
            + (f"&dt2={_us(ret)}" if ret else "")
            + f"&px={adults}&cl=Economy&tt="
            + ("R" if ret else "O")
        ),
    ),
    # ----------------------------------------------------------------- #
    # Airline direct — only ever quotes itself, so it goes last.
    # ----------------------------------------------------------------- #
    FlightSite(
        slug="airasia",
        name="AirAsia",
        kind="airline",
        priority=70,
        scrolls=3,
        regions=("sea",),
        challenge_prone=True,
        note="Dominant on Malaysian domestic routes; usually gated by a bot check.",
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.airasia.com/flights/search/?origin="
            f"{o}&destination={d}&departDate={_ymd(dep)}"
            + (f"&returnDate={_ymd(ret)}" if ret else "")
            + f"&adult={adults}&currency={cur}&type="
            + ("return" if ret else "oneWay")
        ),
    ),
    FlightSite(
        slug="batikair",
        name="Batik Air Malaysia",
        kind="airline",
        priority=75,
        scrolls=3,
        regions=("sea",),
        supports_currency=False,
        build_url=lambda o, d, dep, ret, adults, cur: (
            f"https://www.batikair.com/en-ID/booking/flight?from={o}&to={d}"
            f"&departure={_ymd(dep)}" + (f"&return={_ymd(ret)}" if ret else "") + f"&adult={adults}"
        ),
    ),
    FlightSite(
        slug="malaysiaairlines",
        name="Malaysia Airlines",
        kind="airline",
        priority=78,
        scrolls=3,
        regions=("sea",),
        supports_currency=False,
        build_url=lambda o, d, dep, ret, adults, cur: (
            "https://www.malaysiaairlines.com/my/en/book-with-us/flight-search.html"
            f"?origin={o}&destination={d}&departureDate={_ymd(dep)}"
            + (f"&returnDate={_ymd(ret)}" if ret else "")
            + f"&adults={adults}"
        ),
    ),
)

#: Fast lookup by slug.
BY_SLUG: dict[str, FlightSite] = {site.slug: site for site in SITES}

#: Airports whose routes benefit from the South-east Asian engines.
_SEA_AIRPORTS = frozenset(
    {
        "KUL",
        "SZB",
        "BKI",
        "PEN",
        "LGK",
        "KCH",
        "JHB",
        "IPH",
        "KBR",
        "TGG",
        "AOR",
        "MYY",
        "SBW",
        "SDK",
        "TWU",
        "LBU",
        "MKZ",
        "SIN",
        "BKK",
        "HKT",
        "CNX",
        "KBV",
        "CGK",
        "DPS",
        "SUB",
        "KNO",
        "JOG",
        "MNL",
        "CEB",
        "HAN",
        "SGN",
        "DAD",
        "PNH",
        "REP",
        "VTE",
        "RGN",
        "BWN",
    }
)


def select_sites(
    origin: str,
    destination: str,
    *,
    limit: int = 6,
    include_airlines: bool = True,
) -> list[FlightSite]:
    """Choose which sites to consider for this route, best-prospect first.

    Metasearch leads because that is where a lower fare actually shows up — an
    airline's own page can only quote itself, which is exactly how a search ends
    up recommending AirAsia while another site is cheaper.

    Sites known to answer with a bot challenge are demoted rather than removed:
    they sometimes let a plain visit through, and a demoted attempt costs little.
    """
    regional = origin.upper() in _SEA_AIRPORTS and destination.upper() in _SEA_AIRPORTS

    def rank(site: FlightSite) -> tuple[int, int]:
        score = site.priority
        if regional and "sea" in site.regions:
            score -= 8
        if not regional and "sea" in site.regions and site.kind == "airline":
            # A Malaysian carrier is irrelevant to a Paris→Rome hop.
            score += 40
        if site.challenge_prone:
            score += 25
        return (score, site.priority)

    candidates = [s for s in SITES if include_airlines or s.kind != "airline"]
    return sorted(candidates, key=rank)[:limit]


def crawlable_sites(
    origin: str,
    destination: str,
    *,
    limit: int = 6,
) -> list[FlightSite]:
    """Sites we may actually read, in best-prospect order."""
    ranked = select_sites(origin, destination, limit=len(SITES))
    return [site for site in ranked if site.crawlable][:limit]


def link_only_sites(origin: str, destination: str) -> list[FlightSite]:
    """Sites we may link to but must not crawl (robots.txt)."""
    ranked = select_sites(origin, destination, limit=len(SITES))
    return [site for site in ranked if not site.crawlable]


def build_targets(
    origin: str,
    destination: str,
    depart: date,
    *,
    return_date: date | None = None,
    adults: int = 1,
    currency: str = "MYR",
    limit: int = 6,
) -> list[dict[str, object]]:
    """Camofox `read_many` targets for a route, in the traveller's currency."""
    targets: list[dict[str, object]] = []
    for site in crawlable_sites(origin, destination, limit=limit):
        try:
            url = site.url_for(origin, destination, depart, return_date, adults, currency)
        except Exception:  # noqa: BLE001 — a bad builder must not kill the sweep
            continue
        targets.append(
            {
                "url": url,
                "label": site.name,
                "slug": site.slug,
                "kind": site.kind,
                "scrolls": site.scrolls,
                "challenge_prone": site.challenge_prone,
                "quotes_currency": site.supports_currency,
            }
        )
    return targets
