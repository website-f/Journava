"""Gnosion brain client — library mode, hot path (spec §7 ①).

Gnosion is Journava's own memory layer. This module drives it in **library mode**
(in-process, on the hot path); the same brain file is also served by `gns mcp`
for tool-style access and for Qoder during development.

Two head types, matching the two things §7 ① asks for:

- **memory heads** (`remember` / `recall`) — embedding→value k-NN storage. Every
  factual domain uses these: the profile, the destinations, the options each
  agent surfaced, the active trip.
- **classifier heads** (`learn` / `predict`) — champion/challenger preference
  learning. `decision_outcomes` uses this, which is what lets accepted/rejected
  choices actually change future rankings rather than just being logged.

Domains must be declared with `add_domain` before use — Gnosion ships only
`vision / text / design / tabular / memory`, so writing to `flights` without
registering it raises `KeyError`. `_ensure_domains` does that once per load.

If `gnosion` isn't installed the module degrades to an in-process store with the
same interface, and `available()` / `snapshot()` report which backend is live so
the fallback is never presented as the real brain.
"""

from __future__ import annotations

import logging
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

#: Similarity floor for recall. Keys are short and exact-matched in practice, so
#: this only matters for fuzzy lookups (e.g. "venice" vs "venice, italy").
RECALL_MIN_SIM = 0.25

#: Factual memory domains → the label shown in the brain graph. Declaring them up
#: front gives the Agent Control Center's graph real structure from first boot.
MEMORY_DOMAINS: dict[str, str] = {
    "traveler_profile": "Traveler Profile",
    "destinations": "Destinations",
    "flights": "Flights",
    "hotels": "Hotels",
    "activities": "Activities",
    "dining": "Dining",
    "weather": "Weather",
    "budgets": "Budgets",
    "itinerary": "Itinerary",
    "active_trip": "Active Trip",
}

#: Preference-learning domains (classifier heads → champion/challenger).
CLASSIFIER_DOMAINS: dict[str, str] = {
    "decision_outcomes": "Outcomes",
}

KNOWN_DOMAINS: dict[str, str] = {**MEMORY_DOMAINS, **CLASSIFIER_DOMAINS}

#: Typed edges between domains — the knowledge-graph mapping of §7 ①.
DOMAIN_EDGES: tuple[tuple[str, str, float], ...] = (
    ("traveler_profile", "flights", 0.8),
    ("traveler_profile", "hotels", 0.7),
    ("traveler_profile", "dining", 0.9),
    ("traveler_profile", "destinations", 0.9),
    ("destinations", "activities", 0.8),
    ("destinations", "weather", 0.6),
    ("destinations", "itinerary", 0.8),
    ("activities", "itinerary", 0.7),
    ("dining", "itinerary", 0.6),
    ("weather", "itinerary", 0.5),
    ("flights", "budgets", 0.6),
    ("hotels", "budgets", 0.6),
    ("budgets", "itinerary", 0.5),
    ("itinerary", "active_trip", 0.9),
    ("decision_outcomes", "flights", 0.4),
    ("decision_outcomes", "hotels", 0.4),
    ("decision_outcomes", "dining", 0.5),
    ("decision_outcomes", "activities", 0.5),
)

_brain: Any = None
_brain_loaded = False
#: Gnosion mutates shared state; serialise writes so parallel agents can't race.
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Seed profile — shared by both backends
# --------------------------------------------------------------------------- #


def default_profile_json() -> str:
    """The seed traveler profile, built from the model so its keys can't drift.

    `TravelerProfile` ignores unknown fields, so a hand-written dict with a
    near-miss key (`dietary` instead of `halal_required`) validates cleanly while
    silently dropping the preference. Constructing the model prevents that class
    of bug outright.
    """
    from app.agents.schemas import TravelerProfile

    return TravelerProfile(
        halal_required=True,
        cuisine_likes=["local food", "street food", "seafood"],
        interests=["food", "culture", "photography"],
        pace="relaxed",
        home_airport="KUL",
        seat_preference="window",
        max_connections=1,
        avoid_red_eye=True,
    ).model_dump_json()


# --------------------------------------------------------------------------- #
# Fallback store
# --------------------------------------------------------------------------- #


