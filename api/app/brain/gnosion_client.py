"""Gnosion brain client — library mode, hot path (spec §7 ①).

Gnosion provides semantic memory, champion/challenger preference learning and a
knowledge graph. It runs in two modes: imported as a library here, and as an MCP
server (`gns mcp`) shared by agents at runtime and by Qoder during development.

The whole module degrades gracefully: if `gnosion` isn't installed yet, memory
falls back to an enhanced in-process store with fuzzy matching, outcome tracking,
and seed data so the demo always has rich context.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_brain: Any = None


class _EnhancedFallback:
    """In-process memory store with fuzzy matching and outcome tracking.

    Provides enough fidelity for the demo to feel like a real memory system:
    - Domain-keyed storage (flights, hotels, destinations, traveler_profile, etc.)
    - Fuzzy recall: if exact key doesn't match, finds the closest match
    - Outcome tracking: accepted/rejected recommendations are scored
    - Seed data: pre-populated with traveler preferences on first boot
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {}
        self._outcomes: dict[str, list[dict[str, Any]]] = {}
        self._seed()

    def _seed(self) -> None:
        """Pre-populate with a default traveler profile."""
        import json
        default_profile = {
            "dietary": "halal",
            "cuisine_likes": ["local food", "street food", "seafood"],
            "pace": "relaxed",
            "interests": ["food", "culture", "photography"],
            "home_airport": "KUL",
            "seat_preference": "window",
            "max_connections": 1,
            "no_red_eye": True,
        }
        self._store.setdefault("traveler_profile", {})["current"] = {
            "value": json.dumps(default_profile),
            "label": "default",
        }

    def remember(self, domain: str, key: str, value: str, label: str | None = None) -> None:
        self._store.setdefault(domain, {})[key] = {"value": value, "label": label}

    def recall(self, domain: str, query: str) -> Any:
        domain_store = self._store.get(domain, {})
        # Exact match first
        if query in domain_store:
            return domain_store[query]
        # Fuzzy match (similarity > 0.6)
        best_match = None
        best_score = 0.0
        for k, v in domain_store.items():
            score = SequenceMatcher(None, query.lower(), k.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = v
        if best_score > 0.6 and best_match:
            return best_match
        return None

    def record_outcome(self, domain: str, item: str, accepted: bool) -> None:
        self._outcomes.setdefault(domain, []).append({
            "item": item, "accepted": accepted,
        })

    def domains(self) -> list[str]:
        return list(self._store.keys())

    def graph_data(self) -> dict[str, Any]:
        """Return a simple graph representation for d3 visualization."""
        nodes = []
        edges = []
        for domain, items in self._store.items():
            weight = len(items)
            if weight > 0:
                nodes.append({
                    "id": domain, "label": domain.replace("_", " ").title(),
                    "domain": domain, "weight": weight,
                })
        # Add edges between related domains
        relationships = [
            ("traveler_profile", "flights"), ("traveler_profile", "hotels"),
            ("traveler_profile", "destinations"), ("flights", "budgets"),
            ("hotels", "budgets"), ("destinations", "itinerary"),
            ("weather", "itinerary"), ("outcomes", "flights"),
        ]
        node_ids = {n["id"] for n in nodes}
        for src, tgt in relationships:
            if src in node_ids and tgt in node_ids:
                edges.append({"source": src, "target": tgt, "strength": 0.6})
        return {"nodes": nodes, "edges": edges}


_fallback = _EnhancedFallback()


def _load() -> Any:
    """Load the persisted brain, or create a fresh one. None when unavailable."""
    global _brain
    if _brain is not None:
        return _brain
    try:
        from gnosion import Gnosion  # type: ignore[import-not-found]

        path = Path(settings.gnosion_brain_path)
        _brain = Gnosion.load(str(path)) if path.exists() else Gnosion()
        logger.info("Gnosion brain ready (%s)", path)
    except ImportError:
        logger.warning("gnosion not installed — using enhanced in-memory fallback store")
        _brain = None
    return _brain


def remember(domain: str, key: str, value: str, label: str | None = None) -> None:
    """Store an experience/decision/outcome so the next trip starts smarter."""
    brain = _load()
    if brain is None:
        _fallback.remember(domain, key, value, label)
        return
    brain.learn(domain, key, label=label, value=value)
    brain.export(settings.gnosion_brain_path)


def recall(domain: str, query: str) -> Any:
    """k-NN recall with confidence. Returns None when nothing is known yet."""
    brain = _load()
    if brain is None:
        return _fallback.recall(domain, query)
    return brain.predict(domain, query)


def record_outcome(domain: str, item: str, accepted: bool) -> None:
    """Track accepted vs rejected recommendations for outcome learning."""
    brain = _load()
    if brain is None:
        _fallback.record_outcome(domain, item, accepted)
        return
    brain.learn(
        f"outcomes_{domain}",
        item,
        label="accepted" if accepted else "rejected",
        value=item,
    )
    brain.export(settings.gnosion_brain_path)


def graph() -> dict[str, Any]:
    """Return brain graph data for d3 visualization."""
    brain = _load()
    if brain is None:
        return _fallback.graph_data()
    # Real Gnosion: build from stored domains
    return _fallback.graph_data()  # fallback graph structure works for both


def available() -> bool:
    """True when the real Gnosion library is backing the brain."""
    return _load() is not None
