"""Atlas booking flow — search → verify → confirm → order → pay → ticket.

Wraps the CLI's state machine into steps the UI can drive one button at a time,
which is what makes the "simulate the purchase" flow honest: each step shows what
Atlas actually returned, and nothing advances on assumption.

    POST /flights/booking/start    offer_id            → draft
    POST /flights/booking/verify   → booking_id          price_confirmed
    POST /flights/booking/order    passengers           → ordered
    POST /flights/booking/pay      confirmation         → paying → paid
    GET  /flights/booking/status   poll ≤120s           → ticketed

Guard rails taken from the Atlas safety boundaries, enforced rather than trusted:

- A **price increase** (`PRICE_CHANGED`) stops the flow and requires the caller to
  confirm again. It is never auto-accepted.
- A **confirmation ID is single-use.** After one payment attempt the stage moves
  to `paying` and further attempts are refused; `status` is how you find out what
  happened.
- **Sandbox is the default.** Production requires an explicit opt-in per call, so
  a demo cannot accidentally spend real money.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.brain import bookings
from app.core import sse, vault
from app.tools import atlas_skill
from app.tools.atlas_skill import AtlasEnvelope, AtlasSkillError

logger = logging.getLogger(__name__)


class BookingFlowError(RuntimeError):
    """A step could not be attempted — carries a UI-safe reason."""

    def __init__(self, message: str, *, code: str = "FLOW_ERROR") -> None:
        super().__init__(message)
        self.code = code


async def _atlas_key() -> str | None:
    return await vault.secret_for("atlas")


def _envelope_summary(envelope: AtlasEnvelope) -> dict[str, Any]:
    """The part of an Atlas response the UI should show verbatim."""
    return {
        "status": envelope.status,
        "code": envelope.code,
        "message": envelope.message,
        "needs_action": envelope.needs_action,
        "retryable": bool(envelope.get("retryable")),
        "request_id": envelope.get("request_id"),
        "details": envelope.details,
    }


async def _emit(stage: str, message: str, **data: Any) -> None:
    sse.publish("flight", "working", message, data={"booking_stage": stage, **data})


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #


async def set_environment(environment: str) -> dict[str, Any]:
    """Switch the CLI between sandbox and production.

    Any offer obtained before the switch expires, so the caller must re-search —
    that is Atlas's rule and it is surfaced in the response rather than hidden.
    """
    if environment not in ("sandbox", "production"):
        raise BookingFlowError("Environment must be 'sandbox' or 'production'")
    try:
        envelope = await atlas_skill.use_environment(
            environment,  # type: ignore[arg-type]
            api_key=await _atlas_key(),
        )
    except AtlasSkillError as exc:
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc

    await vault.upsert_credential(
        "atlas",
        secret=None,  # keep whatever key is stored
        extra={"environment": environment},
        status="healthy" if envelope.ok else "untested",
        status_detail=envelope.message[:200] or None,
    )
    vault.invalidate_cache("atlas")
    return {
        "environment": environment,
        "offers_expired": True,
        "note": "Offers obtained before the switch have expired — search again.",
        **_envelope_summary(envelope),
    }


async def atlas_status() -> dict[str, Any]:
    """Installed? authorised? which environment? — for the UI banner."""
    return await atlas_skill.status_report(api_key=await _atlas_key())


async def begin_authorization() -> dict[str, Any]:
    """Start browser authorisation and hand the URL back to the operator."""
    try:
        envelope = await atlas_skill.auth_login(api_key=await _atlas_key())
    except AtlasSkillError as exc:
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc
    data = envelope.data
    return {
        "authorization_url": data.get("authorization_url") or data.get("url"),
        "expires_in": data.get("expires_in"),
        **_envelope_summary(envelope),
    }


async def poll_authorization() -> dict[str, Any]:
    try:
        envelope = await atlas_skill.auth_poll(api_key=await _atlas_key())
    except AtlasSkillError as exc:
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc
    return {"authorized": envelope.code == "AUTHORIZED", **_envelope_summary(envelope)}


# --------------------------------------------------------------------------- #
# Step 1 — start from a chosen offer
# --------------------------------------------------------------------------- #


async def start(
    *,
    offer_id: str,
    route: str | None = None,
    depart_date: date | None = None,
    travellers: int = 1,
    total_amount: float | None = None,
    currency: str | None = None,
    environment: str = "sandbox",
    trip_id: str | None = None,
    offer_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Open a booking for an offer the traveller picked."""
    record = await bookings.create(
        offer_id=offer_id,
        route=route,
        depart_date=depart_date,
        travellers=travellers,
        total_amount=total_amount,
        currency=currency,
        environment=environment,
        trip_id=trip_id,
        payload={"offer": offer_snapshot or {}, "steps": []},
    )
    sse.publish(
        "flight",
        "working",
        f"Booking started for {route or offer_id} ({environment})",
        data={"booking_stage": "draft", "booking_row_id": record["id"]},
    )
    return record


