"""Flight Agent — Atlas booking API + Camofox research, reconciled (§4.2, §5).

Key rule (§7.5): flights always reference the **global** inventory. Dietary and
personal preferences never remove flight options — they only influence ranking
(timing, connections, budget) and add booking-time requests such as the halal
special meal code MOML.

Two sources, always tagged, never blended:

| Source      | What it is                              | Bookable | Price is |
| ----------- | --------------------------------------- | -------- | -------- |
| **atlas**   | Live Atlas inventory via the CLI        | yes      | fact once `offer verify` confirms it |
| **camofox** | Public fare pages the browser agent read | no      | *advertised*, with the page URL |
| amadeus     | Amadeus test inventory (breadth)         | no       | indicative |

The tags are the honest part. A price an agent read on an aggregator page is not
the same claim as a fare the booking API will hold, so they are labelled
differently and the crawled one always carries the link the traveller can check.
Nothing is presented as verified unless Atlas re-priced it.

Gnosion is consulted before searching: a recent memory of the same route is used
to inform ranking, and every search writes back, so repeat routes get smarter
rather than just repeating the work.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote_plus

from app.agents.base import BaseAgent
from app.agents.prompts import flight_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.brain import gnosion_client
from app.core.cache import cached
from app.core.llm import LLMUnavailableError, complete
from app.core.settings import settings
from app.tools import amadeus, atlas_skill, camofox, fare_extract, flight_sites
from app.tools.atlas_skill import AtlasSkillError
from app.tools.frankfurter import rates as fx_rates

logger = logging.getLogger(__name__)

#: Price deviation from the median beyond which an option is flagged an outlier.
OUTLIER_THRESHOLD = 0.20

#: Travel domains whose links are worth surfacing as clickable fare pages. The
#: browser reads a public results page; these hosts become "open live fares"
#: cards. Aggregators/airlines only — never a login, never a paywall (§8).
_FARE_HOSTS = (
    "google.com/travel/flights",
    "skyscanner",
    "kayak",
    "momondo",
    "kiwi.com",
    "expedia",
    "trip.com",
    "wego",
    "agoda",
    "airasia",
    "malaysiaairlines",
    "batikair",
    "firefly",
    "cathaypacific",
    "singaporeair",
    "scoot",
)

#: "RM 1,234" / "MYR 1234.50" / "$421" — enough to read an advertised fare.
_PRICE_PATTERN = re.compile(
    r"(?P<cur>RM|MYR|USD|SGD|EUR|GBP|\$|€|£)\s?(?P<amt>\d[\d,]{1,8}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_CURRENCY_ALIASES = {"$": "USD", "€": "EUR", "£": "GBP", "RM": "MYR"}


class FlightAgent(BaseAgent):
    slug = "flight"
    name = "Flight"
    role = "Atlas booking · Camofox research · reconciliation"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        # Inventory stays global — we only record how prefs affect ranking.
        applied: dict[str, Scope] = {}
        special_requests: dict[str, str] = {}

        if profile.halal_required:
            # Never a filter on flights; becomes a meal request at booking time.
            applied["halal_required"] = "not_applicable"
            special_requests["meal_code"] = "MOML"
        if profile.avoid_red_eye:
            applied["avoid_red_eye"] = "soft_ranking"
        if profile.max_connections is not None:
            applied["max_connections"] = "soft_ranking"
        if request.budget_amount is not None:
            applied["budget"] = "soft_ranking"

        origin = _airport_code(request.origin) or profile.home_airport or "KUL"
        destination = _airport_code(request.destination) or "unknown"
        depart = str(request.start_date) if request.start_date else "flexible"

        self.emit("working", f"Searching flights {origin} → {destination}")

        # Prior knowledge of this route, if the brain has any.
        recalled = self._recall_route(origin, destination)
        if recalled:
            self.emit(
                "working",
                f"Recalled a previous {origin}→{destination} search from memory",
                data={"recalled": recalled.get("summary", "")[:160]},
            )

        # A recovery run must not be served the pre-disruption cache — that is
        # what made every "alternative flight" identical to the cancelled one.
        bypass_cache = bool((context or {}).get("bypass_cache"))

        options, source_report = await self._search(
            request, profile, origin, destination, depart, bypass_cache=bypass_cache
        )

        # --- Verification pass (spec §5 reconciliation pattern) ---
        options = await self._verify(options)

        # --- Time-of-day window from the request ("night", "morning", …) ---
        options = self._filter_time_window(options, request)

        # --- Preference-aware ranking (§7.5 soft signals only) ---
        options = self._apply_preferences(options, profile, request)
        ranking = self._rank(options)

        self._remember_route(origin, destination, options, source_report)

        summary = self._summarise(options, origin, destination, source_report)
        return AgentResult(
            agent=self.slug,
            summary=summary,
            options=options,
            applied_preferences=applied,
            warnings=self._warnings(options, source_report),
            data={
                "special_requests": special_requests,
                "scope": "global",
                "ranking": ranking,
                "route": {"origin": origin, "destination": destination, "depart": depart},
                "sources": source_report,
                "bookable_count": sum(1 for o in options if o.bookable),
                "recalled_from_memory": bool(recalled),
            },
        )

    # ---------------------------------------------------------------------- #
    # Search — the source ladder
    # ---------------------------------------------------------------------- #

    async def _search(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        origin: str,
        destination: str,
        depart: str,
        *,
        bypass_cache: bool = False,
    ) -> tuple[list[Option], dict[str, Any]]:
        cache_key = (
            # Version prefix: bump it whenever the *shape* of a result changes —
            # the site list, the extractor, the currency handling. Those are code
            # changes the key cannot otherwise see, and a stale hit silently
            # serves the old behaviour long after the new one ships.
            f"flight:v5:{origin}:{destination}:{depart}:{request.travellers}"
            f":{request.budget_currency}"
        )

        async def producer() -> dict[str, Any]:
            # Resolve the destination to candidate airports first. The static
            # table is instant; anything it misses (e.g. "Chengdu") goes to the
            # smart resolver, which asks the LLM for the right codes — or the
            # NEAREST airport when the place has none — so Atlas/Amadeus aren't
            # skipped on a perfectly valid trip.
            dest_candidates = _dest_airports(destination)
            used_nearest = False
            if not dest_candidates:
                dest_candidates, used_nearest = await _resolve_airports_llm(destination)
                if dest_candidates:
                    self.emit(
                        "active",
                        f"No exact airport match for {destination} — searching "
                        f"{'nearest ' if used_nearest else ''}airport(s): "
                        f"{', '.join(dest_candidates)}",
                    )

            # Atlas (bookable truth), Amadeus (breadth) and Camofox (discovery)
            # run concurrently — they are independent and the slowest one sets
            # the wall clock either way.
            self.emit("working", "Querying Atlas, Amadeus and Camofox research")
            atlas_raw, amadeus_raw, camofox_raw = await asyncio.gather(
                self._try_atlas(request, origin, dest_candidates, depart),
                self._try_amadeus(request, origin, dest_candidates, depart),
                self._try_camofox(
                    origin,
                    destination,
                    depart,
                    return_date=str(request.end_date) if request.end_date else None,
                    adults=max(1, request.travellers),
                    currency=request.budget_currency or "MYR",
                ),
            )

            report = {
                "atlas": {"count": len(atlas_raw), "status": "ok" if atlas_raw else "empty"},
                "amadeus": {"count": len(amadeus_raw), "status": "ok" if amadeus_raw else "empty"},
                "camofox": {
                    "count": len(camofox_raw["options"]),
                    "status": camofox_raw["status"],
                    "pages_read": camofox_raw["sources"],
                    "sites": camofox_raw.get("sites", {}),
                    "cheapest_site": camofox_raw.get("cheapest_site"),
                    "sites_read": camofox_raw.get("sites_read", 0),
                    "sites_failed": camofox_raw.get("sites_failed", []),
                },
            }
            report["destination_airports"] = {
                "codes": list(dest_candidates),
                "nearest": used_nearest,
            }
            merged = [*atlas_raw, *amadeus_raw, *camofox_raw["options"]]
            if merged:
                # Not every report entry is a source with a count (e.g.
                # destination_airports) — guard so a metadata entry can't KeyError.
                live = ", ".join(
                    f"{name}:{info['count']}"
                    for name, info in report.items()
                    if isinstance(info, dict) and info.get("count")
                )
                self.emit("active", f"Inventory — {live}")
                return {"options": merged, "report": report}

            # LLM simulation, clearly labelled.
            llm_options = await self._try_llm(request, profile)
            if llm_options:
                report["llm"] = {"count": len(llm_options), "status": "simulated"}
                return {"options": llm_options, "report": report}

            mock = self._mock_options(origin, destination)
            report["mock"] = {"count": len(mock), "status": "placeholder"}
            return {"options": mock, "report": report}

        if bypass_cache:
            self.emit("working", "Recovery run — bypassing cached inventory")
            payload = await producer()
        else:
            payload = await cached(cache_key, producer, ttl=settings.cache_ttl_short)

        payload = payload or {"options": [], "report": {}}
        return (
            self._to_options(payload.get("options") or [], request),
            payload.get("report") or {},
        )

    async def _try_atlas(
        self,
        request: TripRequest,
        origin: str,
        candidates: tuple[str, ...],
        depart: str,
    ) -> list[dict[str, Any]]:
        """Search Atlas. Returns [] (never raises) when the CLI is unavailable.

        `candidates` is the pre-resolved list of destination gateway airports
        (from the static table or the smart LLM resolver); we try each until one
        returns inventory, so a full-trip search still yields bookable Atlas fares
        instead of an empty section.
        """
        if depart == "flexible":
            return []  # Atlas requires a concrete departure date.

        if not candidates:
            return []

        api_key = await _atlas_key()
        for dest_code in candidates[:4]:
            try:
                envelope = await atlas_skill.search(
                    origin,
                    dest_code,
                    depart,
                    return_date=str(request.end_date) if request.end_date else None,
                    adults=max(1, request.travellers),
                    currency=request.budget_currency,
                    api_key=api_key,
                )
            except AtlasSkillError as exc:
                logger.info("Atlas unavailable (%s)", exc)
                return []

            if envelope.is_auth_problem:
                self.emit(
                    "waiting",
                    "Atlas needs authorisation — add your sandbox keys in the API Vault",
                    data={"code": envelope.code},
                )
                return []
            if envelope.is_empty_result or not envelope.ok:
                continue  # no inventory to this gateway — try the next one

            offers = atlas_skill.normalize_offers(envelope)
            if offers:
                if len(candidates) > 1:
                    self.emit("active", f"Atlas: {len(offers)} fare(s) via {dest_code}")
                return offers

        self.emit("active", f"Atlas: no inventory to {destination}")
        return []

    async def _try_amadeus(
        self,
        request: TripRequest,
        origin: str,
        candidates: tuple[str, ...],
        depart: str,
    ) -> list[dict[str, Any]]:
        """Search Amadeus for breadth. Returns [] when unconfigured or failing."""
        if depart == "flexible":
            return []
        if not candidates:
            return []
        offers = await amadeus.search_flights(
            origin,
            candidates[0],
            depart,
            return_date=str(request.end_date) if request.end_date else None,
            adults=max(1, request.travellers),
            currency=request.budget_currency,
        )
        if not offers:
            return []
        return [
            {
                "id": f"AMA-{offer.get('offer_id', index + 1)}",
                "title": f"{offer.get('airline', 'Unknown')} · {_stops_label(offer.get('stops'))}",
                "price_amount": offer.get("price_amount"),
                "price_currency": offer.get("price_currency", request.budget_currency),
                "provider": "Amadeus Self-Service (test)",
                "source": "amadeus",
                "reasoning": "Amadeus test inventory — indicative, not bookable here",
                "verified": False,
                "bookable": False,
                "raw": {
                    "source": "amadeus",
                    "stops": offer.get("stops", 0),
                    "departure": offer.get("departure", {}),
                    "arrival": offer.get("arrival", {}),
                    "booking_class": offer.get("booking_class"),
                },
            }
            for index, offer in enumerate(offers)
        ]

    async def _try_camofox(
        self,
        origin: str,
        destination: str,
        depart: str,
        *,
        return_date: str | None = None,
        adults: int = 1,
        currency: str = "MYR",
    ) -> dict[str, Any]:
        """Compare the fare sites a person would actually open.

        Crawling only Google Flights is why a KUL→BKI search recommended the
        AirAsia site while Cheapflights was cheaper: one page is one opinion, and
        an airline's own site can only ever quote itself.

        So this opens the metasearch engines concurrently — Google Flights,
        Skyscanner, Kayak, Cheapflights, Wego, Trip.com and the relevant carriers
        — lets each render, scrolls them so the lazy-loaded fare lists exist, and
        reads every result block. Google Flights keeps its dedicated parser
        because its layout is known; the rest go through the generic extractor.

        Discovery, not truth: nothing here is ever marked verified or bookable —
        that stays Atlas's job.
        """
        empty: dict[str, Any] = {
            "options": [],
            "sources": [],
            "status": "unavailable",
            "sites": {},
        }
        if not await camofox.available():
            return empty
        if depart == "flexible":
            return await self._camofox_links(origin, destination, depart)

        depart_date = _parse_iso_date(depart)
        if depart_date is None:
            return await self._camofox_links(origin, destination, depart)

        targets = flight_sites.build_targets(
            origin,
            destination,
            depart_date,
            return_date=_parse_iso_date(return_date) if return_date else None,
            adults=max(1, adults),
            currency=currency,
            limit=6,
        )
        if not targets:
            return await self._camofox_links(origin, destination, depart)

        names = ", ".join(str(t["label"]) for t in targets)
        self.emit(
            "working",
            f"Camofox: comparing {len(targets)} fare sites — {names}",
            data={"sites": [t["slug"] for t in targets]},
        )

        # A price token is the signal that a results page has actually rendered.
        pages = await camofox.read_many(
            targets, scrolls=4, ready=r"RM\s?\d|MYR|ringgit|\$\s?\d|USD"
        )

        fares: list[dict[str, Any]] = []
        read_urls: list[str] = []
        failures: list[str] = []

        for page in pages:
            label = str(page.get("label") or "")
            if not page.get("ok"):
                failures.append(f"{label}: {page.get('error', 'unreadable')}")
                continue
            url = str(page.get("url") or "")
            snapshot = page.get("snapshot") or ""
            read_urls.append(url)

            if page.get("slug") == "google_flights":
                # Known layout — the structured parser reads it far better than
                # the generic one, and keeps airline/times/stops intact.
                for flight in _parse_google_flights(snapshot):
                    fares.append(
                        {
                            "price_amount": flight["price"],
                            "price_currency": flight["currency"],
                            "airline": flight["airline"],
                            "departure_time": flight.get("dep24") or flight.get("dep"),
                            "arrival_time": flight.get("arr"),
                            "duration_hours": flight.get("duration_hours"),
                            "stops": flight.get("stops"),
                            "site": label,
                            "source_url": url,
                            "confidence": "high",
                        }
                    )
                continue

            fares.extend(
                fare_extract.extract_fares(snapshot, source_url=url, site_name=label, max_results=5)
            )

        if failures:
            logger.info("Camofox could not read: %s", "; ".join(failures[:5]))

        # Sites geolocate the container, so some quote USD even when asked for
        # MYR. Comparing mixed currencies is meaningless, so anything off-target
        # is converted — and every converted fare says so and keeps its original.
        fares, converted = await self._normalise_currency(fares, currency)

        summary = fare_extract.summarise_sites(fares)
        options = self._fares_to_options(fares, origin, destination, depart)

        # Sites we may not crawl are still worth offering: robots.txt governs
        # automated fetching, not whether a person may click a link. Adding them
        # keeps the comparison honest — the traveller can check the big engines
        # themselves even though we did not read them.
        options.extend(self._link_only_options(origin, destination, depart, offset=len(options)))

        if not fares:
            # Every readable page yielded nothing (consent wall, bot check, or a
            # layout change). Say so, and still hand over the links.
            self.emit(
                "active",
                f"Camofox: read {len(read_urls)} site(s), none exposed parseable fares",
            )
            discovered = await self._camofox_links(origin, destination, depart)
            merged = options + [
                option
                for option in discovered.get("options", [])
                if option.get("source_url") not in {o.get("source_url") for o in options}
            ]
            return {
                "options": merged,
                "sources": list(dict.fromkeys(read_urls + discovered.get("sources", [])))[:10],
                "status": "links_only" if merged else "no_results",
                "sites": {},
                "sites_read": len(read_urls),
                "sites_failed": failures[:6],
            }

        cheapest = summary.get("cheapest_site")
        self.emit(
            "active",
            (
                f"Camofox: {len(options)} advertised fare(s) across "
                f"{summary['sites_with_fares']} site(s)"
                + (f" — cheapest on {cheapest}" if cheapest else "")
            ),
            data={"per_site": summary["per_site"]},
        )

        return {
            "options": options,
            "sources": list(dict.fromkeys(read_urls))[:10],
            "status": "ok",
            "sites": summary["per_site"],
            "cheapest_site": cheapest,
            "sites_read": len(read_urls),
            "sites_failed": failures[:6],
        }

    async def _normalise_currency(
        self,
        fares: list[dict[str, Any]],
        target: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Convert research fares into the traveller's currency.

        Several sites ignore the currency parameter and quote whatever their
        geolocation suggests, which makes "cheapest" meaningless across a mixed
        list. Rates come from Frankfurter (no key). A fare that cannot be
        converted keeps its original currency rather than being silently
        relabelled — a wrong number in the right currency is worse than an
        honest foreign one.
        """
        target = (target or "MYR").upper()
        foreign = {
            (fare.get("price_currency") or "").upper()
            for fare in fares
            if fare.get("price_currency") and fare["price_currency"].upper() != target
        }
        if not foreign:
            return fares, 0

        rates = await fx_rates(target)
        if not rates:
            self.emit(
                "waiting",
                f"Could not fetch FX rates — leaving {', '.join(sorted(foreign))} fares as quoted",
            )
            return fares, 0

        converted = 0
        for fare in fares:
            source = (fare.get("price_currency") or "").upper()
            if not source or source == target:
                continue
            rate = rates.get(source)
            if not rate:
                continue
            original = float(fare["price_amount"])
            # `rates(base=target)` reads "1 target buys N of source", so
            # converting *into* target divides.
            fare["price_amount"] = round(original / rate, 2)
            fare["price_currency"] = target
            fare["converted_from"] = {"currency": source, "amount": original}
            converted += 1

        if converted:
            self.emit(
                "working",
                f"Converted {converted} fare(s) into {target} at today's rate",
            )
        return fares, converted

    @staticmethod
    def _link_only_options(
        origin: str,
        destination: str,
        depart: str,
        *,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Offer the robots-disallowed engines as links we never crawled.

        Google Flights, Kayak and Expedia all disallow their flight-search paths,
        and §8 commits us to honouring that. Omitting them entirely would be
        worse for the traveller than saying plainly: here is the link, we did not
        read it.
        """
        depart_date = _parse_iso_date(depart)
        if depart_date is None:
            return []

        options: list[dict[str, Any]] = []
        for index, site in enumerate(flight_sites.link_only_sites(origin, destination), 1):
            try:
                url = site.url_for(origin, destination, depart_date)
            except Exception:  # noqa: BLE001
                continue
            options.append(
                {
                    "id": f"CFX-L{offset + index:02d}",
                    "title": f"{site.name} — open {origin}→{destination} ({depart})",
                    "price_amount": None,
                    "price_currency": None,
                    "provider": f"{site.name} (not crawled)",
                    "source": "camofox",
                    "source_url": url,
                    "booking_url": url,
                    "reasoning": (
                        f"{site.name}'s robots.txt disallows automated access to its "
                        "results, so Journava did not read it. Open the link to compare "
                        "yourself."
                    ),
                    "verified": False,
                    "bookable": False,
                    "raw": {"source": "camofox", "kind": "link_only", "site": site.slug},
                }
            )
        return options

    @staticmethod
    def _fares_to_options(
        fares: list[dict[str, Any]],
        origin: str,
        destination: str,
        depart: str,
    ) -> list[dict[str, Any]]:
        """Shape extracted fares into option dicts, keeping every citation.

        Cheapest first, and de-duplicated across sites: the same fare listed on
        four aggregators is one choice, not four, so the cheapest listing wins and
        the others are recorded as `also_on`.
        """
        best: dict[tuple[Any, ...], dict[str, Any]] = {}
        for fare in sorted(fares, key=lambda f: f["price_amount"]):
            key = (
                (fare.get("airline") or "").lower(),
                fare.get("departure_time"),
                round(float(fare["price_amount"]) / 10)
                if fare.get("airline")
                else fare["price_amount"],
            )
            if key in best:
                seen_on = best[key]["raw"].setdefault("also_on", [])
                entry = {
                    "site": fare.get("site"),
                    "price": fare["price_amount"],
                    "url": fare.get("source_url"),
                }
                if entry not in seen_on:
                    seen_on.append(entry)
                continue

            airline = fare.get("airline")
            stops = fare.get("stops")
            shape = "direct" if stops == 0 else (f"{stops} stop" if stops else "routing unstated")
            title = " \u00b7 ".join(
                bit
                for bit in (
                    airline or "Advertised fare",
                    f"{origin}\u2192{destination}",
                    fare.get("departure_time"),
                    shape,
                )
                if bit
            )
            best[key] = {
                "id": f"CFX-{len(best) + 1:03d}",
                "title": title,
                "price_amount": fare["price_amount"],
                "price_currency": fare.get("price_currency") or "MYR",
                "provider": f"Camofox \u00b7 {fare.get('site') or 'research'}",
                "source": "camofox",
                "source_url": fare.get("source_url"),
                "booking_url": fare.get("source_url"),
                "reasoning": (
                    f"Advertised on {fare.get('site') or 'a public page'} for {depart} "
                    f"({fare.get('confidence', 'low')}-confidence read). Not a held "
                    "fare \u2014 open the source to confirm."
                ),
                "verified": False,
                "bookable": False,
                "raw": {
                    "source": "camofox",
                    "kind": "compared_fare",
                    "site": fare.get("site"),
                    "stops": stops,
                    "duration_hours": fare.get("duration_hours"),
                    "departure_time": fare.get("departure_time"),
                    "arrival_time": fare.get("arrival_time"),
                    "extraction_confidence": fare.get("confidence"),
                    "converted_from": fare.get("converted_from"),
                    "also_on": [],
                },
            }
        return list(best.values())

    async def _camofox_links(
        self,
        origin: str,
        destination: str,
        depart: str,
    ) -> dict[str, Any]:
        """Fallback — surface clickable fare-page links when the live results
        page can't be parsed (no concrete date, or a consent/bot wall)."""
        date_label = depart if depart != "flexible" else "next month"
        query = f"flights from {origin} to {destination} {date_label}"
        result = await camofox.search_with_sources(query)
        snapshot = result["snapshot"] if result else ""
        sources = result["sources"] if result else []
        options = self._options_from_research(snapshot, sources, origin, destination, depart)
        unique_pages = list(dict.fromkeys(sources))[:8]
        if not options:
            return {"options": [], "sources": unique_pages, "status": "no_results"}
        return {"options": options, "sources": unique_pages, "status": "ok"}

    def _filter_time_window(
        self,
        options: list[Option],
        request: TripRequest,
    ) -> list[Option]:
        """Keep only flights departing inside a requested time-of-day window.

        The window is read from the goal ("night", "morning", …). Options with no
        known departure time (e.g. a fare-page link card) are always kept, and if
        nothing matches the window we keep everything rather than show an empty
        result.
        """
        window = _time_window_from_goal(request.goal or "")
        if not window:
            return options
        lo, hi = window

        def in_window(option: Option) -> bool:
            hour = _hour_of(option.raw.get("departure_time"))
            if hour is None:
                return True
            return (hour >= lo or hour < hi) if lo > hi else (lo <= hour < hi)

        timed = [o for o in options if _hour_of(o.raw.get("departure_time")) is not None]
        kept = [o for o in options if in_window(o)]
        kept_timed = [o for o in kept if _hour_of(o.raw.get("departure_time")) is not None]
        if timed and not kept_timed:
            self.emit("active", "No flights in the requested time window — showing all times")
            return options
        if timed:
            self.emit("active", f"Filtered to your time window ({lo:02d}:00–{hi:02d}:00)")
        return kept

    @classmethod
    def _options_from_research(
        cls,
        snapshot: str,
        sources: list[str],
        origin: str,
        destination: str,
        depart: str,
    ) -> list[dict[str, Any]]:
        """Turn a crawled results page into clickable fare-link options.

        Always includes a Google Flights link for the exact route/date (so there
        is at least one live-price link), adds the aggregator/airline links the
        page surfaced, and attaches any advertised price we can read. Conservative
        on prices: a confidently-shown wrong price is worse than none.
        """
        gf_url = _google_flights_url(origin, destination, depart)
        options: list[dict[str, Any]] = [
            {
                "id": "CFX-GF",
                "title": f"Google Flights — {origin}→{destination} (live fares)",
                "price_amount": None,
                "price_currency": "MYR",
                "provider": "Camofox research · Google Flights",
                "source": "camofox",
                "source_url": gf_url,
                "booking_url": gf_url,
                "reasoning": "Opens the live Google Flights results for your exact route and date.",
                "verified": False,
                "bookable": False,
                "raw": {"source": "camofox", "kind": "live_link"},
            }
        ]

        seen_hosts: set[str] = {"google.com/travel/flights"}
        for url in sources:
            host = next((h for h in _FARE_HOSTS if h in url), None)
            if not host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            label = _host_label(host)
            options.append(
                {
                    "id": f"CFX-{len(options):02d}",
                    "title": f"{label} — {origin}→{destination}",
                    "price_amount": None,
                    "price_currency": "MYR",
                    "provider": f"Camofox research · {label}",
                    "source": "camofox",
                    "source_url": url,
                    "booking_url": url,
                    "reasoning": "Advertised fares on a public page — open to see live prices.",
                    "verified": False,
                    "bookable": False,
                    "raw": {"source": "camofox", "kind": "fare_page"},
                }
            )
            if len(options) >= 6:
                break

        prices = cls._read_prices(snapshot)
        if prices:
            currency, amount = prices[0]
            options[0]["price_amount"] = amount
            options[0]["price_currency"] = currency
            options[0]["reasoning"] = (
                f"Advertised from {currency} {amount:,.0f} on the results page — "
                "open the link to confirm the live fare."
            )
        return options

    @staticmethod
    def _read_prices(snapshot: str) -> list[tuple[str, float]]:
        """Read plausible advertised fares out of a page snapshot, cheapest first."""
        out: list[tuple[str, float]] = []
        seen: set[float] = set()
        for match in _PRICE_PATTERN.finditer(snapshot or ""):
            raw_currency = match.group("cur").upper()
            currency = _CURRENCY_ALIASES.get(raw_currency, raw_currency)
            try:
                amount = float(match.group("amt").replace(",", ""))
            except ValueError:
                continue
            # Below 30 or above 30,000 is almost certainly a page element that
            # merely looks like a fare, not a real one-way regional price.
            if not 30 <= amount <= 30_000 or amount in seen:
                continue
            seen.add(amount)
            out.append((currency, amount))
        out.sort(key=lambda pair: pair[1])
        return out

    async def _try_llm(
        self,
        request: TripRequest,
        profile: TravelerProfile,
    ) -> list[dict[str, Any]]:
        try:
            self.emit("working", "No live inventory — generating options via LLM")
            messages = flight_messages(request, profile)
            raw_text = await complete(
                messages, response_format={"type": "json_object"}, agent="flight"
            )
            options = json.loads(raw_text).get("options", [])
            for option in options:
                option["provider"] = option.get("provider") or "LLM simulation"
                option["source"] = "llm"
                option["verified"] = False
                option["bookable"] = False
            return options
        except (LLMUnavailableError, json.JSONDecodeError) as exc:
            logger.warning("Flight LLM failed: %s", exc)
            self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
            return []

    # ---------------------------------------------------------------------- #
    # Shaping
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _to_options(raw_options: list[dict[str, Any]], request: TripRequest) -> list[Option]:
        options: list[Option] = []
        for raw in raw_options:
            try:
                price = raw.get("price_amount")
                options.append(
                    Option(
                        id=raw.get("id", f"FL{len(options) + 1:03d}"),
                        kind="flight",
                        title=raw.get("title", "Flight"),
                        price_amount=Decimal(str(price)) if price is not None else None,
                        price_currency=raw.get("price_currency", request.budget_currency),
                        provider=raw.get("provider"),
                        booking_url=raw.get("booking_url"),
                        reasoning=raw.get("reasoning"),
                        verified=bool(raw.get("verified", False)),
                        last_checked=raw.get("last_checked"),
                        source=raw.get("source"),
                        source_url=raw.get("source_url"),
                        bookable=bool(raw.get("bookable", False)),
                        raw=raw.get("raw", {}),
                    )
                )
            except (InvalidOperation, Exception) as exc:  # noqa: BLE001
                logger.warning("Skipping malformed flight option: %s", exc)
        return options

    async def _verify(self, options: list[Option]) -> list[Option]:
        """Reconcile prices before anything is surfaced (spec §5).

        Two checks, in order of authority:

        1. **Atlas re-price** (`offer verify`). Atlas re-confirming a fare is the
           only signal strong enough to earn the badge on its own.
        2. **Cross-source median** for the rest. An option far from the median of
           what the other sources returned is flagged, because a lone cheap price
           is usually a stale one.
        """
        if not options:
            return options

        atlas_offers = [
            option for option in options if option.source == "atlas" and option.raw.get("offer_id")
        ]
        if atlas_offers:
            self.emit("working", f"Re-pricing {len(atlas_offers)} Atlas offer(s)")
            api_key = await _atlas_key()
            verdicts = await asyncio.gather(
                *(self._reprice(option, api_key) for option in atlas_offers),
                return_exceptions=True,
            )
            confirmed = sum(1 for verdict in verdicts if verdict is True)
            if confirmed:
                self.emit("active", f"{confirmed} fare(s) confirmed by Atlas")

        prices = [float(o.price_amount) for o in options if o.price_amount is not None]
        if len(prices) >= 2:
            prices.sort()
            median = prices[len(prices) // 2]
            for option in options:
                if option.price_amount is None or option.verified:
                    continue
                option.last_checked = "just now"
                if median <= 0:
                    continue
                deviation = abs(float(option.price_amount) - median) / median
                if deviation > OUTLIER_THRESHOLD:
                    note = "price outlier vs other sources — confirm before booking"
                    option.reasoning = (
                        f"{option.reasoning} ({note})" if option.reasoning else note.capitalize()
                    )
        return options

    @staticmethod
    async def _reprice(option: Option, api_key: str | None) -> bool:
        """Re-price one Atlas offer; mark verified only if Atlas confirms."""
        try:
            envelope = await atlas_skill.verify_offer(str(option.raw["offer_id"]), api_key=api_key)
        except AtlasSkillError as exc:
            logger.info("Atlas re-price failed for %s: %s", option.id, exc)
            return False

        if envelope.code == "OFFER_EXPIRED":
            option.reasoning = "Offer expired before it could be confirmed — search again"
            option.bookable = False
            return False

        data = envelope.data
        booking_id = data.get("booking_id")
        if booking_id:
            option.raw["booking_id"] = booking_id

        new_price = data.get("total_price") or (data.get("price") or {}).get("total")
        if new_price is not None:
            try:
                parsed = Decimal(str(new_price))
            except InvalidOperation:
                parsed = None
            if parsed is not None and parsed != option.price_amount:
                option.reasoning = (
                    f"Price changed on verification: {option.price_amount} → {parsed}"
                )
                option.price_amount = parsed

        if envelope.code in ("OFFER_VERIFIED", "PRICE_CONFIRMED"):
            option.verified = True
            option.bookable = True
            option.last_checked = "just now"
            return True
        if envelope.code == "PRICE_CHANGED":
            option.verified = True
            option.bookable = True
            option.last_checked = "just now"
            option.reasoning = f"{option.reasoning} — re-confirmation required before payment"
            return True
        return False

    @staticmethod
    def _apply_preferences(
        options: list[Option],
        profile: TravelerProfile,
        request: TripRequest,
    ) -> list[Option]:
        """Soft ranking only — never removes an option (§7.5).

        Preferences reorder the list and explain themselves in `reasoning`. The
        inventory the traveller sees is still the global one.
        """

        def score(option: Option) -> tuple[float, float]:
            penalty = 0.0
            stops = int(option.raw.get("stops") or 0)
            if profile.max_connections is not None and stops > profile.max_connections:
                penalty += 2.0
            if profile.avoid_red_eye and _is_red_eye(option.raw.get("departure_time")):
                penalty += 1.5
            # A bookable, verified fare outranks an advertised one at equal price.
            if not option.bookable:
                penalty += 0.5
            if option.source == "camofox":
                penalty += 0.25
            price = float(option.price_amount) if option.price_amount is not None else 1e9
            return (penalty, price)

        annotated = sorted(options, key=score)
        for option in annotated:
            notes: list[str] = []
            stops = int(option.raw.get("stops") or 0)
            if profile.max_connections is not None and stops > profile.max_connections:
                notes.append(f"more stops than your usual max of {profile.max_connections}")
            if profile.avoid_red_eye and _is_red_eye(option.raw.get("departure_time")):
                notes.append("red-eye departure")
            if request.budget_amount and option.price_amount:
                if float(option.price_amount) > float(request.budget_amount):
                    notes.append("above your stated budget")
            if notes:
                option.raw["preference_notes"] = notes
        return annotated

    @staticmethod
    def _rank(options: list[Option]) -> dict[str, str | None]:
        """Build the 4-bucket ranking from §5."""
        priced = [(o, float(o.price_amount)) for o in options if o.price_amount is not None]
        if not priced:
            return {
                "cheapest": None,
                "cheapest_with_baggage": None,
                "best_value": None,
                "best_time": None,
            }
        priced.sort(key=lambda pair: pair[1])

        cheapest = priced[0][0]
        with_baggage = next((o for o, _ in priced if o.raw.get("baggage_included")), cheapest)
        # Best value prefers a bookable direct fare over a cheaper unbookable one.
        bookable_direct = [o for o, _ in priced if o.bookable and int(o.raw.get("stops") or 0) == 0]
        bookable_any = [o for o, _ in priced if o.bookable]
        best_value = (
            bookable_direct[0]
            if bookable_direct
            else (bookable_any[0] if bookable_any else cheapest)
        )
        best_time = min(
            (o for o, _ in priced),
            key=lambda o: float(o.raw.get("duration_hours") or 99),
        )
        return {
            "cheapest": cheapest.id,
            "cheapest_with_baggage": with_baggage.id,
            "best_value": best_value.id,
            "best_time": best_time.id,
        }

    @staticmethod
    def _summarise(
        options: list[Option],
        origin: str,
        destination: str,
        report: dict[str, Any],
    ) -> str:
        if not options:
            return f"No flights found {origin} → {destination}"
        bookable = sum(1 for o in options if o.bookable)
        parts = [f"{len(options)} option(s) {origin} → {destination}"]
        if bookable:
            parts.append(f"{bookable} bookable via Atlas")
        # Name the sites actually read, and count only options carrying a price.
        # Saying "read live from Google Flights" while Google Flights was never
        # opened (its robots.txt disallows it) is the kind of claim that makes a
        # whole result untrustworthy.
        camofox_report = report.get("camofox") or {}
        priced_research = sum(
            1
            for option in options
            if option.source == "camofox" and option.price_amount is not None
        )
        site_names = [
            name for name, info in (camofox_report.get("sites") or {}).items() if info.get("count")
        ]
        if priced_research and site_names:
            listed = ", ".join(site_names[:3])
            more = f" +{len(site_names) - 3}" if len(site_names) > 3 else ""
            parts.append(f"{priced_research} compared from {listed}{more}")
        elif priced_research:
            parts.append(f"{priced_research} from public fare pages")

        link_only = sum(1 for o in options if o.raw.get("kind") == "link_only")
        if link_only:
            parts.append(f"{link_only} link(s) not crawled")
        cheapest = min(
            (o for o in options if o.price_amount is not None),
            key=lambda o: float(o.price_amount),
            default=None,
        )
        if cheapest is not None:
            parts.append(f"from {cheapest.price_currency} {float(cheapest.price_amount):,.0f}")
        return " · ".join(parts)

    @staticmethod
    def _warnings(options: list[Option], report: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        airports = report.get("destination_airports") or {}
        if airports.get("nearest") and airports.get("codes"):
            warnings.append(
                "This destination has no airport of its own — searched the "
                f"nearest instead: {', '.join(airports['codes'])}."
            )
        if not any(o.bookable for o in options):
            if report.get("atlas", {}).get("count"):
                warnings.append(
                    "Atlas returned fares but none could be re-priced — treat prices as indicative."
                )
            else:
                warnings.append(
                    "No bookable Atlas inventory. Prices shown are advertised or "
                    "simulated, not held fares."
                )
        if report.get("camofox", {}).get("count"):
            warnings.append(
                "Research fares come from public pages; open the source link to verify."
            )
        if report.get("mock"):
            warnings.append("Showing placeholder data — no flight source and no LLM was available.")
        return warnings

    # ---------------------------------------------------------------------- #
    # Memory
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _recall_route(origin: str, destination: str) -> dict[str, Any] | None:
        stored = gnosion_client.recall("flights", f"{origin}-{destination}".lower())
        if not stored:
            return None
        try:
            raw = stored["value"] if isinstance(stored, dict) else stored
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    @staticmethod
    def _remember_route(
        origin: str,
        destination: str,
        options: list[Option],
        report: dict[str, Any],
    ) -> None:
        if not options:
            return
        priced = [o for o in options if o.price_amount is not None]
        payload = {
            "summary": f"{len(options)} options {origin}→{destination}",
            "cheapest": (float(min(float(o.price_amount) for o in priced)) if priced else None),
            "currency": priced[0].price_currency if priced else None,
            "sources": {
                name: info["count"]
                for name, info in report.items()
                if isinstance(info, dict) and "count" in info
            },
        }
        try:
            gnosion_client.remember(
                "flights",
                key=f"{origin}-{destination}".lower(),
                value=json.dumps(payload, default=str),
                label="flight",
            )
        except Exception as exc:  # noqa: BLE001 — memory is never fatal
            logger.debug("Could not remember route: %s", exc)

    @staticmethod
    def _mock_options(origin: str, destination: str) -> list[dict[str, Any]]:
        """Placeholder so the UI renders when nothing at all is configured."""
        return [
            {
                "id": "FL001",
                "title": f"Placeholder direct — {origin} to {destination}",
                "price_amount": 850.00,
                "price_currency": "MYR",
                "provider": "Placeholder (no source configured)",
                "source": "mock",
                "reasoning": (
                    "Placeholder data. Add an AI model in Engine or authorise Atlas "
                    "in the API Vault for real fares."
                ),
                "verified": False,
                "bookable": False,
                "raw": {"source": "mock", "stops": 0, "duration_hours": 2.5},
            },
        ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _atlas_key() -> str | None:
    """Atlas credential from the vault, if the operator stored one."""
    from app.core import vault

    return await vault.secret_for("atlas")


def _stops_label(stops: Any) -> str:
    """ "direct" / "1 stop" / "2 stops" from a stop count."""
    count = int(stops or 0)
    if count == 0:
        return "direct"
    return f"{count} stop" if count == 1 else f"{count} stops"


def _google_flights_url(origin: str, destination: str, depart: str) -> str:
    """A clickable Google Flights link for the exact route (and date, if known)."""
    query = f"flights from {origin} to {destination}"
    if depart and depart != "flexible":
        query += f" on {depart}"
    return "https://www.google.com/travel/flights?q=" + quote_plus(query)


def _google_flights_results_url(origin: str, destination: str, depart: str) -> str:
    """A one-way Google Flights *results* URL that renders parseable flight rows."""
    query = f"Flights to {destination} from {origin} on {depart} one way"
    return "https://www.google.com/travel/flights?hl=en&gl=my&curr=MYR&q=" + quote_plus(query)


#: One flight row from the Google Flights accessibility tree. The link's aria
#: label is a stable sentence: "From 432 Malaysian ringgits. Nonstop flight with
#: Malaysia Airlines. Leaves … at 6:30 PM on Friday, November 6 and arrives … at
#: 9:10 PM." — price, stops, airline, departure, arrival, in that order.
_GF_ROW = re.compile(
    r"From\s+([\d,]+)\s+Malaysian ringgit\w*\.\s+"
    r"(Nonstop|1\s+stop|\d+\s+stops?)\s+flights?\s+with\s+(.+?)\.\s+"
    r"Leaves\b.*?\bat\s+(\d{1,2}:\d{2}\s*[AP]M)\s+on\b.*?\band\s+arrives\b.*?\bat\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_google_flights(snapshot: str) -> list[dict[str, Any]]:
    """Read each flight (airline, times, stops, price) from a results snapshot."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for match in _GF_ROW.finditer(snapshot or ""):
        try:
            price = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if not 30 <= price <= 30_000:
            continue
        stops_label = match.group(2).strip().lower()
        airline = re.sub(r"\s+", " ", match.group(3)).strip()
        dep = _norm_ampm(match.group(4))
        arr = _norm_ampm(match.group(5))
        key = (airline, dep, price)
        if key in seen:
            continue
        seen.add(key)
        stops = 0 if "nonstop" in stops_label else _first_int(stops_label)
        out.append(
            {
                "airline": airline,
                "price": price,
                "currency": "MYR",
                "dep": dep,
                "arr": arr,
                "dep24": _to_24h(dep),
                "stops": stops,
                "stops_label": (
                    "Nonstop"
                    if stops == 0
                    else (f"{stops} stop" if stops == 1 else f"{stops} stops")
                ),
            }
        )
        if len(out) >= 15:
            break
    out.sort(key=lambda flight: flight["price"])
    return out


def _norm_ampm(value: str) -> str:
    """ "6:30 PM" with single-spaced, upper-cased meridiem."""
    match = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", value, re.IGNORECASE)
    if not match:
        return value.strip()
    return f"{int(match.group(1))}:{match.group(2)} {match.group(3).upper()}"


def _to_24h(value: str) -> str | None:
    """ "6:30 PM" → "18:30"."""
    match = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", value, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).upper() == "PM":
        hour += 12
    return f"{hour:02d}:{match.group(2)}"


def _hour_of(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    match = re.match(r"(\d{1,2}):(\d{2})", str(hhmm))
    return int(match.group(1)) if match else None


def _first_int(text: str) -> int:
    match = re.search(r"\d+", text)
    return int(match.group()) if match else 1


def _time_window_from_goal(goal: str) -> tuple[int, int] | None:
    """Map a phrase in the request to a [start, end) hour window (wraps midnight)."""
    text = goal.lower()
    if "red eye" in text or "red-eye" in text:
        return (22, 6)
    if "night" in text or "malam" in text:  # 'malam' = night (Malay)
        return (18, 5)
    if "evening" in text or "petang" in text:
        return (17, 22)
    if "morning" in text or "pagi" in text:
        return (5, 12)
    if "afternoon" in text or "tengah hari" in text:
        return (12, 17)
    return None


#: Pretty names for the fare hosts we surface as clickable cards.
_HOST_LABELS = {
    "google.com/travel/flights": "Google Flights",
    "skyscanner": "Skyscanner",
    "kayak": "Kayak",
    "momondo": "Momondo",
    "kiwi.com": "Kiwi.com",
    "expedia": "Expedia",
    "trip.com": "Trip.com",
    "wego": "Wego",
    "agoda": "Agoda",
    "airasia": "AirAsia",
    "malaysiaairlines": "Malaysia Airlines",
    "batikair": "Batik Air",
    "firefly": "Firefly",
    "cathaypacific": "Cathay Pacific",
    "singaporeair": "Singapore Airlines",
    "scoot": "Scoot",
}


def _host_label(host: str) -> str:
    return _HOST_LABELS.get(host, host)


def _is_red_eye(departure_time: str | None) -> bool:
    """True for departures between 22:00 and 06:00."""
    if not departure_time:
        return False
    match = re.search(r"(\d{1,2}):(\d{2})", str(departure_time))
    if not match:
        return False
    hour = int(match.group(1))
    return hour >= 22 or hour < 6


#: Common airport names travellers use interchangeably with IATA codes.
_AIRPORT_ALIASES = {
    "klia": "KUL",
    "kuala lumpur": "KUL",
    "kl": "KUL",
    "klia2": "KUL",
    "subang": "SZB",
    "kota kinabalu": "BKI",
    "kk": "BKI",
    "penang": "PEN",
    "langkawi": "LGK",
    "kuching": "KCH",
    "johor bahru": "JHB",
    "singapore": "SIN",
    "changi": "SIN",
    "bangkok": "BKK",
    "jakarta": "CGK",
    "bali": "DPS",
    "denpasar": "DPS",
    "tokyo": "NRT",
    "osaka": "KIX",
    "seoul": "ICN",
    "hong kong": "HKG",
    "taipei": "TPE",
    "dubai": "DXB",
    "doha": "DOH",
    "istanbul": "IST",
    "london": "LHR",
    "paris": "CDG",
    "venice": "VCE",
    "rome": "FCO",
    "amsterdam": "AMS",
    "sydney": "SYD",
    "melbourne": "MEL",
}


#: Country / metro names → ordered candidate airports. Atlas needs an IATA code,
#: but travellers say "Japan" or "Thailand". For a country we try its main
#: international gateways in order and use the first with inventory, so a
#: full-trip "BKI → Japan" still returns bookable Atlas fares instead of nothing.
_COUNTRY_CITY_AIRPORTS: dict[str, tuple[str, ...]] = {
    "japan": ("NRT", "HND", "KIX", "FUK"),
    "tokyo": ("NRT", "HND"),
    "osaka": ("KIX", "ITM"),
    "thailand": ("BKK", "DMK", "HKT"),
    "bangkok": ("BKK", "DMK"),
    "indonesia": ("CGK", "DPS"),
    "bali": ("DPS",),
    "jakarta": ("CGK",),
    "singapore": ("SIN",),
    "malaysia": ("KUL", "PEN", "BKI"),
    "korea": ("ICN", "GMP"),
    "south korea": ("ICN", "GMP"),
    "seoul": ("ICN", "GMP"),
    "vietnam": ("SGN", "HAN", "DAD"),
    "taiwan": ("TPE", "TSA"),
    "hong kong": ("HKG",),
    "china": ("PVG", "PEK", "CAN"),
    # Chinese cities the static table used to miss — the "Chengdu" gap that made
    # Atlas return nothing. Anything still missing goes to _resolve_airports_llm.
    "chengdu": ("CTU", "TFU"),
    "shanghai": ("PVG", "SHA"),
    "beijing": ("PEK", "PKX"),
    "guangzhou": ("CAN",),
    "shenzhen": ("SZX",),
    "chongqing": ("CKG",),
    "xian": ("XIY",),
    "xi'an": ("XIY",),
    "hangzhou": ("HGH",),
    "kunming": ("KMG",),
    "chiang mai": ("CNX",),
    "phuket": ("HKT",),
    "hanoi": ("HAN",),
    "da nang": ("DAD",),
    "danang": ("DAD",),
    "ho chi minh": ("SGN",),
    "kuala lumpur": ("KUL",),
    "penang": ("PEN",),
    "kota kinabalu": ("BKI",),
    "philippines": ("MNL", "CEB"),
    "australia": ("SYD", "MEL", "BNE"),
    "uae": ("DXB", "AUH"),
    "dubai": ("DXB",),
    "united kingdom": ("LHR", "LGW", "MAN"),
    "uk": ("LHR", "LGW"),
    "london": ("LHR", "LGW"),
    "france": ("CDG", "ORY"),
    "paris": ("CDG", "ORY"),
    "italy": ("FCO", "MXP", "VCE"),
    "turkey": ("IST", "SAW"),
    "india": ("DEL", "BOM"),
    "saudi arabia": ("JED", "RUH"),
    "qatar": ("DOH",),
}


def _dest_airports(value: str | None) -> tuple[str, ...]:
    """Resolve a destination into candidate IATA airports for Atlas/Amadeus.

    A three-letter code or known city → one airport; a country/metro → its main
    gateways in priority order; anything unrecognised → empty (Atlas is skipped).
    """
    if not value:
        return ()
    text = value.strip()
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return (text.upper(),)
    candidates = _COUNTRY_CITY_AIRPORTS.get(text.lower())
    if candidates:
        return candidates
    code = _airport_code(text)
    if code and re.fullmatch(r"[A-Z]{3}", code):
        return (code,)
    return ()


_AIRPORT_RESOLVER_SYSTEM = (
    "You map a place name to airport IATA codes. Respond ONLY as JSON: "
    '{"iata": ["CODE", ...], "nearest": false}. '
    "List the international airport(s) that actually serve the place, most useful "
    "first (max 3, uppercase 3-letter IATA). If the place has NO airport of its "
    "own, return the NEAREST major airport(s) instead and set nearest=true. Never "
    "invent codes; if you are unsure, return an empty list."
)


async def _resolve_airports_llm(destination: str | None) -> tuple[tuple[str, ...], bool]:
    """Resolve a place to IATA codes with the LLM when the static table misses.

    This is what makes the agent *smart* about less-obvious places (e.g. Chengdu
    → CTU/TFU) and about places with no airport of their own (returns the nearest
    and flags it). Cached per place, so it costs at most one LLM call per city.
    Returns (codes, used_nearest).
    """
    if not destination:
        return ((), False)

    async def resolve() -> dict[str, Any]:
        try:
            resp = await complete(
                [
                    {"role": "system", "content": _AIRPORT_RESOLVER_SYSTEM},
                    {"role": "user", "content": f"Place: {destination.strip()}"},
                ],
                response_format={"type": "json_object"},
                agent="flight",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001 — resolution is best-effort
            return {"iata": [], "nearest": False}
        codes = [
            c.strip().upper()
            for c in (data.get("iata") or [])
            if isinstance(c, str) and re.fullmatch(r"[A-Za-z]{3}", c.strip())
        ]
        return {"iata": list(dict.fromkeys(codes))[:3], "nearest": bool(data.get("nearest"))}

    key = f"airport-resolve:{destination.strip().lower()}"
    try:
        data = await cached(key, resolve, ttl=settings.cache_ttl_long)
    except Exception:  # noqa: BLE001
        data = {"iata": [], "nearest": False}
    return (tuple(data.get("iata") or ()), bool(data.get("nearest")))


def _airport_code(value: str | None) -> str | None:
    """Normalise a place into an IATA code where we can.

    Atlas requires IATA codes, and travellers type "KLIA" or "Kota Kinabalu".
    Resolving the common cases here keeps a natural request from failing with
    INVALID_ARGUMENT; anything unrecognised is passed through unchanged so the
    LLM-parsed value still gets its chance.
    """
    if not value:
        return None
    text = value.strip()
    if re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    alias = _AIRPORT_ALIASES.get(text.lower())
    if alias:
        return alias
    # "Kuala Lumpur (KUL)" / "KUL - Kuala Lumpur"
    match = re.search(r"\b([A-Z]{3})\b", text)
    if match:
        return match.group(1)
    for name, code in _AIRPORT_ALIASES.items():
        if name in text.lower():
            return code
    return text


def _parse_iso_date(value: str | None) -> _date | None:
    """Parse an ISO date, or None for "flexible" / anything unparseable."""
    if not value or value == "flexible":
        return None
    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
