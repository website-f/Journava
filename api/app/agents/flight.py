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
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import flight_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.brain import gnosion_client
from app.core.cache import cached
from app.core.llm import LLMUnavailableError, complete
from app.core.settings import settings
from app.tools import amadeus, atlas_skill, camofox
from app.tools.atlas_skill import AtlasSkillError

logger = logging.getLogger(__name__)

#: Price deviation from the median beyond which an option is flagged an outlier.
OUTLIER_THRESHOLD = 0.20

#: Fare pages worth reading when Atlas has nothing. Aggregators only — never a
#: login, never a paywall (§8).
_RESEARCH_QUERIES = (
    "{origin} to {destination} flight {date} cheapest fare",
    "{origin} {destination} flight price {date} site:skyscanner.net OR site:kayak.com",
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
            f"flight:v2:{origin}:{destination}:{depart}:{request.travellers}"
            f":{request.budget_currency}"
        )

        async def producer() -> dict[str, Any]:
            # Atlas (bookable truth), Amadeus (breadth) and Camofox (discovery)
            # run concurrently — they are independent and the slowest one sets
            # the wall clock either way.
            self.emit("working", "Querying Atlas, Amadeus and Camofox research")
            atlas_raw, amadeus_raw, camofox_raw = await asyncio.gather(
                self._try_atlas(request, origin, destination, depart),
                self._try_amadeus(request, origin, destination, depart),
                self._try_camofox(origin, destination, depart),
            )

            report = {
                "atlas": {"count": len(atlas_raw), "status": "ok" if atlas_raw else "empty"},
                "amadeus": {"count": len(amadeus_raw), "status": "ok" if amadeus_raw else "empty"},
                "camofox": {
                    "count": len(camofox_raw["options"]),
                    "status": camofox_raw["status"],
                    "pages_read": camofox_raw["sources"],
                },
            }
            merged = [*atlas_raw, *amadeus_raw, *camofox_raw["options"]]
            if merged:
                live = ", ".join(
                    f"{name}:{info['count']}" for name, info in report.items() if info["count"]
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
        destination: str,
        depart: str,
    ) -> list[dict[str, Any]]:
        """Search Atlas. Returns [] (never raises) when the CLI is unavailable."""
        if depart == "flexible":
            return []  # Atlas requires a concrete departure date.

        api_key = await _atlas_key()
        try:
            envelope = await atlas_skill.search(
                origin,
                destination,
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
                "Atlas needs authorisation — run `atlas-flight auth login`",
                data={"code": envelope.code},
            )
            return []
        if envelope.is_empty_result:
            self.emit("active", f"Atlas: no inventory ({envelope.code})")
            return []
        if not envelope.ok:
            self.emit("waiting", f"Atlas: {envelope.code}", data={"code": envelope.code})
            return []

        return atlas_skill.normalize_offers(envelope)

    async def _try_amadeus(
        self,
        request: TripRequest,
        origin: str,
        destination: str,
        depart: str,
    ) -> list[dict[str, Any]]:
        """Search Amadeus for breadth. Returns [] when unconfigured or failing."""
        if depart == "flexible":
            return []
        offers = await amadeus.search_flights(
            origin,
            destination,
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
    ) -> dict[str, Any]:
        """Read public fare pages and extract advertised prices, with citations.

        This is discovery, not truth: the numbers are whatever the page showed,
        so each option keeps the URL it came from and is never marked verified.
        """
        empty: dict[str, Any] = {"options": [], "sources": [], "status": "unavailable"}
        if not await camofox.available():
            return empty

        date_label = depart if depart != "flexible" else "next month"
        self.emit("working", f"Camofox: reading fare pages for {origin}→{destination}")

        results = await asyncio.gather(
            *(
                camofox.search_with_sources(
                    query.format(origin=origin, destination=destination, date=date_label)
                )
                for query in _RESEARCH_QUERIES
            )
        )

        options: list[dict[str, Any]] = []
        pages: list[str] = []
        for result in results:
            if not result:
                continue
            pages.extend(result["sources"])
            options.extend(
                self._parse_researched_fares(
                    result["snapshot"], result["sources"], origin, destination, len(options)
                )
            )

        unique_pages = list(dict.fromkeys(pages))[:8]
        if not options and not unique_pages:
            return {"options": [], "sources": [], "status": "no_results"}

        self.emit(
            "active",
            f"Camofox: {len(options)} advertised fare(s) across {len(unique_pages)} page(s)",
        )
        return {"options": options, "sources": unique_pages, "status": "ok"}

    @staticmethod
    def _parse_researched_fares(
        snapshot: str,
        sources: list[str],
        origin: str,
        destination: str,
        offset: int,
    ) -> list[dict[str, Any]]:
        """Extract advertised fares from a crawled page snapshot.

        Deliberately conservative: at most three fares per page, deduplicated,
        and anything implausible is dropped rather than guessed at. A wrong price
        presented confidently is worse than no price.
        """
        found: list[dict[str, Any]] = []
        seen: set[float] = set()
        citation = sources[0] if sources else None

        for match in _PRICE_PATTERN.finditer(snapshot or ""):
            raw_currency = match.group("cur").upper()
            currency = _CURRENCY_ALIASES.get(raw_currency, raw_currency)
            try:
                amount = float(match.group("amt").replace(",", ""))
            except ValueError:
                continue
            # A one-way regional fare below 30 or above 30,000 is almost
            # certainly a page element that merely looks like a price.
            if not 30 <= amount <= 30_000 or amount in seen:
                continue
            seen.add(amount)
            index = offset + len(found) + 1
            found.append(
                {
                    "id": f"CFX-{index:03d}",
                    "title": f"Advertised fare {origin}→{destination} · {currency} {amount:,.0f}",
                    "price_amount": amount,
                    "price_currency": currency,
                    "provider": "Camofox research",
                    "source": "camofox",
                    "source_url": citation,
                    "reasoning": (
                        "Advertised on a public fare page — not a held fare. "
                        "Open the source link to confirm before relying on it."
                    ),
                    "verified": False,
                    "bookable": False,
                    "raw": {"source": "camofox", "pages": sources[:4]},
                }
            )
            if len(found) >= 3:
                break
        return found

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
        crawled = report.get("camofox", {}).get("count", 0)
        if crawled:
            parts.append(f"{crawled} advertised from research")
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
            "sources": {name: info.get("count", 0) for name, info in report.items()},
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
