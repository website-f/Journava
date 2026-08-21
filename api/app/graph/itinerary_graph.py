"""Itinerary as a dependency graph (the major-breakthrough tier).

Every leg of a trip depends on the one before it — you can't check in before you
land, can't make the 3pm tour if the connecting flight slips. This models the
itinerary as an ordered DAG so that when one leg moves (a delay), we can
propagate the shift through every downstream leg, detect what breaks (a missed
connection, a venue that's now closed), and hand the broken legs to the re-planner.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

#: Minimum connection time — below this a shifted arrival misses the next flight.
MCT_MINUTES = 90
#: A leg pushed past this hour is treated as "venue likely closed".
LATE_HOUR = 22


def _parse(t: str | None) -> datetime | None:
    if not t:
        return None
    for fmt in ("%H:%M", "%H.%M", "%I:%M %p"):
        try:
            return datetime.strptime(t.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _sort_key(leg: dict[str, Any]) -> tuple[int, int]:
    t = _parse(leg.get("starts_at"))
    return (int(leg.get("day") or 0), (t.hour * 60 + t.minute) if t else 0)


def build(results: dict[str, Any]) -> dict[str, Any]:
    """Build the ordered dependency graph from a trip's itinerary items."""
    items = ((results or {}).get("itinerary") or {}).get("items") or []
    legs: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        legs.append(
            {
                "id": f"leg{i}",
                "kind": it.get("kind") or "activity",
                "day": int(it.get("day_index") or 0),
                "title": it.get("title") or "",
                "starts_at": it.get("starts_at"),
                "ends_at": it.get("ends_at"),
                "cost_amount": it.get("cost_amount"),
                "cost_currency": it.get("cost_currency"),
            }
        )
    legs.sort(key=_sort_key)
    for idx, leg in enumerate(legs):
        leg["depends_on"] = [legs[idx - 1]["id"]] if idx > 0 else []
        leg["shift_minutes"] = 0
        leg["conflict"] = None
    edges = [{"from": leg["depends_on"][0], "to": leg["id"]} for leg in legs if leg["depends_on"]]
    return {"nodes": legs, "edges": edges}


def propagate(graph: dict[str, Any], source_id: str, delay_minutes: int) -> dict[str, Any]:
    """Shift every leg from `source_id` onward by the delay; flag what breaks.

    Returns {nodes (shifted), impacted:[legs that broke]}.
    """
    nodes = [dict(n) for n in graph["nodes"]]
    start = next((i for i, n in enumerate(nodes) if n["id"] == source_id), 0)
    impacted: list[dict[str, Any]] = []

    for node in nodes[start:]:
        # The source leg itself absorbs the delay; downstream legs get pushed.
        node["shift_minutes"] = delay_minutes
        s, e = _parse(node.get("starts_at")), _parse(node.get("ends_at"))
        if s:
            node["starts_at"] = _fmt(s + timedelta(minutes=delay_minutes))
        if e:
            node["ends_at"] = _fmt(e + timedelta(minutes=delay_minutes))

        if node is nodes[start]:
            continue  # the disrupted leg is the cause, not an impact

        new_start = _parse(node.get("starts_at"))
        conflict = None
        if node["kind"] in ("flight", "transport") and delay_minutes >= MCT_MINUTES:
            conflict = "missed_connection"
        elif new_start and new_start.hour >= LATE_HOUR:
            conflict = "likely_closed"
        elif node["kind"] == "hotel" and delay_minutes >= 240:
            conflict = "late_checkin"
        node["conflict"] = conflict
        if conflict:
            impacted.append(node)

    return {"nodes": nodes, "impacted": impacted}
