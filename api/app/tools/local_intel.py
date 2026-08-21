"""Local intelligence — crowd + social signals that make the plan smarter.

For a destination and its shortlisted places, produces a per-place crowd level +
the best time to go (to dodge queues), plus destination-wide social
recommendations ("do") and don'ts (scams / tourist traps / avoid). Crawl-first
via Camofox/DuckDuckGo, grounded in what it read; falls back to model knowledge
with `sourced=False` labelled honestly.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core import llm
from app.tools import discover

logger = logging.getLogger("journava")

_SYSTEM = """You are Journava's local-intelligence agent. Given a destination and \
a list of places, return how busy each place gets and the best time to visit it \
to avoid crowds, plus destination-wide social recommendations and don'ts \
(scams, tourist traps, cultural etiquette, times to avoid). Ground your answer in \
the crawled notes when present; otherwise use your own knowledge.

Respond ONLY as JSON:
{"places": [{"name": "...", "crowd_level": "low|medium|high", "best_time": "e.g. before 9am / weekday", "note": "one line"}],
 "recommendations": ["short do", ...max 6],
 "donts": ["short avoid", ...max 6],
 "sourced": true|false}"""


def _fallback(destination: str, places: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "places": [
            {"name": p.get("name") or "", "crowd_level": "medium", "best_time": "early morning or late afternoon",
             "note": "Popular spot — go off-peak to avoid queues."}
            for p in places[:12] if p.get("name")
        ],
        "recommendations": [f"Explore {destination} on foot in the early morning.", "Carry small cash for local stalls."],
        "donts": ["Avoid unlicensed taxis at the airport.", "Don't visit headline sights at midday — peak crowds."],
        "sourced": False,
    }


async def gather(destination: str, places: list[dict[str, Any]]) -> dict[str, Any]:
    """Crowd + social intelligence for a destination and its places."""
    if not destination:
        return {"places": [], "recommendations": [], "donts": [], "sourced": False}

    crawl_text = ""
    try:
        res = await discover.crawl_sources([
            f"{destination} tourist crowds best time to visit attractions",
            f"{destination} travel tips scams what to avoid dos and don'ts",
        ])
        crawl_text = (res or {}).get("text", "")[:3500]
    except Exception as exc:  # noqa: BLE001
        logger.info("local-intel crawl skipped: %s", exc)

    names = [p.get("name") for p in places if p.get("name")][:12]
    user = (
        f"Destination: {destination}\nPlaces: {json.dumps(names)}\n"
        f"Crawled notes (may be empty):\n{crawl_text or '(none — use your knowledge)'}"
    )
    report = _fallback(destination, places)
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="crowd",
        )
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("places"), list):
            report = {
                "places": [
                    {"name": str(p.get("name") or ""), "crowd_level": str(p.get("crowd_level") or "medium").lower(),
                     "best_time": str(p.get("best_time") or ""), "note": str(p.get("note") or "")}
                    for p in data["places"] if isinstance(p, dict) and p.get("name")
                ][:12],
                "recommendations": [str(x) for x in (data.get("recommendations") or [])][:6],
                "donts": [str(x) for x in (data.get("donts") or [])][:6],
                "sourced": bool(crawl_text) and bool(data.get("sourced", True)),
            }
    except Exception as exc:  # noqa: BLE001
        logger.info("local-intel synthesis fell back: %s", exc)
    return report