# --------------------------------------------------------------------------- #
# Step 2 — verify the fare, then confirm the price
# --------------------------------------------------------------------------- #


async def verify(booking_row_id: str, *, accept_price_change: bool = False) -> dict[str, Any]:
    """Re-price the offer and confirm it.

    `offer verify` yields a `booking_id`; `booking confirm-price` accepts the
    verified fare. A `PRICE_CHANGED` result stops here unless the caller has
    explicitly accepted the new price.
    """
    record = await bookings.get_internal(booking_row_id)
    if record is None:
        raise BookingFlowError("Booking not found", code="BOOKING_NOT_FOUND")
    if record["stage"] in bookings.TERMINAL_STAGES:
        raise BookingFlowError(
            f"Booking is already {record['stage']}", code="BOOKING_STATE_INVALID"
        )
    if not record["offer_id"]:
        raise BookingFlowError("Booking has no offer to verify", code="BOOKING_INPUT_INVALID")

    api_key = await _atlas_key()
    await _emit("verifying", "Re-pricing the fare with Atlas")

    try:
        # deep=True → the real sandbox verify.do (re-prices live + opens a session
        # for order.do), not the fast search-time confirm.
        verified = await atlas_skill.verify_offer(record["offer_id"], deep=True, api_key=api_key)
    except AtlasSkillError as exc:
        await bookings.update(
            booking_row_id,
            stage="failed",
            last_code="CLI_UNAVAILABLE",
            last_message=str(exc),
        )
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc

    booking_id = verified.data.get("booking_id")
    new_total = verified.data.get("total_price")
    steps = [{"step": "offer.verify", **_envelope_summary(verified)}]

    if verified.code == "OFFER_EXPIRED":
        await bookings.update(
            booking_row_id,
            stage="failed",
            last_code=verified.code,
            last_message=verified.message,
            payload_patch={"steps": steps},
        )
        raise BookingFlowError(
            "The offer expired — search again for current fares.", code="OFFER_EXPIRED"
        )

    price_changed = verified.code == "PRICE_CHANGED"
    if price_changed and not accept_price_change:
        updated = await bookings.update(
            booking_row_id,
            booking_id=booking_id,
            last_code=verified.code,
            last_message=verified.message,
            total_amount=float(new_total) if new_total is not None else None,
            payload_patch={"steps": steps},
        )
        return {
            **(updated or record),
            "requires_confirmation": True,
            "reason": "price_changed",
            "previous_amount": record.get("total_amount"),
            "new_amount": float(new_total) if new_total is not None else None,
            "atlas": _envelope_summary(verified),
        }

    if not booking_id:
        await bookings.update(
            booking_row_id,
            last_code=verified.code,
            last_message=verified.message,
            payload_patch={"steps": steps},
        )
        raise BookingFlowError(
            f"Atlas did not return a booking id ({verified.code})", code=verified.code
        )

    await _emit("confirming", "Confirming the verified price")
    try:
        confirmed = await atlas_skill.confirm_price(booking_id, api_key=api_key)
    except AtlasSkillError as exc:
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc

    steps.append({"step": "booking.confirm-price", **_envelope_summary(confirmed)})
    stage = "price_confirmed" if confirmed.ok else "draft"
    total = confirmed.data.get("total_price", new_total)

    updated = await bookings.update(
        booking_row_id,
        stage=stage,
        booking_id=booking_id,
        last_code=confirmed.code,
        last_message=confirmed.message,
        total_amount=float(total) if total is not None else None,
        currency=confirmed.data.get("currency"),
        payload_patch={"steps": steps},
    )
    sse.publish(
        "flight",
        "active" if confirmed.ok else "waiting",
        f"Price {'confirmed' if confirmed.ok else confirmed.code}",
        data={"booking_stage": stage},
    )
    return {
        **(updated or {}),
        "requires_confirmation": False,
        "atlas": _envelope_summary(confirmed),
        "ancillaries": await _ancillaries(booking_id, confirmed, api_key),
    }


