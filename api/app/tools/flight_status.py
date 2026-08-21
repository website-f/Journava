"""Flight status detection (Phase: autonomous delay detection).

Real-first with a labelled simulation fallback — the same honesty pattern as
`atlas_sandbox`. We crawl a public flight-status page with Camofox and read the
accessibility snapshot for delay/cancellation language; if the crawl is walled or
inconclusive we return a clearly-labelled simulation so the demo never dead-ends.

`force` lets the demo trigger a specific disruption (the "money shot"): the
detector reports a delay/cancellation without needing a real disrupted flight.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from app.tools import camofox

logger = logging.getLogger("journava")

#: Snapshot language → status. Order matters: "cancelled" wins over "delayed".
_CANCELLED = re.compile(r"\bcancel(?:led|ed|lation)\b", re.I)
_DELAYED = re.compile(r"\bdelay(?:ed)?\b", re.I)
_ON_TIME = re.compile(r"\bon[\s-]?time\b|\bscheduled\b|\bboarding\b|\bdeparted\b|\ben\s?route\b", re.I)
_DELAY_MINUTES = re.compile(r"delayed(?:\s+by)?\s+(?:about\s+)?(\d{1,3})\s*(?:min|minute|m\b)", re.I)
_DELAY_HOURS = re.compile(r"delayed(?:\s+by)?\s+(?:about\s+)?(\d{1,2})\s*(?:hr|hour|h\b)", re.I)


def _status_query(carrier: str, origin: str, destination: str, date: str) -> str:
    bits = [b for b in [carrier, origin, destination, date, "flight status"] if b]
    return " ".join(bits)


async def _crawl_status(carrier: str, origin: str, destination: str, date: str) -> dict[str, Any] | None:
    """Best-effort live read of a flight-status page. None if inconclusive."""
    query = _status_query(carrier, origin, destination, date)
    url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en"
    try:
        snapshot = await camofox.browse(url, ready=r"(?i)(delay|cancel|on[\s-]?time|scheduled|status)", attempts=4)
    except Exception as exc:  # noqa: BLE001
        logger.info("flight status crawl failed: %s", exc)
        return None
    if not snapshot:
        return None
    text = snapshot[:6000]
    if _CANCELLED.search(text):
        return {"status": "cancelled", "delay_minutes": None, "source_url": url}
    if _DELAYED.search(text):
        mins = None
        m = _DELAY_MINUTES.search(text)
        h = _DELAY_HOURS.search(text)
        if m:
            mins = int(m.group(1))
        elif h:
            mins = int(h.group(1)) * 60
        return {"status": "delayed", "delay_minutes": mins, "source_url": url}
    if _ON_TIME.search(text):
        return {"status": "on_time", "delay_minutes": 0, "source_url": url}
    return None


async def check_status(
    *,
    carrier: str = "",
    origin: str = "",
    destination: str = "",
    date: str = "",
    force: str | None = None,
) -> dict[str, Any]:
    """Return {status, delay_minutes, source_url, mode, sim_reason?}.

    status: on_time | delayed | cancelled.
    mode:   "live" (read from a page) | "simulated" (labelled fallback / forced demo).
    force:  "delayed" | "cancelled" | "on_time" to drive the demo deterministically.
    """
    if force in ("delayed", "cancelled", "on_time"):
        return {
            "status": force,
            "delay_minutes": 180 if force == "delayed" else (None if force == "cancelled" else 0),
            "source_url": None,
            "mode": "simulated",
            "sim_reason": "demo trigger",
            "carrier": carrier,
            "route": f"{origin}→{destination}",
        }

    live = await _crawl_status(carrier, origin, destination, date)
    if live is not None:
        return {**live, "mode": "live", "carrier": carrier, "route": f"{origin}→{destination}"}

    # Inconclusive crawl → honest simulated "on time" so a watch never fakes a delay.
    return {
        "status": "on_time",
        "delay_minutes": 0,
        "source_url": None,
        "mode": "simulated",
        "sim_reason": "no live status page available",
        "carrier": carrier,
        "route": f"{origin}→{destination}",
    }
