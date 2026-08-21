"""AI escrow adjudicator — the "impossible without AI" multiplier.

Given an escrow hold and a claim (flight delayed/cancelled, downgrade, no-show,
service issue), an agent decides *autonomously* how to settle: release the funds
to the supplier, partially refund the traveller, or refund in full — with a
written rationale and a cited policy basis. A rule baseline (EU261-inspired for
delays) anchors the decision; the LLM refines it within a sane band and explains
it in plain language. No human in the loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core import llm

logger = logging.getLogger("journava")


def _rule_baseline(claim: dict[str, Any]) -> dict[str, Any]:
    """Rule-of-thumb refund %, so the AI never drifts far from fair practice."""
    event = str(claim.get("event_type") or "").lower()
    mins = claim.get("delay_minutes")
    mins = int(mins) if isinstance(mins, (int, float)) else None

    if event in ("flight_cancelled", "cancelled", "overbooking_denied", "no_alternative"):
        return {"refund_pct": 100, "basis": "Cancellation / denied boarding — full refund (EU261 Art.8)."}
    if event in ("flight_delayed", "delayed") and mins is not None:
        if mins >= 360:
            return {"refund_pct": 100, "basis": "Delay ≥ 6h — treated as cancellation (EU261)."}
        if mins >= 240:
            return {"refund_pct": 60, "basis": "Delay 4–6h — major disruption compensation."}
        if mins >= 180:
            return {"refund_pct": 40, "basis": "Delay 3–4h — EU261 long-delay tier."}
        if mins >= 120:
            return {"refund_pct": 25, "basis": "Delay 2–3h — partial goodwill compensation."}
        return {"refund_pct": 0, "basis": "Delay < 2h — below compensation threshold; release to supplier."}
    if event == "downgrade":
        return {"refund_pct": 30, "basis": "Cabin/room downgrade — fare-class differential (EU261 Art.10 style)."}
    if event in ("no_show", "traveller_no_show"):
        return {"refund_pct": 0, "basis": "Traveller no-show — non-refundable; release to supplier."}
    if event in ("service_issue", "not_as_described"):
        return {"refund_pct": 25, "basis": "Service not as described — partial goodwill refund."}
    return {"refund_pct": 20, "basis": "General claim — modest goodwill refund pending review."}


_SYSTEM = """You are Journava's escrow adjudicator. An amount is held in escrow \
for a booking; something went wrong and you must decide how to split it between a \
REFUND to the traveller and a RELEASE to the supplier — fairly, and fast, with no \
human in the loop. A rule baseline is provided; stay within ±15 percentage points \
of it unless the evidence clearly justifies more, and never exceed 100 or go below 0.

Respond ONLY as JSON:
{"verdict": "release|partial_refund|full_refund", "refund_pct": number,
 "rationale": "2-3 sentences a traveller and a supplier would both find fair",
 "policy_basis": "the rule/regulation or T&C you leaned on"}"""


async def adjudicate(hold: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    """Decide the refund/release split for a hold given a claim."""
    baseline = _rule_baseline(claim)
    remaining = float(hold.get("remaining", hold.get("amount", 0)))
    currency = hold.get("currency", "MYR")

    user = (
        f"Escrow held: {currency} {remaining:.2f} for '{hold.get('description') or hold.get('booking_ref')}'.\n"
        f"Claim: {json.dumps(claim, default=str)}\n"
        f"Rule baseline: refund {baseline['refund_pct']}% — {baseline['basis']}\n"
        "Decide the split."
    )
    refund_pct = float(baseline["refund_pct"])
    rationale = baseline["basis"]
    policy_basis = baseline["basis"]
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            agent="adjudicator",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            pct = data.get("refund_pct")
            if isinstance(pct, (int, float)):
                refund_pct = max(0.0, min(100.0, float(pct)))
            rationale = str(data.get("rationale") or rationale)
            policy_basis = str(data.get("policy_basis") or policy_basis)
    except Exception as exc:  # noqa: BLE001 — fall back to the rule baseline
        logger.info("adjudicator LLM refine failed, using baseline: %s", exc)

    refund_amount = round(remaining * refund_pct / 100.0, 2)
    release_amount = round(remaining - refund_amount, 2)
    verdict = "full_refund" if refund_pct >= 99.5 else ("release" if refund_amount <= 0.005 else "partial_refund")
    return {
        "verdict": verdict,
        "refund_pct": round(refund_pct, 1),
        "refund_amount": refund_amount,
        "release_amount": release_amount,
        "currency": currency,
        "rationale": rationale,
        "policy_basis": policy_basis,
        "baseline_pct": baseline["refund_pct"],
    }