async def _ancillaries(
    booking_id: str,
    confirmed: AtlasEnvelope,
    api_key: str | None,
) -> dict[str, Any]:
    """Baggage and seat availability. Unavailability never blocks the flow."""
    if not confirmed.ok:
        return {"baggage": [], "seats": [], "note": "Not fetched — price unconfirmed."}
    try:
        baggage = await atlas_skill.list_baggage(booking_id, api_key=api_key)
        seats = await atlas_skill.list_seats(booking_id, api_key=api_key)
    except AtlasSkillError:
        return {"baggage": [], "seats": [], "note": "Ancillary lookup unavailable."}
    return {
        "baggage": baggage.data.get("options") or baggage.data.get("baggage") or [],
        "seats": seats.data.get("options") or seats.data.get("seats") or [],
        "baggage_code": baggage.code,
        "seat_code": seats.code,
    }


# --------------------------------------------------------------------------- #
# Step 3 — create the order
# --------------------------------------------------------------------------- #


async def create_order(
    booking_row_id: str,
    passengers: list[dict[str, Any]],
    *,
    seat_policy: str | None = None,
) -> dict[str, Any]:
    """Create the Atlas order.

    Passenger details go straight to the CLI over stdin and are **not** stored —
    only how many there were.
    """
    record = await bookings.get_internal(booking_row_id)
    if record is None:
        raise BookingFlowError("Booking not found", code="BOOKING_NOT_FOUND")
    if not record.get("booking_id"):
        raise BookingFlowError(
            "Verify the fare before creating an order", code="BOOKING_STATE_INVALID"
        )
    if record["stage"] in bookings.TERMINAL_STAGES:
        raise BookingFlowError(
            f"Booking is already {record['stage']}", code="BOOKING_STATE_INVALID"
        )
    if not passengers:
        raise BookingFlowError("At least one passenger is required", code="PASSENGER_INFO_REQUIRED")

    await _emit("ordering", f"Creating the order for {len(passengers)} passenger(s)")
    try:
        envelope = await atlas_skill.create_order(
            record["booking_id"],
            passengers,
            seat_policy=seat_policy,
            api_key=await _atlas_key(),
        )
    except AtlasSkillError as exc:
        await bookings.update(booking_row_id, last_code="CLI_UNAVAILABLE", last_message=str(exc))
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc

    data = envelope.data
    order_no = data.get("order_no") or data.get("orderNo")
    confirmation_id = data.get("confirmation_id") or data.get("payment_confirmation_id")

    # ORDER_CREATION_UNKNOWN means we must not retry — poll instead.
    if envelope.code == "ORDER_CREATION_UNKNOWN":
        updated = await bookings.update(
            booking_row_id,
            stage="paying",
            order_no=order_no,
            last_code=envelope.code,
            last_message=envelope.message,
        )
        return {
            **(updated or {}),
            "atlas": _envelope_summary(envelope),
            "warning": (
                "Order creation outcome is unknown. Do not retry — check the order status instead."
            ),
        }

    stage = "ordered" if (envelope.ok and order_no) else record["stage"]
    updated = await bookings.update(
        booking_row_id,
        stage=stage,
        order_no=order_no,
        confirmation_id=confirmation_id,
        last_code=envelope.code,
        last_message=envelope.message,
        total_amount=float(data["total_price"]) if data.get("total_price") else None,
        payload_patch={
            "order": {
                "masked_payment_summary": data.get("payment_summary")
                or data.get("masked_payment_summary"),
                "order_link": data.get("order_link") or data.get("atlas_order_url"),
                "passenger_count": len(passengers),
            }
        },
    )
    sse.publish(
        "flight",
        "active" if stage == "ordered" else "waiting",
        f"Order {envelope.code}",
        data={"booking_stage": stage, "order_no": order_no},
    )
    return {
        **(updated or {}),
        "atlas": _envelope_summary(envelope),
        "payment_summary": data.get("payment_summary") or data.get("masked_payment_summary"),
        "order_link": data.get("order_link") or data.get("atlas_order_url"),
        "ready_to_pay": bool(confirmation_id) and stage == "ordered",
    }


# --------------------------------------------------------------------------- #
# Step 4 — pay
# --------------------------------------------------------------------------- #


