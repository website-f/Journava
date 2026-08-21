"""Corporate travel policy — shape, extraction, and evaluation (Phase 2.3).

Pure functions shared by the Flight/Hotel agents (which read the active org
policy as a layer on top of the traveller's own prefs) and the API (which stores
policies and reports compliance in the Agency console). A policy is soft: like
personal preferences it never removes options, it flags violations and nudges
ranking toward the preferred carriers/hotels.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("journava")

#: Empty policy — every field optional, so "no policy" is just all-None.
DEFAULT_POLICY: dict[str, Any] = {
    "max_fare_amount": None,        # per one-way sector cap
    "fare_currency": "MYR",
    "max_cabin": None,              # economy < premium_economy < business < first
    "preferred_carriers": [],       # airline names or IATA codes
    "max_hotel_per_night": None,
    "hotel_currency": "MYR",
    "preferred_hotels": [],         # chain / property names
    "approval_threshold": None,     # trip total that needs manager sign-off
    "notes": "",
}

_CABIN_RANK = {"economy": 0, "premium_economy": 1, "premium": 1, "business": 2, "first": 3}

_EXTRACT_SYSTEM = """You convert a company's corporate travel policy into a strict \
JSON object. Read the policy text and fill only the fields you can find; use null \
when a rule isn't stated. Amounts are numbers (no currency symbols).

Respond ONLY as JSON:
{"max_fare_amount": number|null, "fare_currency": "ISO code",
 "max_cabin": "economy|premium_economy|business|first"|null,
 "preferred_carriers": ["airline", ...], "max_hotel_per_night": number|null,
 "hotel_currency": "ISO code", "preferred_hotels": ["chain", ...],
 "approval_threshold": number|null, "notes": "one-line summary of anything else"}"""


def merge(policy: dict[str, Any] | None) -> dict[str, Any]:
    """A full policy dict with defaults filled — safe to read every key."""
    out = dict(DEFAULT_POLICY)
    if isinstance(policy, dict):
        for k in out:
            if policy.get(k) is not None:
                out[k] = policy[k]
    # Normalise list/str shapes.
    for key in ("preferred_carriers", "preferred_hotels"):
        val = out.get(key)
        if isinstance(val, str):
            out[key] = [v.strip() for v in val.split(",") if v.strip()]
        elif not isinstance(val, list):
            out[key] = []
        else:
            out[key] = [str(v).strip() for v in val if str(v).strip()]
    if isinstance(out.get("max_cabin"), str):
        out["max_cabin"] = out["max_cabin"].strip().lower().replace(" ", "_") or None
    return out


def is_empty(policy: dict[str, Any] | None) -> bool:
    """True when nothing meaningful is set (so agents can skip the policy layer)."""
    p = merge(policy)
    return not (
        p["max_fare_amount"]
        or p["max_cabin"]
        or p["preferred_carriers"]
        or p["max_hotel_per_night"]
        or p["preferred_hotels"]
        or p["approval_threshold"]
    )


async def extract_from_text(text: str) -> dict[str, Any]:
    """Turn raw policy-document text into a structured policy via the LLM."""
    from app.core import llm

    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": text[:12_000]},
            ],
            response_format={"type": "json_object"},
            agent="assistant",
        )
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("policy extract not an object")
    except Exception as exc:  # noqa: BLE001 — extraction is best-effort
        logger.warning("policy extract failed: %s", exc)
        return dict(DEFAULT_POLICY)
    return merge(data)


def _matches_preferred(text: str, preferred: list[str]) -> str | None:
    """Return the preferred name the text matches (carrier or hotel), or None."""
    low = (text or "").lower()
    for name in preferred:
        n = name.lower().strip()
        if n and n in low:
            return name
    return None


def eval_dict(option: Any) -> dict[str, Any]:
    """Normalise an Option object OR a serialized option dict for evaluation."""
    if isinstance(option, dict):
        raw = option.get("raw") or {}
        return {
            "id": option.get("id"),
            "title": option.get("title") or "",
            "provider": option.get("provider") or "",
            "price_amount": option.get("price_amount"),
            "price_currency": option.get("price_currency"),
            "cabin": (raw.get("cabin") or raw.get("cabin_class") or option.get("cabin")),
        }
    raw = getattr(option, "raw", {}) or {}
    price = getattr(option, "price_amount", None)
    return {
        "id": getattr(option, "id", None),
        "title": getattr(option, "title", "") or "",
        "provider": getattr(option, "provider", "") or "",
        "price_amount": float(price) if price is not None else None,
        "price_currency": getattr(option, "price_currency", None),
        "cabin": raw.get("cabin") or raw.get("cabin_class"),
    }


def evaluate_flights(options: list[Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    """Check flight options against the policy. Never removes options — reports.

    Returns {applied, violations:[{option_id,title,reason}], compliant_count,
    preferred_count, summary}.
    """
    p = merge(policy)
    if is_empty(p):
        return {"applied": False, "violations": [], "compliant_count": 0, "preferred_count": 0, "summary": ""}

    cap = p["max_fare_amount"]
    max_cabin_rank = _CABIN_RANK.get(p["max_cabin"]) if p["max_cabin"] else None
    violations: list[dict[str, Any]] = []
    preferred = 0
    compliant = 0

    for opt in options:
        o = eval_dict(opt)
        reasons: list[str] = []
        price = o["price_amount"]
        if cap and price is not None and float(price) > float(cap):
            cur = o["price_currency"] or p["fare_currency"]
            note = "" if (not o["price_currency"] or o["price_currency"] == p["fare_currency"]) else " (check currency)"
            reasons.append(f"fare {cur} {float(price):,.0f} exceeds cap {p['fare_currency']} {float(cap):,.0f}{note}")
        cabin = str(o["cabin"] or "").lower().replace(" ", "_")
        if max_cabin_rank is not None and cabin in _CABIN_RANK and _CABIN_RANK[cabin] > max_cabin_rank:
            reasons.append(f"{cabin.replace('_', ' ')} class above policy max ({p['max_cabin']})")
        if p["preferred_carriers"] and _matches_preferred(f"{o['provider']} {o['title']}", p["preferred_carriers"]):
            preferred += 1
        if reasons:
            violations.append({"option_id": o["id"], "title": o["title"], "reason": "; ".join(reasons)})
        else:
            compliant += 1

    parts = []
    if violations:
        parts.append(f"{len(violations)} option(s) breach policy")
    if preferred:
        parts.append(f"{preferred} on a preferred carrier")
    if compliant and not violations:
        parts.append("all options within policy")
    return {
        "applied": True,
        "violations": violations,
        "compliant_count": compliant,
        "preferred_count": preferred,
        "summary": " · ".join(parts) if parts else "policy applied",
    }


def carrier_boost(option: Any, policy: dict[str, Any] | None) -> float:
    """Ranking bonus (negative = better) for a preferred carrier / under-cap fare."""
    p = merge(policy)
    if is_empty(p):
        return 0.0
    o = eval_dict(option)
    bonus = 0.0
    if p["preferred_carriers"] and _matches_preferred(f"{o['provider']} {o['title']}", p["preferred_carriers"]):
        bonus -= 1.0
    cap = p["max_fare_amount"]
    if cap and o["price_amount"] is not None and float(o["price_amount"]) > float(cap):
        bonus += 3.0  # over-cap fares sink in the ranking
    return bonus
