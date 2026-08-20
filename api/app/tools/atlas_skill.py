"""Atlas Flight Booking Skill wrapper (spec §9, §4.2).

Written against the real CLI (`atlas-flight-booking==0.3.12`), whose surface is:

    atlas-flight environment use {sandbox|production} --json
    atlas-flight auth login|status|poll --json
    atlas-flight session refresh --json
    atlas-flight doctor --json
    atlas-flight search --origin KUL --destination BKI --depart YYYY-MM-DD
                        --adults N [--return-date D] [--children N] [--infants N]
                        [--airline XX ...] [--currency MYR]
                        [--multiple-fare-families] --json
    atlas-flight offer list   --search-id ID  --json
    atlas-flight offer verify --offer-id ID   --json
    atlas-flight booking confirm-price --booking-id ID --json
    atlas-flight baggage list|select|remove ...
    atlas-flight seat    list|select|remove ...
    atlas-flight order create --booking-id ID (--passengers-stdin|--passengers-file F)
                              [--seat-policy P] --json
    atlas-flight order pay    --confirmation-id ID --json
    atlas-flight order status --order-no NO --json

Every subcommand returns **one stable envelope**:

    {"schema_version": "1", "status": "success|action_required|
      retryable_error|terminal_error", "code": "FLIGHT_SEARCHED", "message": "...",
     "retryable": false, "request_id": "...", "data": {...}, "details": {...}}

Process exit codes: 0 ok · 2 INVALID_ARGUMENT · 20 retryable · 30 terminal. A
non-zero exit still prints a valid envelope, so the envelope — not the exit code —
is the source of truth, and callers branch on `code`.

Two things this wrapper must not get wrong:

1. **`--sandbox` is not a flag.** The environment is CLI-level state set once via
   `environment use`. Appending `--sandbox` to every command makes each one fail
   with INVALID_ARGUMENT.
2. **Opaque IDs are opaque.** `search_id`, `offer_id`, `booking_id`,
   `confirmation_id` and `order_no` are passed through byte-for-byte, never
   parsed, reformatted or regenerated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Literal

from app.core.settings import settings

logger = logging.getLogger(__name__)

CLI_TIMEOUT_SECONDS = 90
#: Ticketing polls upstream for up to 120s, so allow headroom over that.
TICKETING_TIMEOUT_SECONDS = 150

AtlasEnvironment = Literal["sandbox", "production"]

#: Codes that mean "the caller must do something", not "this failed".
ACTION_REQUIRED_CODES = frozenset(
    {
        "AUTHORIZATION_REQUIRED",
        "AUTH_PENDING",
        "PASSENGER_INFO_REQUIRED",
        "PRICE_CONFIRMATION_REQUIRED",
        "PRICE_CHANGED",
        "PAYMENT_CONFIRMATION_REQUIRED",
        "PAYMENT_BALANCE_CHECK_REQUIRED",
        "TOP_UP_REQUIRED",
        "TICKETING_ACTIVATION_REQUIRED",
        "SUBSCRIPTION_REQUIRED",
    }
)

#: Codes that mean the credential/session is the problem.
AUTH_CODES = frozenset(
    {
        "AUTHORIZATION_REQUIRED",
        "AUTH_EXPIRED",
        "AUTH_SESSION_MISSING",
        "AUTH_STATUS_INVALID",
        "CREDENTIAL_REJECTED",
        "SECURE_STORE_UNAVAILABLE",
    }
)

#: Codes that mean "no inventory", which is an answer rather than a failure.
EMPTY_RESULT_CODES = frozenset(
    {
        "SEARCH_NO_RESULTS",
        "ROUTE_NOT_SUPPORTED",
        "AIRLINE_NO_FLIGHT",
        "FLIGHT_SOLD_OUT",
        "FLIGHT_UNAVAILABLE",
    }
)


class AtlasSkillError(RuntimeError):
    """The CLI is missing, timed out, or emitted something that isn't an envelope."""


class AtlasEnvelope(dict):
    """Thin accessor over the CLI's stable result object."""

    @property
    def status(self) -> str:
        return str(self.get("status", ""))

    @property
    def code(self) -> str:
        return str(self.get("code", ""))

    @property
    def message(self) -> str:
        return str(self.get("message", ""))

    @property
    def data(self) -> dict[str, Any]:
        value = self.get("data")
        return value if isinstance(value, dict) else {}

    @property
    def details(self) -> dict[str, Any]:
        value = self.get("details")
        return value if isinstance(value, dict) else {}

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def needs_action(self) -> bool:
        return self.status == "action_required" or self.code in ACTION_REQUIRED_CODES

    @property
    def is_auth_problem(self) -> bool:
        return self.code in AUTH_CODES

    @property
    def is_empty_result(self) -> bool:
        return self.code in EMPTY_RESULT_CODES


