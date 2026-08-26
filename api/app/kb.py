"""Knowledge Base — "train your AI on your business."

An owner drops in their brochure text or a website URL; the content is stored
and, at run time, the most relevant snippets are retrieved and injected into
every custom agent and the inbox reply — so they answer from THIS business's
real facts instead of generic knowledge. Retrieval is deliberately dependency-
free: a lightweight term-overlap score over the org's entries (good enough to
ground answers for a demo, with no vector DB to run).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth.deps import resolve_org_id
from app.core import db
from app.core.settings import settings
from app.tools import camofox

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/studio/kb", tags=["studio-kb"])

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "you", "your", "with", "our", "are", "can", "that", "this", "have", "from", "what", "who", "how"}


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]


async def _org(request: Request) -> str:
    return await resolve_org_id(request)


class TextIn(BaseModel):
    title: str
    content: str


class UrlIn(BaseModel):
    url: str


def _public(row: dict[str, Any]) -> dict[str, Any]:
    content = row.get("content") or ""
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "source": row.get("source"),
        "chars": len(content),
        "preview": content[:160],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def _insert(org_id: str, title: str, source: str, content: str) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO kb_entries (org_id, title, source, content) VALUES ($1,$2,$3,$4) "
            "RETURNING id, title, source, content, created_at",
            org_id, title[:160], source, content[:20000],
        )
    return _public(dict(row))


@router.get("")
async def list_kb(request: Request) -> dict[str, Any]:
    org = await _org(request)
    pool = await db.get_pool()
    if pool is None:
        return {"entries": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, source, content, created_at FROM kb_entries WHERE org_id = $1 ORDER BY created_at DESC",
            org,
        )
    return {"entries": [_public(dict(r)) for r in rows]}


@router.post("/text")
async def add_text(body: TextIn, request: Request) -> dict[str, Any]:
    if len(body.content.strip()) < 10:
        raise HTTPException(status_code=400, detail="Add a bit more content.")
    entry = await _insert(await _org(request), body.title.strip() or "Note", "text", body.content.strip())
    return {"entry": entry}


@router.post("/url")
async def add_url(body: UrlIn, request: Request) -> dict[str, Any]:
    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Enter a full URL (https://…).")
    try:
        page = await camofox.read_page(url, respect_robots=False, attempts=2, scrolls=1)
    except Exception as exc:  # noqa: BLE001
        logger.info("kb url read failed: %s", exc)
        page = None
    text = (page or {}).get("snapshot") or ""
    if len(text.strip()) < 40:
        raise HTTPException(status_code=422, detail="Couldn't read enough from that page — paste the text instead.")
    title = url.replace("https://", "").replace("http://", "").split("/")[0]
    entry = await _insert(await _org(request), title, "url", text.strip())
    return {"entry": entry}


@router.delete("/{entry_id}")
async def delete_kb(entry_id: str, request: Request) -> dict[str, bool]:
    org = await _org(request)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM kb_entries WHERE id = $1 AND org_id = $2", uuid.UUID(entry_id), org
        )
    return {"removed": result.endswith("1")}


# --------------------------------------------------------------------------- #
# Retrieval — importable, injected into agent runs + inbox replies
# --------------------------------------------------------------------------- #


async def kb_context(org_id: str, query: str, *, max_chars: int = 1800) -> str:
    """Most-relevant KB snippets for a query, as a grounding block (or "")."""
    pool = await db.get_pool()
    if pool is None:
        return ""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT title, content FROM kb_entries WHERE org_id = $1", org_id
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("kb_context load failed: %s", exc)
        return ""
    if not rows:
        return ""

    q = set(_terms(query))
    if not q:
        # No usable query terms — still ground with the newest entry.
        q = set()
    scored: list[tuple[float, str, str]] = []
    for r in rows:
        content = r["content"] or ""
        terms = _terms(content)
        if not terms:
            continue
        overlap = sum(1 for t in terms if t in q) if q else 0
        # Normalise a little by length so a huge page doesn't always win.
        score = overlap / (1 + len(terms) ** 0.5) if q else 0.0
        scored.append((score, r["title"], content))
    if not scored:
        return ""
    scored.sort(key=lambda s: s[0], reverse=True)

    # If nothing matched the query, fall back to the first entries so agents are
    # still grounded in the business's info.
    picked = [s for s in scored if s[0] > 0] or scored[:2]
    out: list[str] = []
    used = 0
    for _score, title, content in picked:
        snippet = content[: max(300, max_chars // max(1, len(picked)))]
        block = f"[{title}]\n{snippet}"
        if used + len(block) > max_chars:
            block = block[: max_chars - used]
        out.append(block)
        used += len(block)
        if used >= max_chars:
            break
    return "\n\n".join(out)
