"""Automated flight recovery — the "book → detect delay → suggest best →
refund old → book new → report" pipeline, run autonomously.

It composes pieces that already exist rather than reinventing them:

  detect   → tools.flight_status.check_status  (real-first, `force` for demos)
  suggest  → atlas_skill.search + normalize     (fresh inventory, pick best)
  refund   → adjudicator.adjudicate + refund_raw (EU261-style %, real refund)
  rebook   → graph.booking_flow.start→verify→order→pay (the real Atlas chain)
  report   → sse.publish + notify.broadcast + a step-by-step ledger returned

Every step is recorded with its outcome and mode (live/simulated) so the
traveller sees exactly what the agent did on their behalf — nothing happens
silently. `execute=False` stops after "suggest" (preview), so the same pipeline
powers both an autopilot and a confirm-first UX.
"""

from __future__ import annotations

import logging
import re
from datetime import date as _date
from typing import Any

from app.brain import bookings
from app.core import sse
from app.graph import booking_flow
from app.tools import adjudicator, atlas_sandbox, atlas_skill, flight_status, notify

logger = logging.getLogger("journava")

#: Sandbox never issues a ticket to a real person, and passenger PII is
#: deliberately never persisted — so an automated rebook uses a placeholder.
#: A real (production) rebook would collect passengers via the booking dialog.
_SYNTHETIC_PASSENGER: dict[str, Any] = {
    "given_name": "Journava",
    "family_name": "Traveller",
    "date_of_birth": "1990-01-01",
    "gender": "male",
    "nationality": "MY",
    "passport_number": "A1234567",
    "passport_expiry": "2032-01-01",
}