class _InProcessFallback:
    """Stand-in used when the `gnosion` package isn't importable.

    Same interface, far less intelligence: exact-then-fuzzy key matching instead
    of embeddings, and outcome counting instead of champion/challenger learning.
    Enough to run the product; not the real brain, and never claimed to be.
    """

    FUZZY_THRESHOLD = 0.6

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {}
        self._outcomes: dict[str, list[dict[str, Any]]] = {}
        self._seed()

    def _seed(self) -> None:
        """Pre-populate the same default traveler profile as the real brain."""
        self._store.setdefault("traveler_profile", {})["current"] = {
            "value": default_profile_json(),
            "key": "current",
            "label": "seed",
        }

    def remember(self, domain: str, key: str, value: str, label: str | None = None) -> None:
        self._store.setdefault(domain, {})[key] = {
            "value": value,
            "key": key,
            "label": label,
        }

    def recall(self, domain: str, query: str) -> dict[str, Any] | None:
        entries = self._store.get(domain, {})
        if query in entries:
            return entries[query]
        best, best_score = None, 0.0
        for key, entry in entries.items():
            score = SequenceMatcher(None, query.lower(), key.lower()).ratio()
            if score > best_score:
                best_score, best = score, entry
        return best if best_score > self.FUZZY_THRESHOLD else None

    def record_outcome(self, domain: str, item: str, accepted: bool) -> None:
        self._outcomes.setdefault(domain, []).append({"item": item, "accepted": accepted})
        self.remember(
            "decision_outcomes",
            key=f"{domain}:{item}"[:200],
            value="accepted" if accepted else "rejected",
            label=domain,
        )

    def counts(self) -> dict[str, int]:
        return {domain: len(entries) for domain, entries in self._store.items()}

    def outcome_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for domain, entries in self._outcomes.items():
            accepted = sum(1 for e in entries if e["accepted"])
            stats[domain] = {"accepted": accepted, "rejected": len(entries) - accepted}
        return stats


_fallback = _InProcessFallback()


# --------------------------------------------------------------------------- #
# Real brain lifecycle
# --------------------------------------------------------------------------- #


def _ensure_domains(brain: Any) -> None:
    """Register Journava's domains on a freshly loaded brain.

    Gnosion ships five built-in domains; ours have to be added explicitly or
    `learn`/`remember` raise `KeyError: unknown domain`.
    """
    existing = set(getattr(brain, "domains", {}) or {})
    for domain in MEMORY_DOMAINS:
        if domain not in existing:
            brain.add_domain(domain, head="memory", modality="text")
    for domain in CLASSIFIER_DOMAINS:
        if domain not in existing:
            brain.add_domain(domain, head="classifier", modality="text")


def _ensure_seed_profile(brain: Any) -> None:
    """Seed a default profile on an empty brain, matching the fallback store.

    Keeps behaviour identical across backends — otherwise the app has standing
    preferences with the fallback and none with the real brain, and the halal
    scoping rules silently stop applying when you install the dependency.
    """
    try:
        if brain.recall("traveler_profile", "current", min_sim=RECALL_MIN_SIM):
            return
        brain.remember(
            "traveler_profile",
            "current",
            value=default_profile_json(),
            key="current",
            meta={"label": "seed"},
        )
    except Exception as exc:  # noqa: BLE001 — seeding is a convenience, not a must
        logger.debug("Could not seed profile: %s", exc)