# --------------------------------------------------------------------------- #
# Process plumbing
# --------------------------------------------------------------------------- #


async def _run(
    *args: str,
    api_key: str | None = None,
    stdin_payload: str | None = None,
    timeout: int = CLI_TIMEOUT_SECONDS,
) -> AtlasEnvelope:
    """Invoke the CLI and parse its envelope.

    A non-zero exit is *not* treated as failure: the CLI documents that every
    subcommand prints an envelope, and the envelope carries the actionable `code`.
    Only a missing binary, a timeout, or unparseable output is an exception.
    """
    argv = [settings.atlas_flight_cli, *args]
    if "--json" not in argv:
        argv.append("--json")

    env = os.environ.copy()
    if api_key:
        # Headless hosts cannot complete the browser OAuth flow, so a token from
        # the vault is offered through the environment. The CLI still prefers its
        # own keychain session when one exists.
        env["ATLAS_API_KEY"] = api_key
        env["ATLAS_FLIGHT_API_KEY"] = api_key

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin_payload else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise AtlasSkillError(
            f"{settings.atlas_flight_cli} not found — install the skill "
            "(see skills/atlas-flight-booking/README.md)"
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_payload.encode() if stdin_payload else None),
            timeout=timeout,
        )
    except TimeoutError as exc:
        process.kill()
        raise AtlasSkillError(f"atlas-flight {args[0]} timed out") from exc

    text = stdout.decode(errors="replace").strip()
    if not text:
        detail = stderr.decode(errors="replace").strip()
        raise AtlasSkillError(detail or "atlas-flight produced no output")

    # Some hosts prepend installer chatter; the envelope is the last JSON object.
    envelope = _parse_envelope(text)
    if envelope is None:
        raise AtlasSkillError(f"atlas-flight returned non-JSON output: {text[:200]}")

    if envelope.code and not envelope.ok:
        logger.info("atlas-flight %s → %s (%s)", args[0], envelope.code, envelope.message[:120])
    return envelope