def _as_date(value: Any) -> _date | None:
    if isinstance(value, _date):
        return value
    if isinstance(value, str) and value:
        try:
            return _date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _route_ends(booking: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """(origin, destination, carrier) for the booked flight, best-effort.

    Prefers the stored offer's own segments; falls back to the "AAA → BBB"
    route label so a hand-built record still resolves.
    """
    offer = ((booking.get("payload") or {}).get("offer")) or {}
    raw = offer.get("raw") or {}
    segments = raw.get("segments") or []
    origin = dest = None
    if segments:
        origin = segments[0].get("departure_airport")
        dest = segments[-1].get("arrival_airport")
    carriers = raw.get("carriers") or []
    carrier = carriers[0] if carriers else None
    if not (origin and dest):
        codes = [c.strip()[:3].upper() for c in re.split(r"[^A-Za-z]+", booking.get("route") or "") if c.strip()]
        if len(codes) >= 2:
            origin = origin or codes[0]
            dest = dest or codes[-1]
    return origin, dest, carrier


def _price(offer: dict[str, Any]) -> float:
    try:
        amount = offer.get("price_amount")
        return float(amount) if amount is not None else float("inf")
    except (TypeError, ValueError):
        return float("inf")


async def _find_alternatives(
    origin: str | None,
    dest: str | None,
    depart: _date | None,
    booking: dict[str, Any],
    currency: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Fresh Atlas search for the same route/date, minus the disrupted flight,
    ranked to the best bookable option (cheapest, preferring within ~budget)."""
    if not (origin and dest and depart):
        return [], None
    try:
        env = await atlas_skill.search(
            origin,
            dest,
            depart.isoformat(),
            adults=max(1, int(booking.get("travellers") or 1)),
            currency=currency,
            multiple_fare_families=True,
            api_key=await booking_flow._atlas_key(),
        )
        offers = atlas_skill.normalize_offers(env) if (env.ok and not env.is_empty_result) else []
    except Exception as exc:  # noqa: BLE001
        logger.info("auto_recover: alternative search failed: %s", exc)
        offers = []

    disrupted_id = booking.get("offer_id")
    candidates = [o for o in offers if o.get("id") and o.get("id") != disrupted_id]
    bookable = [o for o in candidates if o.get("bookable")]
    pool = bookable or candidates
    if not pool:
        return candidates, None

    budget = booking.get("total_amount")
    within = [o for o in pool if budget and _price(o) <= float(budget) * 1.2]
    best = min(within or pool, key=_price)
    return candidates, best


async def _refund_old(
    booking: dict[str, Any],
    status: dict[str, Any],
    amount: float,
    currency: str,
) -> dict[str, Any]:
    """Adjudicate a fair refund (EU261-style) and execute it against Atlas, then
    move the old booking to a refunded/cancelled terminal stage."""
    delay = int(status.get("delay_minutes") or 0)
    cancelled = status.get("status") == "cancelled"
    # Use the exact event keywords the adjudicator's EU261 rule baseline matches
    # ("cancelled" -> 100%, "delayed" + minutes -> tiered), not free text.
    claim = {
        "event_type": "cancelled" if cancelled else "delayed",
        "delay_minutes": delay,
        "evidence": status.get("source_url"),
        "description": booking.get("route"),
    }
    hold = {
        "amount": amount,
        "remaining": amount,
        "currency": currency,
        "booking_ref": booking.get("order_no") or booking.get("id"),
        "description": booking.get("route"),
    }
    try:
        decision = await adjudicator.adjudicate(hold, claim)
    except Exception as exc:  # noqa: BLE001 — adjudicator must never block recovery
        logger.info("auto_recover: adjudicator unavailable, using rule baseline: %s", exc)
        pct = 100 if cancelled or delay >= 360 else 60 if delay >= 240 else 40 if delay >= 180 else 25
        decision = {
            "refund_pct": pct,
            "refund_amount": round(amount * pct / 100, 2),
            "currency": currency,
            "rationale": "Rule-based refund (adjudicator unavailable).",
            "policy_basis": "EU261-style",
            "verdict": "partial",
        }

    refund_amount = float(decision.get("refund_amount") or 0)
    settlement: dict[str, Any] = {"mode": "none"}
    if refund_amount > 0 and booking.get("order_no"):
        try:
            settlement = await atlas_sandbox.refund_raw(
                booking["order_no"],
                refund_amount,
                currency=currency,
                reason=f"{claim['event_type']}: {str(decision.get('rationale', ''))[:120]}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_recover: refund_raw failed: %s", exc)
            settlement = {"mode": "error", "error": str(exc)}

    await bookings.update(
        booking["id"],
        stage="cancelled" if cancelled else "refunded",
        last_code="AUTO_REFUND",
        last_message=str(decision.get("rationale", ""))[:400],
        payload_patch={
            "refund": {
                "amount": refund_amount,
                "pct": decision.get("refund_pct"),
                "currency": currency,
                "ref": settlement.get("atlas_ref"),
                "mode": settlement.get("mode"),
                "basis": decision.get("policy_basis"),
                "rationale": decision.get("rationale"),
            }
        },
    )
    return {
        "amount": refund_amount,
        "pct": decision.get("refund_pct"),
        "currency": currency,
        "mode": settlement.get("mode"),
        "rationale": decision.get("rationale"),
        "policy_basis": decision.get("policy_basis"),
        "settlement": settlement,
    }


async def _rebook_new(
    best: dict[str, Any],
    old_booking: dict[str, Any],
    currency: str,
) -> dict[str, Any]:
    """Run the real Atlas booking chain on the chosen alternative, linked to the
    booking it replaces. Goes as far as the sandbox allows and reports the stage."""
    try:
        rec = await booking_flow.start(
            offer_id=(best.get("raw") or {}).get("offer_id") or best["id"],
            route=best.get("title"),
            depart_date=_as_date(old_booking.get("depart_date")),
            travellers=int(old_booking.get("travellers") or 1),
            total_amount=best.get("price_amount"),
            currency=best.get("price_currency") or currency,
            environment=old_booking.get("environment", "sandbox"),
            trip_id=old_booking.get("trip_id"),
            offer_snapshot=best,
        )
        await bookings.update(rec["id"], payload_patch={"replaces_booking_id": old_booking["id"]})

        stage = rec.get("stage")
        ver = await booking_flow.verify(rec["id"], accept_price_change=True)
        stage = ver.get("stage", stage)
        if stage == "price_confirmed":
            order = await booking_flow.create_order(rec["id"], [_SYNTHETIC_PASSENGER])
            stage = order.get("stage", stage)
            if stage == "ordered":
                try:
                    paid = await booking_flow.pay(rec["id"])
                    stage = paid.get("stage", stage)
                except Exception as exc:  # noqa: BLE001 — pay may need sandbox balance
                    logger.info("auto_recover: rebook pay deferred: %s", exc)
        final = await bookings.get(rec["id"]) or rec
        return {"ok": True, "booking": final, "stage": final.get("stage", stage)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_recover: rebook failed: %s", exc)
        return {"ok": False, "booking": None, "error": str(exc)}


async def auto_recover(
    booking_row_id: str,
    *,
    simulate: str | None = None,
    threshold_minutes: int = 90,
    execute: bool = True,
) -> dict[str, Any]:
    """Detect a disruption on a booked flight and (optionally) refund + rebook.

    `simulate` ("delayed" | "cancelled" | "on_time") forces the status for a
    deterministic demo; omit it to check the real status. `execute=False` stops
    after choosing the best alternative (preview). Returns a report with a
    step-by-step ledger of what was done.
    """
    booking = await bookings.get_internal(booking_row_id)
    if booking is None:
        raise ValueError("Booking not found")

    steps: list[dict[str, Any]] = []

    def _record(step: str, ok: bool, detail: str, **extra: Any) -> None:
        steps.append({"step": step, "ok": ok, "detail": detail, **extra})
        sse.publish("flight", "active" if ok else "waiting", detail, data={"auto_recover": step})

    origin, dest, carrier = _route_ends(booking)
    depart = _as_date(booking.get("depart_date"))
    currency = booking.get("currency") or "MYR"
    amount = float(booking.get("total_amount") or 0.0)
    route_label = booking.get("route") or f"{origin or '?'} → {dest or '?'}"

    # 1) Detect ------------------------------------------------------------- #
    status = await flight_status.check_status(
        carrier=carrier, origin=origin, destination=dest, date=depart.isoformat() if depart else None, force=simulate
    )
    delay = int(status.get("delay_minutes") or 0)
    disrupted = status.get("status") == "cancelled" or delay >= threshold_minutes
    _record(
        "detect",
        True,
        f"{route_label}: {status.get('status')}"
        + (f", {delay} min delay" if delay else "")
        + f" ({status.get('mode')})",
        status=status.get("status"),
        delay_minutes=delay,
        mode=status.get("mode"),
    )
    if not disrupted:
        return {
            "disrupted": False,
            "booking_id": booking_row_id,
            "status": status,
            "steps": steps,
            "summary": f"{route_label} is {status.get('status')} — no action needed.",
        }

    # 2) Suggest the best alternative -------------------------------------- #
    alternatives, best = await _find_alternatives(origin, dest, depart, booking, currency)
    if best is None:
        _record("suggest", False, "No bookable alternative found for this route and date.")
        return {
            "disrupted": True,
            "booking_id": booking_row_id,
            "status": status,
            "alternatives": alternatives,
            "steps": steps,
            "summary": f"{route_label} was {status.get('status')} but no bookable alternative was available.",
        }
    _record(
        "suggest",
        True,
        f"Best alternative: {best['title']} — {best.get('price_currency')} {best.get('price_amount')}",
        chosen=best,
        considered=len(alternatives),
    )

    if not execute:
        return {
            "disrupted": True,
            "booking_id": booking_row_id,
            "status": status,
            "alternative": best,
            "alternatives": alternatives,
            "steps": steps,
            "summary": "Alternative found — confirm to refund the old flight and rebook.",
        }

    # 3) Refund the disrupted booking -------------------------------------- #
    refund = await _refund_old(booking, status, amount, currency)
    _record(
        "refund",
        refund.get("mode") not in ("error",),
        f"Refunded {currency} {refund['amount']:.2f} ({refund.get('pct')}%) — {refund.get('mode')}",
        refund=refund,
    )

    # 4) Rebook the replacement -------------------------------------------- #
    rebook = await _rebook_new(best, booking, currency)
    _record(
        "rebook",
        rebook["ok"],
        f"Rebooked {best['title']} — new booking {rebook.get('stage', 'failed')}"
        if rebook["ok"]
        else f"Rebook could not complete: {rebook.get('error')}",
        new_booking=rebook.get("booking"),
    )

    # 5) Report ------------------------------------------------------------ #
    summary = (
        f"Detected {status.get('status')} on {route_label}. "
        f"Refunded {currency} {refund['amount']:.2f} ({refund.get('pct')}%); "
        f"rebooked to {best['title']} at {best.get('price_currency')} {best.get('price_amount')}."
    )
    sse.publish("flight", "done", summary, data={"auto_recover": "complete"})
    try:
        await notify.broadcast(summary, subject="Journava — flight auto-recovered")
    except Exception as exc:  # noqa: BLE001 — notification is best-effort
        logger.debug("auto_recover: notify failed: %s", exc)

    return {
        "disrupted": True,
        "booking_id": booking_row_id,
        "status": status,
        "refund": refund,
        "alternative": best,
        "new_booking": rebook.get("booking"),
        "new_booking_ok": rebook["ok"],
        "steps": steps,
        "summary": summary,
    }
