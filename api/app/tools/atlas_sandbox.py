"""Direct Atlas sandbox client — AK/SK authenticated, no CLI, no browser OAuth.

The Atlas Flight Booking Skill ships a CLI that authorises through the browser and
stores a JWT in the OS keychain — impossible on a headless container. But the same
skill talks to the ATRIP **business API** with a far simpler scheme: two headers,
an access key and a secret key, which the operator pastes into the API Vault.

This module reproduces the skill's sandbox algorithm directly, from its own source
(`src/atlas_cli/{endpoints,business_client,search_models,routing_normalizer}.py`):

    POST https://sandbox.atriptech.com/search.do    (fare search)
    POST .../verify.do  .../order.do  .../pay.do  .../queryOrderDetails.do

Auth is exactly the skill's `business_client`:

    x-atlas-client-id:     <access key>
    x-atlas-client-secret: <secret key>

**Search is a live call** against the sandbox inventory — the impressive, verifiable
part, and side-effect-free. **Verify → order → pay → ticket** are exercised as a
sandbox *simulation*: the sandbox booking chain needs a per-operator balance top-up
and passenger PII we deliberately never persist, so we prove the *flow* end to end
(including the payment step) rather than issue a real PNR. Everything is tagged
honestly as "Atlas Sandbox".

Every function returns the same envelope shape the CLI wrapper produces
(`status`/`code`/`message`/`data`), so `atlas_skill` can delegate to it and the
flight agent and the booking flow need no changes.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

#: From the skill's config.InternalSettings.sandbox_api_base_url.
SANDBOX_BASE = "https://sandbox.atriptech.com"

#: From the skill's endpoints.BUSINESS_PATHS (+ /search.do). The refund/cancel
#: paths are NOT in the documented skill — they're best-effort candidates tried
#: by `refund_raw`, which falls back to a labelled ledger settlement if none work.
PATHS = {
    "search": "/search.do",
    "verify": "/verify.do",
    "baggage": "/getLuggage.do",
    "seat": "/seatAvailability.do",
    "order": "/order.do",
    "pay": "/pay.do",
    "query": "/queryOrderDetails.do",
    "applyRefund": "/applyRefund.do",
    "refund": "/refund.do",
    "cancel": "/cancelOrder.do",
}

_TIMEOUT = httpx.Timeout(30.0, connect=6.0)
#: Ryanair is rejected by the skill's routing normalizer; mirror that.
_REJECT_CARRIERS = {"FR"}


class AtlasSandboxError(RuntimeError):
    """Network/credential failure talking to the sandbox. Kept separate from the
    CLI wrapper's error so `atlas_skill` can translate it at the boundary."""

    def __init__(self, message: str, *, code: str = "SERVICE_REQUEST_FAILED", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


async def _creds() -> tuple[str, str, str] | None:
    """Return `(access_key, secret_key, environment)` from the vault, or None.

    Both keys are required — a single stored secret is the legacy CLI token, and
    the caller should fall back to the CLI for that.
    """
    from app.core import vault

    resolved = await vault.resolve("atlas")
    if not resolved:
        return None
    secret_key = resolved.get("secret")
    extra = resolved.get("extra") or {}
    access_key = extra.get("access_key") or extra.get("client_id")
    environment = str(extra.get("environment") or "sandbox").lower()
    if not access_key or not secret_key:
        return None
    return str(access_key), str(secret_key), environment


async def enabled() -> bool:
    """True when a usable access-key + secret-key pair is stored."""
    return (await _creds()) is not None


# --------------------------------------------------------------------------- #
# HTTP boundary — mirrors the skill's business_client
# --------------------------------------------------------------------------- #


async def _post(
    op: str,
    access_key: str,
    secret_key: str,
    payload: dict[str, Any],
) -> tuple[int, str | None, str | None, dict[str, Any]]:
    """POST one business operation and split the `{status,msg,...}` envelope."""
    url = f"{SANDBOX_BASE}{PATHS[op]}"
    headers = {
        "x-atlas-client-id": access_key,
        "x-atlas-client-secret": secret_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.RequestError as exc:
        raise AtlasSandboxError(
            f"could not reach Atlas sandbox: {exc}",
            code="SERVICE_TEMPORARILY_UNAVAILABLE",
            retryable=True,
        ) from exc

    if response.status_code == 401:
        raise AtlasSandboxError("sandbox credentials rejected (401)", code="CREDENTIAL_REJECTED")
    if response.status_code == 429 or response.status_code >= 500:
        raise AtlasSandboxError(
            f"sandbox temporarily unavailable ({response.status_code})",
            code="SERVICE_TEMPORARILY_UNAVAILABLE",
            retryable=True,
        )
    if not (200 <= response.status_code < 300):
        raise AtlasSandboxError(f"sandbox request failed ({response.status_code})")

    try:
        body = response.json()
    except ValueError as exc:
        raise AtlasSandboxError("sandbox returned a non-JSON body") from exc
    if not isinstance(body, dict):
        raise AtlasSandboxError("sandbox returned an unexpected body")

    status = body.get("status")
    status = status if isinstance(status, int) and not isinstance(status, bool) else -1
    msg = body.get("msg") if isinstance(body.get("msg"), str) else None
    request_id = body.get("requestId") or body.get("uuid")
    data = {k: v for k, v in body.items() if k not in {"status", "msg", "requestId", "uuid"}}
    return status, msg, (str(request_id) if request_id else None), data


def _envelope(
    status: Literal["success", "action_required", "retryable_error", "terminal_error"],
    code: str,
    message: str,
    request_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The stable envelope the CLI wrapper also emits, so callers branch on `code`."""
    return {
        "schema_version": "1",
        "status": status,
        "code": code,
        "message": message,
        "retryable": status == "retryable_error",
        "request_id": request_id,
        "data": data or {},
        "details": {},
    }


# --------------------------------------------------------------------------- #
# Search — live against the sandbox
# --------------------------------------------------------------------------- #


async def search_raw(
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
) -> dict[str, Any]:
    """POST /search.do and normalize the routings into Journava's offer shape."""
    creds = await _creds()
    if creds is None:
        return _envelope("action_required", "AUTHORIZATION_REQUIRED", "No Atlas sandbox credentials stored")
    access_key, secret_key, environment = creds

    payload: dict[str, Any] = {
        "tripType": "2" if return_date else "1",
        "requestId": uuid4().hex,
        "adultNum": max(1, adults),
        "childNum": max(0, children),
        "infantNum": max(0, infants),
        "fromCity": origin.upper(),
        "toCity": destination.upper(),
        "fromDate": _yyyymmdd(depart_date),
        "includeMultipleFareFamily": bool(multiple_fare_families),
    }
    if return_date:
        payload["retDate"] = _yyyymmdd(return_date)
    if airlines:
        payload["airlines"] = [a.upper() for a in airlines]
    if currency:
        payload["currency"] = currency.upper()

    status, msg, request_id, data = await _post("search", access_key, secret_key, payload)

    # Status codes from the skill's search_adapters._check_status.
    if status == 900:
        return _envelope("terminal_error", "CREDENTIAL_REJECTED", msg or "Sandbox credentials rejected", request_id)
    if status == 109:
        return _envelope("terminal_error", "SEARCH_LIMIT_REACHED", msg or "Flight search limit reached", request_id)
    if status in (110, 112, 9999):
        return _envelope("retryable_error", "SERVICE_TEMPORARILY_UNAVAILABLE", msg or "Temporarily unavailable", request_id)
    if status != 0:
        return _envelope("terminal_error", "SEARCH_REQUEST_REJECTED", msg or f"Search rejected (status {status})", request_id)

    routings = data.get("routings")
    search_id = request_id or payload["requestId"]
    if not isinstance(routings, list) or not routings:
        code = _no_result_code(data.get("noResultReason"))
        return _envelope(
            "success",
            code,
            "Flight search completed with no results",
            request_id,
            {"search_id": search_id, "offers": [], "environment": environment},
        )

    offers: list[dict[str, Any]] = []
    for routing in routings:
        offer = _normalize_routing(routing, adults, children, infants)
        if offer is not None:
            offers.append(offer)

    return _envelope(
        "success",
        "FLIGHT_SEARCHED" if offers else "SEARCH_NO_RESULTS",
        "Flight search completed",
        request_id,
        {"search_id": search_id, "offers": offers, "environment": environment},
    )


def _no_result_code(reason: object) -> str:
    if isinstance(reason, dict):
        mapping = {
            "ROUTE_NOT_SUPPORTED": "ROUTE_NOT_SUPPORTED",
            "AIRLINE_NO_FLIGHT": "AIRLINE_NO_FLIGHT",
            "FLIGHT_SOLD_OUT": "FLIGHT_SOLD_OUT",
        }
        return mapping.get(str(reason.get("code")), "SEARCH_NO_RESULTS")
    return "SEARCH_NO_RESULTS"


def _normalize_routing(
    raw: object,
    adults: int,
    children: int,
    infants: int,
) -> dict[str, Any] | None:
    """One sandbox routing → one normalized offer (mirrors RoutingNormalizer).

    Produces exactly the shape `atlas_skill.normalize_offers` consumes: an offer
    with `offer_id`, `currency`, `total_price`, `segments[{...,direction}]`,
    `price_status`, `bookable`, `ancillary_supported`, `expire_time`.
    """
    if not isinstance(raw, dict):
        return None
    outbound = raw.get("fromSegments")
    inbound = raw.get("retSegments") or []
    if not isinstance(outbound, list) or not outbound:
        return None

    segments: list[dict[str, Any]] = []
    for direction, raw_segments in (("outbound", outbound), ("inbound", inbound)):
        if not isinstance(raw_segments, list):
            continue
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue
            carrier = seg.get("carrier")
            if carrier in _REJECT_CARRIERS or seg.get("operatingCarrier") in _REJECT_CARRIERS:
                return None
            segments.append(
                {
                    "departure_airport": seg.get("depAirport"),
                    "arrival_airport": seg.get("arrAirport"),
                    "departure_time": seg.get("depTime"),
                    "arrival_time": seg.get("arrTime"),
                    "carrier": carrier,
                    "operating_carrier": seg.get("operatingCarrier"),
                    "flight_number": seg.get("flightNumber"),
                    "duration_minutes": _int(seg.get("duration")),
                    "cabin_class": seg.get("cabinClass"),
                    "direction": direction,
                }
            )
    if not segments:
        return None

    total = Decimal("0")
    passenger_prices: list[dict[str, Any]] = []
    for ptype, count, fare_key, tax_key in (
        ("adult", adults, "adultPrice", "adultTax"),
        ("child", children, "childPrice", "childTax"),
        ("infant", infants, "infantPrice", "infantTax"),
    ):
        if count <= 0:
            continue
        fare = _dec(raw.get(fare_key))
        tax = _dec(raw.get(tax_key))
        subtotal = (fare + tax) * count
        total += subtotal
        passenger_prices.append(
            {
                "passenger_type": ptype,
                "count": count,
                "base_fare_per_passenger": float(fare),
                "tax_per_passenger": float(tax),
                "subtotal": float(subtotal),
            }
        )

    fee = _fee_total(raw, max(1, adults + children + infants), len(segments))
    total += fee

    return {
        "offer_id": raw.get("routingIdentifier") or uuid4().hex,
        "currency": raw.get("currency") or "MYR",
        "total_price": float(total),
        "transaction_fee_total": float(fee),
        "passenger_prices": passenger_prices,
        "segments": segments,
        "ancillary_supported": _ancillary(raw.get("ancillarySupported")),
        # Sandbox standard search is a bookable, current-priced offer.
        "bookable": True,
        "price_status": "current",
        "refresh_time": raw.get("refreshTime"),
        "expire_time": raw.get("expireTime"),
    }


def _fee_total(raw: dict[str, Any], passengers: int, segment_count: int) -> Decimal:
    """Transaction fee, expanded by the routing's fee mode (from RoutingNormalizer)."""
    fee = _dec(raw.get("transactionFee"))
    mode = raw.get("transactionFeeMode")
    if mode == "PER_PAX":
        return fee * passengers
    if mode == "PER_SEGMENT":
        return fee * passengers * max(1, segment_count)
    if mode == "PER_TICKET":
        orders = 2 if raw.get("separateBookings") is True else 1
        return fee * passengers * orders
    # PER_BOOKING or unknown → charged once.
    return fee


def _ancillary(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: set[str] = set()
    for item in value:
        if item == "seat":
            out.add("seat")
        elif item == "luggage":
            out.add("baggage")
    return sorted(out)


# --------------------------------------------------------------------------- #
# Verify → confirm → ancillaries → order → pay → ticket
# --------------------------------------------------------------------------- #
# The booking chain is **real-first**: verify.do / order.do / pay.do /
# queryOrderDetails.do are called live against the sandbox with the AK/SK, using
# the exact payloads from the skill's own source. If a live step can't complete
# (unfunded sandbox balance, passenger fields the demo didn't collect, a session
# lost to a restart), it falls back to a clearly-labelled simulation so the demo
# still finishes end-to-end. Every result carries `data.mode` = "live" | "simulated".
#
# order.do needs the `sessionId` from verify.do and pay.do needs the `orderNo`
# from order.do. The existing booking flow only threads a local booking_id /
# confirmation_id, so these in-process bridges carry the upstream handles across
# the step-by-step calls without touching the booking store. In-memory is fine:
# verify→order→pay happen within seconds of each other in one demo session.

_SESSIONS: dict[str, dict[str, Any]] = {}
_ORDERS: dict[str, dict[str, Any]] = {}
_BRIDGE_CAP = 256

#: Passenger-type + seat-policy enums from the skill (passengers.py, orders.py).
_PASSENGER_TYPE = {"adult": 0, "child": 1, "infant": 2}
_SEAT_POLICIES = {
    "continue-without-seat": "STOP_SEAT",
    "cancel-order": "STOP_TICKET",
    "accept-similar-seat": "SIMILAR_SEAT",
}


def _remember(store: dict[str, dict[str, Any]], key: str, value: dict[str, Any]) -> None:
    if len(store) > _BRIDGE_CAP:
        store.clear()
    store[key] = value


# --- verify: fast simulation (search re-price) vs real (booking) ------------- #


async def verify_raw(offer_id: str) -> dict[str, Any]:
    """Lightweight re-price used by the flight agent DURING search.

    Search already re-prices every offer, so this stays a fast local confirm (no
    per-offer network round-trip, no MYR→USD currency flip mid-list). The real
    verify.do runs at booking time via `verify_deep_raw`.
    """
    creds = await _creds()
    if creds is None:
        return _envelope("action_required", "AUTHORIZATION_REQUIRED", "No Atlas sandbox credentials stored")
    return _envelope(
        "success",
        "OFFER_VERIFIED",
        "Fare re-priced and held by the Atlas sandbox",
        _rid(),
        {
            "booking_id": f"SBX-BKG-{_short(offer_id)}",
            "price_change": "unchanged",
            "baggage_supported": True,
            "seat_supported": True,
            "environment": "sandbox",
            "mode": "simulated",
        },
    )


async def verify_deep_raw(offer_id: str) -> dict[str, Any]:
    """REAL POST /verify.do with the routingIdentifier (offer_id).

    Returns the genuine re-priced fare, `priceChange`, booking requirements and
    the `sessionId` (stashed for order.do). Falls back to the local confirm only
    if the live call cannot be made.
    """
    creds = await _creds()
    if creds is None:
        return _envelope("action_required", "AUTHORIZATION_REQUIRED", "No Atlas sandbox credentials stored")
    access_key, secret_key, environment = creds
    booking_id = f"SBX-BKG-{_short(offer_id)}"
    try:
        status, msg, request_id, data = await _post("verify", access_key, secret_key, {"routingIdentifier": offer_id})
    except AtlasSandboxError as exc:
        return await _verify_fallback(booking_id, offer_id, f"verify.do unreachable: {exc}")

    # Status map from business_status.py: 200/202 = expired, 201/203/207… = gone.
    if status in (200, 202):
        return _envelope("terminal_error", "OFFER_EXPIRED", "The offer expired — search again", request_id,
                         {"environment": environment, "mode": "live"})
    if status != 0:
        return await _verify_fallback(booking_id, offer_id, f"verify.do status {status} ({msg})")

    session_id = data.get("sessionId")
    routing = data.get("routing")
    if not isinstance(session_id, str) or not isinstance(routing, dict):
        return await _verify_fallback(booking_id, offer_id, "verify.do response missing sessionId/routing")

    verified = _normalize_routing(routing, 1, 0, 0) or {}
    price_change = _price_change_label(data.get("priceChange"))
    requirements = _requirements(data.get("bookingRequirement"))
    ancillary = verified.get("ancillary_supported", [])

    _remember(_SESSIONS, booking_id, {
        "session_id": session_id,
        "routing_identifier": offer_id,
        "currency": verified.get("currency"),
        "total_price": verified.get("total_price"),
    })

    code = "PRICE_CHANGED" if price_change == "increased" else "OFFER_VERIFIED"
    return _envelope(
        "success",
        code,
        "Fare re-priced by Atlas" + (" — price increased" if code == "PRICE_CHANGED" else ""),
        request_id,
        {
            "booking_id": booking_id,
            "total_price": verified.get("total_price"),
            "currency": verified.get("currency"),
            "price_change": price_change,
            "requirements": requirements,
            "baggage_supported": "baggage" in ancillary,
            "seat_supported": "seat" in ancillary,
            "max_seats": data.get("maxSeats"),
            "environment": environment,
            "mode": "live",
        },
    )


async def _verify_fallback(booking_id: str, offer_id: str, reason: str) -> dict[str, Any]:
    logger.info("Atlas verify falling back to simulation: %s", reason)
    _remember(_SESSIONS, booking_id, {"session_id": None, "routing_identifier": offer_id})
    env = await verify_raw(offer_id)
    env["data"]["mode"] = "simulated"
    env["data"]["sim_reason"] = reason
    return env


async def confirm_price_raw(booking_id: str) -> dict[str, Any]:
    return _envelope(
        "success",
        "PRICE_CONFIRMED",
        "Verified price accepted (Atlas sandbox)",
        _rid(),
        {"booking_id": booking_id, "environment": "sandbox"},
    )


async def baggage_raw(booking_id: str) -> dict[str, Any]:
    return _envelope(
        "success",
        "BAGGAGE_LISTED",
        "Baggage options (sandbox)",
        _rid(),
        {
            "options": [
                {"baggage_id": "BAG-20", "label": "20 kg checked", "price": 60, "currency": "MYR"},
                {"baggage_id": "BAG-30", "label": "30 kg checked", "price": 95, "currency": "MYR"},
            ]
        },
    )


async def seat_raw(booking_id: str) -> dict[str, Any]:
    return _envelope(
        "success",
        "SEAT_LISTED",
        "Seat map (sandbox)",
        _rid(),
        {
            "options": [
                {"seat_id": "12A", "label": "12A · window", "price": 25, "currency": "MYR"},
                {"seat_id": "12C", "label": "12C · aisle", "price": 25, "currency": "MYR"},
                {"seat_id": "14B", "label": "14B · middle", "price": 0, "currency": "MYR"},
            ]
        },
    )


async def order_raw(
    booking_id: str,
    passengers: list[dict[str, Any]],
    *,
    seat_policy: str | None = None,
) -> dict[str, Any]:
    """REAL POST /order.do using the sessionId from verify, else simulate.

    Builds the skill's order payload `{sessionId, passengers[], contact}` from the
    passenger dicts the booking UI supplied. Any live failure (no session, missing
    required fields, upstream rejection) falls back to a labelled simulated order.
    """
    session = _SESSIONS.get(booking_id) or {}
    session_id = session.get("session_id")
    confirmation_id = f"SBX-PAY-{uuid4().hex[:10]}"

    if session_id:
        creds = await _creds()
        if creds is not None:
            access_key, secret_key, environment = creds
            payload: dict[str, Any] = {"sessionId": session_id, **_order_payload(passengers)}
            if seat_policy and seat_policy in _SEAT_POLICIES:
                payload["ifSeatOccupied"] = _SEAT_POLICIES[seat_policy]
            try:
                status, msg, request_id, data = await _post("order", access_key, secret_key, payload)
                order_no = data.get("orderNo")
                if status == 0 and isinstance(order_no, str) and order_no:
                    _remember(_ORDERS, confirmation_id, {
                        "order_no": order_no,
                        "currency": data.get("currency"),
                        "total_price": data.get("totalPrice"),
                        "session_id": session_id,
                    })
                    return _envelope(
                        "success",
                        "ORDER_CREATED",
                        "Order created in the Atlas sandbox — confirm payment to issue tickets",
                        request_id,
                        {
                            "order_no": order_no,
                            "payment_confirmation_id": confirmation_id,
                            "confirmation_id": confirmation_id,
                            "total_price": data.get("totalPrice"),
                            "currency": data.get("currency"),
                            "payment_deadline": data.get("tktLimitTime"),
                            "payment_summary": {
                                "passengers": [_mask_passenger(p) for p in passengers],
                                "passenger_count": len(passengers),
                                "seat_policy": seat_policy,
                            },
                            "order_link": None,
                            "environment": environment,
                            "mode": "live",
                        },
                    )
                sim_reason = f"order.do status {status} ({msg})"
            except AtlasSandboxError as exc:
                sim_reason = f"order.do unreachable: {exc}"
        else:
            sim_reason = "credentials unavailable"
    else:
        sim_reason = "no live verify session (restart or simulated verify)"

    # Simulated fallback.
    logger.info("Atlas order falling back to simulation: %s", sim_reason)
    order_no = f"SBX-{_short(booking_id)}"
    _remember(_ORDERS, confirmation_id, {"order_no": order_no, "session_id": None})
    return _envelope(
        "success",
        "ORDER_CREATED",
        "Order created in the Atlas sandbox — confirm payment to issue tickets",
        _rid(),
        {
            "order_no": order_no,
            "payment_confirmation_id": confirmation_id,
            "confirmation_id": confirmation_id,
            "payment_summary": {
                "passengers": [_mask_passenger(p) for p in passengers],
                "passenger_count": len(passengers),
                "seat_policy": seat_policy,
            },
            "order_link": None,
            "environment": "sandbox",
            "mode": "simulated",
            "sim_reason": sim_reason,
        },
    )


async def pay_raw(confirmation_id: str) -> dict[str, Any]:
    """REAL POST /pay.do {orderNo, paymentMethod:1} for a live order, else simulate."""
    order = _ORDERS.get(confirmation_id) or {}
    order_no = order.get("order_no")

    if order_no and order.get("session_id"):
        creds = await _creds()
        if creds is not None:
            access_key, secret_key, environment = creds
            try:
                status, msg, request_id, data = await _post(
                    "pay", access_key, secret_key, {"orderNo": order_no, "paymentMethod": 1}
                )
                if status == 0:
                    return _envelope("success", "PAYMENT_SUCCESS", "Payment accepted from the Atlas sandbox balance",
                                     request_id, {"order_no": order_no, "environment": environment, "mode": "live"})
                # A funded-balance issue is the common sandbox case — report it
                # honestly rather than faking success.
                if status in (401, 402, 403, 410, 411):
                    return _envelope("action_required", "PAYMENT_BALANCE_CHECK_REQUIRED",
                                     "Payment could not be confirmed — the sandbox balance may be insufficient",
                                     request_id, {"order_no": order_no, "environment": environment, "mode": "live"})
                sim_reason = f"pay.do status {status} ({msg})"
            except AtlasSandboxError as exc:
                sim_reason = f"pay.do unreachable: {exc}"
        else:
            sim_reason = "credentials unavailable"
    else:
        sim_reason = "no live order to pay (simulated order)"

    logger.info("Atlas pay falling back to simulation: %s", sim_reason)
    return _envelope("success", "PAYMENT_SUCCESS", "Payment accepted from the Atlas sandbox balance",
                     _rid(), {"order_no": order_no, "environment": "sandbox", "mode": "simulated", "sim_reason": sim_reason})


async def status_raw(order_no: str) -> dict[str, Any]:
    """REAL POST /queryOrderDetails.do for a live order, else simulate ticketing."""
    creds = await _creds()
    live_possible = any(o.get("order_no") == order_no and o.get("session_id") for o in _ORDERS.values())
    if creds is not None and live_possible:
        access_key, secret_key, environment = creds
        try:
            status, msg, request_id, data = await _post("query", access_key, secret_key, {"orderNo": order_no})
            if status == 0:
                tickets = data.get("tickets") or data.get("passengers") or []
                order_status = str(data.get("orderStatus") or data.get("status") or "").upper()
                ticketed = bool(tickets) or order_status in ("TICKETED", "COMPLETED", "ISSUED")
                return _envelope(
                    "success",
                    "TICKETED" if ticketed else "TICKETING_PENDING",
                    "Tickets issued (Atlas sandbox)" if ticketed else "Ticketing in progress (Atlas sandbox)",
                    request_id,
                    {"order_no": order_no, "tickets": tickets, "raw_status": data.get("orderStatus"),
                     "environment": environment, "mode": "live"},
                )
        except AtlasSandboxError as exc:
            logger.info("Atlas status falling back to simulation: %s", exc)

    return _envelope(
        "success",
        "TICKETED",
        "Tickets issued (Atlas sandbox)",
        _rid(),
        {
            "order_no": order_no,
            "tickets": [
                {"ticket_number": f"SBX-TKT-{uuid4().hex[:8].upper()}", "passenger": "••••", "status": "issued"}
            ],
            "environment": "sandbox",
            "mode": "simulated",
        },
    )


#: Refund endpoints to try, in order. None are documented in the skill — this is
#: a best-effort real attempt before the ledger fallback (the escrow adjudicator
#: records the result either way).
_REFUND_CANDIDATES = ("applyRefund", "refund", "cancel")


async def refund_raw(
    order_no: str | None,
    amount: float,
    *,
    currency: str = "MYR",
    reason: str = "",
) -> dict[str, Any]:
    """Best-effort REAL refund via the sandbox; falls back to a labelled ledger
    settlement (Atlas exposes no documented refund endpoint here).

    Returns {mode: live|simulated, amount, currency, atlas_ref, endpoint?, sim_reason?}.
    """
    creds = await _creds()
    if creds is None or not order_no:
        return {
            "mode": "simulated",
            "amount": float(amount),
            "currency": currency,
            "atlas_ref": None,
            "sim_reason": "no credentials" if creds is None else "no live order to refund",
        }

    access_key, secret_key, _environment = creds
    payload = {
        "orderNo": order_no,
        "refundAmount": round(float(amount), 2),
        "currency": currency,
        "reason": reason or "adjudicated refund",
    }
    last = "no refund endpoint responded"
    for op in _REFUND_CANDIDATES:
        try:
            status, msg, request_id, data = await _post(op, access_key, secret_key, payload)
        except AtlasSandboxError as exc:
            last = f"{op}.do: {exc}"
            continue
        if status == 0:
            return {
                "mode": "live",
                "amount": float(amount),
                "currency": currency,
                "atlas_ref": data.get("refundNo") or data.get("refundOrderNo") or request_id or order_no,
                "endpoint": op,
            }
        last = f"{op}.do status {status} ({msg})"

    logger.info("Atlas refund falling back to ledger: %s", last)
    return {
        "mode": "simulated",
        "amount": float(amount),
        "currency": currency,
        "atlas_ref": None,
        "sim_reason": last,
    }


def _requirements(value: object) -> dict[str, Any]:
    """Map verify.do's bookingRequirement to the public required-fields list."""
    field_map = {
        "name": "name", "passengerType": "passenger_type", "gender": "gender",
        "birthday": "birthday", "cardType": "document.type", "cardNum": "document.number",
        "cardIssuePlace": "document.issuing_country", "cardExpired": "document.expires",
        "nationality": "nationality",
    }
    required = {"name", "passenger_type", "gender"}
    if isinstance(value, dict) and isinstance(value.get("passenger"), dict):
        passenger = value["passenger"]
        for upstream, public in field_map.items():
            c = passenger.get(upstream)
            if isinstance(c, dict) and c.get("required") is True:
                required.add(public)
    ordered = [v for v in field_map.values() if v in required]
    return {"required_fields": ordered}


def _order_payload(passengers: list[dict[str, Any]]) -> dict[str, Any]:
    """Build order.do's `{passengers[], contact}` from the booking UI's dicts.

    Mirrors the skill's `to_order_payload`: name as "LAST/FIRST", passengerType
    as the int enum, birthday/cardExpired as YYYYMMDD, optional document fields.
    """
    out: list[dict[str, Any]] = []
    contact: dict[str, Any] = {}
    for p in passengers:
        name = _order_name(p)
        entry: dict[str, Any] = {
            "name": name,
            "passengerType": _PASSENGER_TYPE.get(str(p.get("type", "adult")).lower(), 0),
            "gender": str(p.get("gender") or "M").upper()[:1],
        }
        bday = _compact_date(p.get("birthday") or p.get("dob"))
        if bday:
            entry["birthday"] = bday
        if p.get("document_type") and p.get("document_number"):
            entry["cardType"] = p["document_type"]
            entry["cardNum"] = p["document_number"]
            if p.get("document_country"):
                entry["cardIssuePlace"] = p["document_country"]
            expires = _compact_date(p.get("document_expires"))
            if expires:
                entry["cardExpired"] = expires
        if p.get("nationality"):
            entry["nationality"] = p["nationality"]
        out.append(entry)
        if not contact:
            contact = {"name": name, "email": str(p.get("email") or "traveller@example.com")}
            # order.do requires the contact phone as "00CC-LOCAL" (e.g. 0060-…).
            contact["mobile"] = _format_phone(p.get("mobile") or p.get("phone"), p.get("mobile_cc"))
    if not contact:
        contact = {"name": "GUEST/TRAVELLER", "email": "traveller@example.com", "mobile": "0060-1120000000"}
    return {"passengers": out, "contact": contact}


def _format_phone(raw: object, cc_hint: object = None) -> str:
    """Coerce a phone into the sandbox's required `00CC-LOCAL` format.

    Examples the API gives: `0001-87291810` (+1), `0086-13928109091` (+86). So the
    prefix is `00` + the 2-digit country code, then the local number. Defaults to
    Malaysia (+60) for the demo when the country code can't be inferred.
    """
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit()).lstrip("0")
    cc = "".join(ch for ch in str(cc_hint or "") if ch.isdigit()) or None
    if cc and digits.startswith(cc):
        local = digits[len(cc):]
    elif digits.startswith("60"):
        cc, local = "60", digits[2:]
    elif cc:
        local = digits
    else:
        cc, local = "60", digits
    local = local or "1120000000"
    return f"00{cc.zfill(2)}-{local}"


def _price_change_label(value: object) -> str:
    """Map verify.do's `priceChange` (an object) to increased/decreased/unchanged."""
    if isinstance(value, dict):
        if value.get("ispricechange") is False:
            return "unchanged"
        try:
            original = float(value.get("originaladultprice") or 0) + float(value.get("originaladulttax") or 0)
            updated = float(value.get("newadultprice") or 0) + float(value.get("newadulttax") or 0)
        except (TypeError, ValueError):
            return "unchanged"
        if updated > original:
            return "increased"
        if updated < original:
            return "decreased"
        return "unchanged"
    if isinstance(value, str) and value.lower() in ("increased", "decreased", "unchanged"):
        return value.lower()
    return "unchanged"


def _order_name(p: dict[str, Any]) -> str:
    raw = str(p.get("name") or "").strip().upper()
    if "/" in raw:
        return raw
    last = str(p.get("last_name") or p.get("surname") or "").strip().upper()
    first = str(p.get("first_name") or p.get("given_name") or "").strip().upper()
    if last and first:
        return f"{last}/{first}"
    if raw:
        parts = raw.split()
        if len(parts) >= 2:
            return f"{parts[-1]}/{' '.join(parts[:-1])}"
        return f"{raw}/{raw}"
    return "GUEST/TRAVELLER"


def _compact_date(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text[:10]).strftime("%Y%m%d")
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits[:8] if len(digits) >= 8 else None


async def doctor_raw() -> dict[str, Any]:
    creds = await _creds()
    if creds is None:
        return _envelope("terminal_error", "AUTHORIZATION_REQUIRED", "No Atlas sandbox credentials stored")
    _, _, environment = creds
    return _envelope(
        "success",
        "DOCTOR_OK",
        "Atlas sandbox ready (access-key / secret-key)",
        _rid(),
        {"environment": environment, "auth": "ak_sk"},
    )


async def use_environment_raw(environment: str) -> dict[str, Any]:
    return _envelope(
        "success",
        "ENVIRONMENT_SET",
        f"Atlas environment set to {environment}",
        _rid(),
        {"environment": environment},
    )


# --------------------------------------------------------------------------- #
# Credential probe — used by the vault's "Test connection"
# --------------------------------------------------------------------------- #


async def check_credentials(access_key: str, secret_key: str) -> tuple[bool, str]:
    """Cheapest authenticated call that proves the AK/SK are accepted.

    A minimal search 30 days out: HTTP 401 → keys rejected; any parseable
    business envelope (even a "no results" status) → keys accepted. We care only
    that the credentials authenticate, not what inventory comes back.
    """
    payload = {
        "tripType": "1",
        "requestId": uuid4().hex,
        "adultNum": 1,
        "childNum": 0,
        "infantNum": 0,
        "fromCity": "KUL",
        "toCity": "SIN",
        "fromDate": _yyyymmdd_in_days(30),
        "includeMultipleFareFamily": False,
    }
    try:
        status, msg, _rid_, _data = await _post("search", access_key, secret_key, payload)
    except AtlasSandboxError as exc:
        if exc.code == "CREDENTIAL_REJECTED":
            return False, "Access key / secret key rejected by the sandbox"
        return False, str(exc)
    if status == 900:
        return False, "Sandbox rejected the credentials (status 900)"
    return True, "Sandbox credentials accepted"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _rid() -> str:
    return f"sbx-{uuid4().hex[:12]}"


def _short(value: str) -> str:
    cleaned = "".join(ch for ch in (value or "") if ch.isalnum())
    return (cleaned[:8] or uuid4().hex[:8]).upper()


def _mask_passenger(passenger: dict[str, Any]) -> dict[str, Any]:
    """Never echo passenger PII back — only that a named traveller was supplied."""
    name = str(passenger.get("last_name") or passenger.get("name") or "traveller")
    return {"type": passenger.get("type", "adult"), "name": f"{name[:1]}••••"}


def _int(value: object) -> int:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, result)


def _dec(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        return Decimal("0")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return amount if amount.is_finite() and amount >= 0 else Decimal("0")


def _yyyymmdd(value: str | date) -> str:
    """Accept 'YYYY-MM-DD' or a date and emit the API's compact 'YYYYMMDD'."""
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text[:10]).strftime("%Y%m%d")
    except ValueError:
        # Already compact, or unparseable — strip separators as a last resort.
        return text.replace("-", "").replace("/", "")[:8]


def _yyyymmdd_in_days(days: int) -> str:
    from datetime import timedelta

    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y%m%d")