def _parse_envelope(text: str) -> AtlasEnvelope | None:
    """Extract the envelope, tolerating leading non-JSON noise."""
    try:
        return AtlasEnvelope(json.loads(text))
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return AtlasEnvelope(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Last resort: the outermost JSON object anywhere in the output.
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return AtlasEnvelope(json.loads(text[start : end + 1]))
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# Sandbox delegation
# --------------------------------------------------------------------------- #
# When the operator has stored an access-key + secret-key pair in the vault, we
# talk to the ATRIP sandbox HTTP API directly (headless, no browser OAuth). The
# CLI path below stays as the fallback for a keychain-authorised install. Each
# public call checks `_sandbox(...)` first; a None return means "not in sandbox
# mode — use the CLI".


async def _sandbox(fn_name: str, *args: Any, **kwargs: Any) -> AtlasEnvelope | None:
    """Run the sandbox equivalent when AK/SK creds exist, else return None.

    The sandbox module raises its own error type; translate it to the wrapper's
    so every caller keeps catching a single `AtlasSkillError`.
    """
    from app.tools import atlas_sandbox

    if not await atlas_sandbox.enabled():
        return None
    fn = getattr(atlas_sandbox, fn_name)
    try:
        return AtlasEnvelope(await fn(*args, **kwargs))
    except atlas_sandbox.AtlasSandboxError as exc:
        raise AtlasSkillError(str(exc)) from exc


async def sandbox_enabled() -> bool:
    from app.tools import atlas_sandbox

    return await atlas_sandbox.enabled()


# --------------------------------------------------------------------------- #
# Environment / auth / health
# --------------------------------------------------------------------------- #


async def use_environment(
    environment: AtlasEnvironment,
    *,
    api_key: str | None = None,
) -> AtlasEnvelope:
    """Point the CLI at sandbox or production.

    This is persistent CLI state, so it is set once rather than per call. Any
    offer obtained before a switch expires — always re-search afterwards.
    """
    delegated = await _sandbox("use_environment_raw", environment)
    if delegated is not None:
        return delegated
    return await _run("environment", "use", environment, api_key=api_key)


async def auth_status(*, api_key: str | None = None) -> AtlasEnvelope:
    return await _run("auth", "status", api_key=api_key)


async def auth_login(*, api_key: str | None = None) -> AtlasEnvelope:
    """Begin browser authorisation; the envelope carries the URL to open."""
    return await _run("auth", "login", api_key=api_key)


async def auth_poll(*, api_key: str | None = None) -> AtlasEnvelope:
    """Poll a pending authorisation (bounded by the CLI)."""
    return await _run("auth", "poll", api_key=api_key)


async def doctor(*, api_key: str | None = None) -> AtlasEnvelope:
    """The CLI's own self-check — used by the vault probe."""
    delegated = await _sandbox("doctor_raw")
    if delegated is not None:
        return delegated
    return await _run("doctor", api_key=api_key)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


async def search(
    origin: str,
    destination: str,
    depart_date: str,
    *,
    return_date: str | None = None,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    airlines: tuple[str, ...] = (),
    currency: str | None = None,
    multiple_fare_families: bool = False,
    api_key: str | None = None,
) -> AtlasEnvelope:
    """Live flight search against the **global** inventory (never pre-filtered)."""
    delegated = await _sandbox(
        "search_raw",
        origin,
        destination,
        depart_date,
        return_date=return_date,
        adults=adults,
        children=children,
        infants=infants,
        airlines=airlines,
        currency=currency,
        multiple_fare_families=multiple_fare_families,
    )
    if delegated is not None:
        return delegated
    args = [
        "search",
        "--origin",
        origin,
        "--destination",
        destination,
        "--depart",
        depart_date,
        "--adults",
        str(max(1, adults)),
    ]
    if return_date:
        args += ["--return-date", return_date]
    if children:
        args += ["--children", str(children)]
    if infants:
        args += ["--infants", str(infants)]
    for airline in airlines:
        args += ["--airline", airline]
    if currency:
        args += ["--currency", currency]
    if multiple_fare_families:
        args.append("--multiple-fare-families")
    return await _run(*args, api_key=api_key)


async def list_offers(search_id: str, *, api_key: str | None = None) -> AtlasEnvelope:
    return await _run("offer", "list", "--search-id", search_id, api_key=api_key)


async def verify_offer(offer_id: str, *, deep: bool = False, api_key: str | None = None) -> AtlasEnvelope:
    """Re-price an offer. Never surface a price that hasn't passed through here.

    `deep=True` runs the **real** sandbox `verify.do` (used at booking time, and
    it stashes the upstream sessionId for order.do). The default is the fast
    search-time confirm the flight agent runs across the whole result list.
    """
    delegated = await _sandbox("verify_deep_raw" if deep else "verify_raw", offer_id)
    if delegated is not None:
        return delegated
    return await _run("offer", "verify", "--offer-id", offer_id, api_key=api_key)


async def confirm_price(booking_id: str, *, api_key: str | None = None) -> AtlasEnvelope:
    """Accept a verified price. Required again after any PRICE_CHANGED."""
    delegated = await _sandbox("confirm_price_raw", booking_id)
    if delegated is not None:
        return delegated
    return await _run("booking", "confirm-price", "--booking-id", booking_id, api_key=api_key)


# --------------------------------------------------------------------------- #
# Ancillaries
# --------------------------------------------------------------------------- #


async def list_baggage(booking_id: str, *, api_key: str | None = None) -> AtlasEnvelope:
    delegated = await _sandbox("baggage_raw", booking_id)
    if delegated is not None:
        return delegated
    return await _run("baggage", "list", "--booking-id", booking_id, api_key=api_key)


async def list_seats(booking_id: str, *, api_key: str | None = None) -> AtlasEnvelope:
    delegated = await _sandbox("seat_raw", booking_id)
    if delegated is not None:
        return delegated
    return await _run("seat", "list", "--booking-id", booking_id, api_key=api_key)


# --------------------------------------------------------------------------- #
# Order → pay → ticket
# --------------------------------------------------------------------------- #


async def create_order(
    booking_id: str,
    passengers: list[dict[str, Any]],
    *,
    seat_policy: str | None = None,
    api_key: str | None = None,
) -> AtlasEnvelope:
    """Create an order, passing passengers through stdin.

    stdin (not a file) is deliberate: the CLI documents passenger details as
    one-time input excluded from persisted state, and writing them to disk would
    defeat that.
    """
    delegated = await _sandbox("order_raw", booking_id, passengers, seat_policy=seat_policy)
    if delegated is not None:
        return delegated
    args = ["order", "create", "--booking-id", booking_id, "--passengers-stdin"]
    if seat_policy:
        args += ["--seat-policy", seat_policy]
    payload = json.dumps({"passengers": passengers})
    return await _run(*args, stdin_payload=payload, api_key=api_key)


async def pay_order(confirmation_id: str, *, api_key: str | None = None) -> AtlasEnvelope:
    """Pay from the Atlas balance.

    The confirmation ID is **single-use**. An uncertain payment is never retried
    automatically — `order_status` is the way to find out what happened.
    """
    delegated = await _sandbox("pay_raw", confirmation_id)
    if delegated is not None:
        return delegated
    return await _run("order", "pay", "--confirmation-id", confirmation_id, api_key=api_key)


async def order_status(order_no: str, *, api_key: str | None = None) -> AtlasEnvelope:
    """Poll ticketing (up to 120s upstream), or query an order later."""
    delegated = await _sandbox("status_raw", order_no)
    if delegated is not None:
        return delegated
    return await _run(
        "order",
        "status",
        "--order-no",
        order_no,
        api_key=api_key,
        timeout=TICKETING_TIMEOUT_SECONDS,
    )


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #


async def available(*, api_key: str | None = None) -> bool:
    """True when sandbox creds are stored, or the CLI reports a usable session."""
    if await sandbox_enabled():
        return True
    try:
        envelope = await doctor(api_key=api_key)
    except AtlasSkillError as exc:
        logger.info("Atlas skill unavailable: %s", exc)
        return False
    return envelope.ok or envelope.code == "DOCTOR_OK"


async def status_report(*, api_key: str | None = None) -> dict[str, Any]:
    """Structured health for the UI: installed? authorised? which environment?"""
    try:
        envelope = await doctor(api_key=api_key)
    except AtlasSkillError as exc:
        return {
            "installed": False,
            "authorised": False,
            "environment": None,
            "detail": str(exc),
        }
    return {
        # In sandbox (AK/SK) mode there is no CLI to install — the direct HTTP
        # client is always "installed" and authorised as soon as keys are stored.
        "installed": True,
        "authorised": not envelope.is_auth_problem,
        "environment": envelope.data.get("environment"),
        "auth_mode": "sandbox_ak_sk" if await sandbox_enabled() else "cli",
        "code": envelope.code,
        "detail": envelope.message,
    }


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def normalize_offers(envelope: AtlasEnvelope) -> list[dict[str, Any]]:
    """Flatten Atlas's normalized offers into Journava's option shape.

    Atlas returns `segments` with carriers, times and durations, plus a
    `price_status` of reference/current/verified. That last field maps directly
    onto whether we may present the price as fact.
    """
    offers = envelope.data.get("offers") or []
    normalized: list[dict[str, Any]] = []

    # Sandbox offers wear a distinct provider label so the result badge reads
    # "Atlas Sandbox" — the honest signal that this is the test environment.
    environment = envelope.data.get("environment")
    provider_label = "Atlas Sandbox" if environment == "sandbox" else "Atlas Flight Booking"

    for index, offer in enumerate(offers):
        segments = offer.get("segments") or []
        outbound = [s for s in segments if s.get("direction", "outbound") == "outbound"]
        legs = outbound or segments
        if not legs:
            continue

        first, last = legs[0], legs[-1]
        stops = max(0, len(legs) - 1)
        duration_minutes = sum(int(s.get("duration_minutes") or 0) for s in legs)
        carriers = sorted({s.get("carrier", "") for s in legs if s.get("carrier")})
        flight_numbers = [
            f"{s.get('carrier', '')}{s.get('flight_number', '')}".strip() for s in legs
        ]
        price_status = offer.get("price_status", "reference")

        normalized.append(
            {
                "id": offer.get("offer_id") or f"ATLAS{index + 1:03d}",
                "title": (
                    f"{'/'.join(carriers) or 'Atlas'} "
                    f"{first.get('departure_airport', '')}→{last.get('arrival_airport', '')}"
                    f" · {'direct' if stops == 0 else f'{stops} stop'}"
                ),
                "price_amount": offer.get("total_price"),
                "price_currency": offer.get("currency", "MYR"),
                "provider": provider_label,
                "source": "atlas",
                "reasoning": _offer_reasoning(offer, stops, duration_minutes),
                # Only Atlas's own "verified" price status earns the badge.
                "verified": price_status == "verified",
                "bookable": bool(offer.get("bookable")),
                "raw": {
                    "source": "atlas",
                    "environment": environment,
                    "offer_id": offer.get("offer_id"),
                    "search_id": envelope.data.get("search_id"),
                    "stops": stops,
                    "duration_hours": round(duration_minutes / 60, 1),
                    "departure_time": first.get("departure_time"),
                    "arrival_time": last.get("arrival_time"),
                    "carriers": carriers,
                    "flight_numbers": flight_numbers,
                    "price_status": price_status,
                    "expire_time": offer.get("expire_time"),
                    "transaction_fee_total": offer.get("transaction_fee_total"),
                    "ancillary_supported": offer.get("ancillary_supported") or [],
                    "segments": legs,
                    "baggage_included": "baggage" in (offer.get("ancillary_supported") or []),
                },
            }
        )
    return normalized


def _offer_reasoning(offer: dict[str, Any], stops: int, minutes: int) -> str:
    hours = round(minutes / 60, 1)
    shape = "Direct" if stops == 0 else f"{stops} stop"
    status = {
        "verified": "price re-confirmed by Atlas",
        "current": "current fare",
        "reference": "reference fare — verify before booking",
    }.get(str(offer.get("price_status")), "fare status unknown")
    return f"{shape}, {hours}h total · {status}"