async def pay(booking_row_id: str) -> dict[str, Any]:
    """Pay from the Atlas balance. One attempt only."""
    record = await bookings.get_internal(booking_row_id)
    if record is None:
        raise BookingFlowError("Booking not found", code="BOOKING_NOT_FOUND")

    confirmation_id = record.get("confirmation_id")
    if not confirmation_id:
        raise BookingFlowError(
            "No payment confirmation available — create the order first",
            code="PAYMENT_CONFIRMATION_REQUIRED",
        )
    if record["stage"] not in bookings.PAYABLE_STAGES:
        # This is the single-use rule. Re-paying could double-charge, so the only
        # way forward from here is to ask Atlas what happened.
        raise BookingFlowError(
            f"Payment cannot be attempted from stage '{record['stage']}'. "
            "Check the order status instead — a confirmation ID is single-use.",
            code="PAYMENT_ALREADY_ATTEMPTED",
        )

    # Move to `paying` *before* calling, so a crash mid-payment cannot look
    # payable again on restart.
    await bookings.update(booking_row_id, stage="paying")
    await _emit("paying", "Submitting payment from the Atlas balance")

    try:
        envelope = await atlas_skill.pay_order(confirmation_id, api_key=await _atlas_key())
    except AtlasSkillError as exc:
        await bookings.update(booking_row_id, last_code="CLI_UNAVAILABLE", last_message=str(exc))
        raise BookingFlowError(
            f"{exc} — payment outcome unknown, check the order status.",
            code="PAYMENT_STATUS_UNKNOWN",
        ) from exc

    if envelope.code in ("PAYMENT_PROCESSING", "PAYMENT_STATUS_UNKNOWN"):
        updated = await bookings.update(
            booking_row_id, last_code=envelope.code, last_message=envelope.message
        )
        return {
            **(updated or {}),
            "atlas": _envelope_summary(envelope),
            "next": "poll_status",
        }

    if envelope.code == "TOP_UP_REQUIRED":
        updated = await bookings.update(
            booking_row_id,
            stage="ordered",
            last_code=envelope.code,
            last_message=envelope.message,
        )
        return {
            **(updated or {}),
            "atlas": _envelope_summary(envelope),
            "next": "top_up",
        }

    stage = "paid" if envelope.ok else "failed"
    updated = await bookings.update(
        booking_row_id, stage=stage, last_code=envelope.code, last_message=envelope.message
    )
    sse.publish(
        "flight",
        "active" if envelope.ok else "error",
        f"Payment {envelope.code}",
        data={"booking_stage": stage},
    )
    return {
        **(updated or {}),
        "atlas": _envelope_summary(envelope),
        "next": "poll_status" if envelope.ok else None,
    }


# --------------------------------------------------------------------------- #
# Step 5 — ticketing
# --------------------------------------------------------------------------- #


async def status(booking_row_id: str) -> dict[str, Any]:
    """Poll ticketing, or query the order later."""
    record = await bookings.get_internal(booking_row_id)
    if record is None:
        raise BookingFlowError("Booking not found", code="BOOKING_NOT_FOUND")
    order_no = record.get("order_no")
    if not order_no:
        raise BookingFlowError("Booking has no order number yet", code="ORDER_NOT_FOUND")

    await _emit("ticketing", "Polling Atlas for ticket issuance")
    try:
        envelope = await atlas_skill.order_status(order_no, api_key=await _atlas_key())
    except AtlasSkillError as exc:
        raise BookingFlowError(str(exc), code="CLI_UNAVAILABLE") from exc

    stage_by_code = {
        "TICKETED": "ticketed",
        "COMPLETED": "ticketed",
        "TICKETING_PENDING": "paid",
        "PENDING": "paid",
        "ORDER_CANCELLED": "failed",
        "EXPIRED": "failed",
        "PAYMENT_DEADLINE_EXPIRED": "failed",
    }
    stage = stage_by_code.get(envelope.code, record["stage"])

    updated = await bookings.update(
        booking_row_id,
        stage=stage,
        last_code=envelope.code,
        last_message=envelope.message,
        payload_patch={"ticketing": envelope.data},
    )
    if stage == "ticketed":
        sse.publish("flight", "active", "Tickets issued", data={"order_no": order_no})
    return {
        **(updated or {}),
        "atlas": _envelope_summary(envelope),
        "tickets": envelope.data.get("tickets") or [],
    }
