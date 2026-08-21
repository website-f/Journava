"""Finance ledger — one page for every money movement (Track B).

Bookings (income), refunds (from the escrow adjudicator), payouts and fees all
post here as `finance_transactions`. The console renders them as a filterable,
sortable table with an AI summary, and every row has a well-formatted receipt PDF.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db, llm
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/finance", tags=["finance"])

_KINDS = {"income", "refund", "payout", "fee", "adjustment"}


async def record(
    *,
    org_id: str | None,
    kind: str,
    amount: float,
    currency: str = "MYR",
    reference: str | None = None,
    counterparty: str | None = None,
    description: str | None = None,
    status: str = "completed",
) -> str | None:
    """Post a transaction to the ledger. Best-effort — never breaks the caller."""
    if not org_id or kind not in _KINDS:
        return None
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            txid = await conn.fetchval(
                """INSERT INTO finance_transactions
                       (org_id, kind, amount, currency, status, reference, counterparty, description)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                uuid.UUID(org_id), kind, round(float(amount), 2), currency, status,
                reference, counterparty, description,
            )
        return str(txid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("finance.record failed: %s", exc)
        return None


def _tx(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "status": row["status"],
        "reference": row["reference"],
        "counterparty": row["counterparty"],
        "description": row["description"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }


async def _fetch(org_id: str, *, kind: str | None, status: str | None, q: str | None, days: int | None, limit: int) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None:
        return []
    clauses = ["org_id = $1"]
    args: list[Any] = [uuid.UUID(org_id)]
    if kind and kind in _KINDS:
        args.append(kind)
        clauses.append(f"kind = ${len(args)}")
    if status:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if q:
        args.append(f"%{q}%")
        clauses.append(f"(counterparty ILIKE ${len(args)} OR description ILIKE ${len(args)} OR reference ILIKE ${len(args)})")
    if days:
        clauses.append(f"created_at >= now() - interval '{int(days)} days'")
    args.append(limit)
    sql = f"SELECT * FROM finance_transactions WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ${len(args)}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [_tx(dict(r)) for r in rows]


class TxQuery(BaseModel):
    kind: str | None = None
    status: str | None = None
    q: str | None = None
    days: int | None = None


@router.get("/transactions")
async def transactions(
    kind: str | None = None, status: str | None = None, q: str | None = None,
    days: int | None = None, limit: int = 200, agency: dict = Depends(require_agency),
) -> dict[str, Any]:
    rows = await _fetch(agency["org_id"], kind=kind, status=status, q=q, days=days, limit=limit)
    return {"transactions": rows}


def _summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    income = sum(r["amount"] for r in rows if r["kind"] == "income")
    refunds = sum(r["amount"] for r in rows if r["kind"] == "refund")
    payouts = sum(r["amount"] for r in rows if r["kind"] in ("payout", "fee"))
    currency = rows[0]["currency"] if rows else "MYR"
    return {
        "currency": currency,
        "income": round(income, 2),
        "refunds": round(refunds, 2),
        "payouts": round(payouts, 2),
        "net": round(income - refunds - payouts, 2),
        "count": len(rows),
        "by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in _KINDS},
    }


@router.get("/summary")
async def summary(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    rows = await _fetch(agency["org_id"], kind=None, status=None, q=None, days=None, limit=1000)
    return _summarise(rows)


_AI_SYSTEM = """You are a finance analyst for a hotel/agency. Given a summary and \
recent transactions, write a short, plain-language readout an owner would value: \
what came in, what went out, the net, notable items, and one actionable suggestion.

Respond ONLY as JSON:
{"summary": "3-4 sentences", "highlights": ["short bullet", ...max 5]}"""


@router.post("/ai-summary")
async def ai_summary(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    rows = await _fetch(agency["org_id"], kind=None, status=None, q=None, days=None, limit=200)
    s = _summarise(rows)
    if not rows:
        return {"summary": "No transactions yet — take a booking and it appears here.", "highlights": []}
    sample = [{"kind": r["kind"], "amount": r["amount"], "party": r["counterparty"], "desc": r["description"]} for r in rows[:25]]
    user = f"Summary: {json.dumps(s)}\nRecent: {json.dumps(sample, default=str)}"
    out = {"summary": f"{s['currency']} {s['income']:,.0f} in, {s['refunds']:,.0f} refunded — net {s['currency']} {s['net']:,.0f} across {s['count']} transactions.", "highlights": []}
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _AI_SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="finance",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            out["summary"] = str(data.get("summary") or out["summary"])
            out["highlights"] = [str(h) for h in (data.get("highlights") or [])][:5]
    except Exception as exc:  # noqa: BLE001
        logger.info("finance ai-summary fell back: %s", exc)
    return {**out, "metrics": s}


@router.get("/receipt/{txn_id}")
async def receipt(txn_id: str, agency: dict = Depends(require_agency)) -> Response:
    from app.tools import trip_pdf

    pool = await db.get_pool()
    if pool is None:
        return Response("database unavailable", status_code=503)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM finance_transactions WHERE id = $1 AND org_id = $2",
            uuid.UUID(txn_id), uuid.UUID(agency["org_id"]),
        )
    if not row:
        return Response("not found", status_code=404)
    pdf = trip_pdf.build_receipt_pdf(_tx(dict(row)), org=agency.get("org_name") or "Journava")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="receipt-{txn_id[:8]}.pdf"'},
    )