def _load() -> Any:
    """Load the persisted brain, or create one. Returns None when unavailable."""
    global _brain, _brain_loaded
    if _brain_loaded:
        return _brain
    _brain_loaded = True
    try:
        from gnosion import Gnosion  # type: ignore[import-not-found]

        path = Path(settings.gnosion_brain_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        brain = Gnosion.load(str(path)) if path.exists() else Gnosion()
        _ensure_domains(brain)
        _brain = brain
        _ensure_seed_profile(brain)
        logger.info("Gnosion brain ready (%s)", path)
    except ImportError:
        logger.warning(
            "gnosion not installed — using the in-process fallback store. "
            "Run `uv sync --extra brain` for real semantic memory."
        )
        _brain = None
    except Exception as exc:  # noqa: BLE001 — a corrupt brain file must not block boot
        logger.error("Gnosion failed to load (%s) — falling back in-process", exc)
        _brain = None
    return _brain


def _persist(brain: Any) -> None:
    """Write the brain to disk. Best-effort: a failed export is not fatal."""
    try:
        brain.export(settings.gnosion_brain_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not export brain: %s", exc)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def remember(domain: str, key: str, value: str, label: str | None = None) -> None:
    """Store an experience so the next trip starts smarter.

    The key doubles as the embedding cue, which is what makes `recall(domain,
    key)` an exact hit while still allowing near-miss lookups.
    """
    brain = _load()
    if brain is None:
        _fallback.remember(domain, key, value, label)
        return
    with _lock:
        try:
            brain.remember(domain, key, value=value, key=key, meta={"label": label})
            _persist(brain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gnosion write to %s failed (%s) — using fallback", domain, exc)
            _fallback.remember(domain, key, value, label)


def recall(domain: str, query: str) -> dict[str, Any] | None:
    """k-NN recall with confidence. Returns None when nothing is known yet."""
    brain = _load()
    if brain is None:
        return _fallback.recall(domain, query)
    try:
        return brain.recall(domain, query, min_sim=RECALL_MIN_SIM)
    except Exception as exc:  # noqa: BLE001 — an empty/unknown domain isn't an error
        logger.debug("Gnosion recall miss for %s/%s: %s", domain, query, exc)
        return None


def record_outcome(domain: str, item: str, accepted: bool) -> None:
    """Train the preference classifier on an accepted/rejected choice (§7 ③).

    This is the champion/challenger path, not plain storage: the label is what
    `predict_preference` later uses to rank a similar option without regression.
    """
    brain = _load()
    if brain is None:
        _fallback.record_outcome(domain, item, accepted)
        return
    with _lock:
        try:
            brain.learn(
                "decision_outcomes",
                f"{domain}: {item}",
                label="accepted" if accepted else "rejected",
                value="accepted" if accepted else "rejected",
            )
            _persist(brain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gnosion outcome write failed (%s) — using fallback", exc)
            _fallback.record_outcome(domain, item, accepted)


def predict_preference(domain: str, item: str) -> dict[str, Any] | None:
    """Ask the brain whether the traveller is likely to accept `item`.

    Returns `{"label": "accepted"|"rejected", "confidence": float}` or None when
    the classifier has not seen enough examples to have an opinion.
    """
    brain = _load()
    if brain is None:
        return None
    try:
        return brain.predict("decision_outcomes", f"{domain}: {item}")
    except Exception:  # noqa: BLE001 — untrained classifier
        return None


def _domain_counts() -> dict[str, int]:
    """Live memory count per domain, whichever backend is serving."""
    brain = _load()
    if brain is None:
        return _fallback.counts()
    try:
        domains = brain.stats().get("domains", {})
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gnosion stats unavailable: %s", exc)
        return {}
    counts: dict[str, int] = {}
    for domain in KNOWN_DOMAINS:
        info = domains.get(domain) or {}
        # memory heads report `entries`, classifier heads report `samples`.
        counts[domain] = int(info.get("entries", info.get("samples", 0)) or 0)
    return counts


def graph() -> dict[str, object]:
    """Domain-level brain graph for the Agent Control Center (§7 ①).

    Every known domain is a node whose `weight` is its live memory count, so the
    graph starts sparse and thickens as agents learn — that is the "brain
    growing" demo: real numbers that climb, not a fixed picture. Entry-level
    detail is available separately via `entry_graph()`.
    """
    counts = _domain_counts()
    nodes = [
        {"id": domain, "label": label, "domain": domain, "weight": counts.get(domain, 0)}
        for domain, label in KNOWN_DOMAINS.items()
    ]
    node_ids = {node["id"] for node in nodes}
    edges = [
        {"source": src, "target": tgt, "strength": strength}
        for src, tgt, strength in DOMAIN_EDGES
        if src in node_ids and tgt in node_ids
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "backend": "gnosion" if available() else "in-process-fallback",
        "total_memories": sum(counts.values()),
        "outcomes": {} if available() else _fallback.outcome_stats(),
    }


def entry_graph() -> dict[str, object]:
    """Gnosion's own entry-level knowledge graph, when the real brain is live.

    Finer-grained than `graph()`: one node per stored memory, with the semantic
    edges Gnosion derived between them.
    """
    brain = _load()
    if brain is None:
        return {"nodes": [], "edges": [], "backend": "in-process-fallback"}
    try:
        raw = brain.graph()
        return {
            "nodes": raw.get("nodes", []),
            "edges": raw.get("edges", []),
            "domains": raw.get("domains", []),
            "backend": "gnosion",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Gnosion entry graph unavailable: %s", exc)
        return {"nodes": [], "edges": [], "backend": "gnosion"}


def available() -> bool:
    """True when the real Gnosion library is backing the brain."""
    return _load() is not None


def snapshot() -> dict[str, Any]:
    """Diagnostic view of the brain — surfaced by /health and the Engine page."""
    return {
        "backend": "gnosion" if available() else "in-process-fallback",
        "brain_path": settings.gnosion_brain_path,
        "domains": _domain_counts(),
    }


__all__ = [
    "CLASSIFIER_DOMAINS",
    "DOMAIN_EDGES",
    "KNOWN_DOMAINS",
    "MEMORY_DOMAINS",
    "available",
    "entry_graph",
    "graph",
    "predict_preference",
    "recall",
    "record_outcome",
    "remember",
    "snapshot",
]
