"""Gnosion brain client — library mode, hot path (spec §7 ①).

Gnosion provides semantic memory, champion/challenger preference learning and a
knowledge graph. It runs in two modes: imported as a library here, and as an MCP
server (`gns mcp`) shared by agents at runtime and by Qoder during development.

The whole module degrades gracefully: if `gnosion` isn't installed yet, memory
falls back to an in-process dict so Phase 0 boots and the API stays healthy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_brain: Any = None
#: Fallback store used only when the gnosion package is unavailable.
_fallback: dict[str, dict[str, Any]] = {}


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
        logger.warning("gnosion not installed — using in-memory fallback store")
        _brain = None
    return _brain


def remember(domain: str, key: str, value: str, label: str | None = None) -> None:
    """Store an experience/decision/outcome so the next trip starts smarter."""
    brain = _load()
    if brain is None:
        _fallback.setdefault(domain, {})[key] = {"value": value, "label": label}
        return
    brain.learn(domain, key, label=label, value=value)
    # TODO(Phase 2): debounce/consolidate instead of exporting on every write.
    brain.export(settings.gnosion_brain_path)


def recall(domain: str, query: str) -> Any:
    """k-NN recall with confidence. Returns None when nothing is known yet."""
    brain = _load()
    if brain is None:
        return _fallback.get(domain, {}).get(query)
    return brain.predict(domain, query)


def available() -> bool:
    """True when the real Gnosion library is backing the brain."""
    return _load() is not None
