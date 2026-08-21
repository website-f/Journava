"""Hotel inventory firewall — reconciliation logic (Tier 3).

A supplier's physical room count (the listing capacity) is the source of truth.
Each sales channel gets an allocation; the firewall detects the two ways that
drift into a double-booking and prescribes the fix:

1. **Over-allocation** — the channels are collectively told they can sell more
   rooms than physically exist.
2. **Open-while-sold-out** — a channel still shows availability after the
   physical pool is exhausted (the classic OTA double-booking).

Pure functions here; the router applies the fixes and does the atomic booking
guard against Postgres.
"""

from __future__ import annotations

from typing import Any


def reconcile(capacity: int, channels: list[dict[str, Any]]) -> dict[str, Any]:
    """Diagnose drift for one listing. `channels` = [{channel, allocated, sold}]."""
    total_sold = sum(int(c.get("sold") or 0) for c in channels)
    total_allocated = sum(int(c.get("allocated") or 0) for c in channels)
    physical_available = max(0, int(capacity) - total_sold)

    discrepancies: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []

    if total_allocated > capacity:
        discrepancies.append(
            {
                "type": "over_allocation",
                "severity": "high",
                "detail": f"{total_allocated} rooms allocated across channels but only {capacity} exist "
                f"— {total_allocated - capacity} oversell exposure.",
            }
        )

    if physical_available == 0:
        for c in channels:
            still_open = int(c.get("allocated") or 0) - int(c.get("sold") or 0)
            if still_open > 0:
                discrepancies.append(
                    {
                        "type": "open_while_soldout",
                        "severity": "critical",
                        "channel": c["channel"],
                        "detail": f"{c['channel']} still shows {still_open} available while physically sold out.",
                    }
                )
                fixes.append(
                    {"channel": c["channel"], "action": "close_out", "new_allocated": int(c.get("sold") or 0)}
                )

    # When over-allocated but not yet sold out, cap each channel's allocation to
    # its fair share of the physical pool (proportional close-down), so the sum
    # can never exceed capacity going forward.
    if total_allocated > capacity and physical_available > 0:
        for c in channels:
            alloc = int(c.get("allocated") or 0)
            sold = int(c.get("sold") or 0)
            if alloc > sold:
                share = max(sold, round(alloc * capacity / total_allocated)) if total_allocated else sold
                if share < alloc:
                    fixes.append({"channel": c["channel"], "action": "rebalance", "new_allocated": share})

    return {
        "capacity": int(capacity),
        "total_allocated": total_allocated,
        "total_sold": total_sold,
        "physical_available": physical_available,
        "healthy": not discrepancies,
        "discrepancies": discrepancies,
        "fixes": fixes,
    }
