"""Text hygiene helpers.

Camofox accessibility snapshots occasionally carry bytes that decode into *lone
surrogates* (e.g. `\\udc8f`). They survive inside Python strings but blow up the
moment anything serializes them to JSON — `UnicodeEncodeError: surrogates not
allowed`. A single such character in a flight title was enough to 500 `GET /trip`
(and therefore blank out My Trip). Scrub them at the boundaries: where crawled
text enters, and where trips are persisted/returned.
"""

from __future__ import annotations

from typing import Any


def clean_str(s: str) -> str:
    """Drop lone surrogates so the string is safe to JSON-encode. No-op if clean."""
    try:
        s.encode("utf-8")
        return s
    except UnicodeEncodeError:
        return s.encode("utf-8", "ignore").decode("utf-8", "ignore")


def scrub_surrogates(obj: Any) -> Any:
    """Recursively clean strings in dicts/lists so the whole structure is JSON-safe."""
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, dict):
        return {clean_str(k) if isinstance(k, str) else k: scrub_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_surrogates(v) for v in obj]
    return obj
