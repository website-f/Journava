"""Group expense split — shared trip costs and a minimal-transaction settle-up.

Each expense records who paid and who it's shared among; balances net out per
person and a greedy settle-up returns the fewest "A pays B" transfers. Scoped to
the trip owner, grouped by the same trip_key the checklist uses.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/trip/expenses", tags=["expenses"])


class ExpenseIn(BaseModel):
    trip_key: str
    description: str
    amount: float
    currency: str = "MYR"
    paid_by: str
    shared_by: list[str] = []


def _user_id(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


def _row(r: dict[str, Any]) -> dict[str, Any]:
    shared = r.get("shared_by")
    if isinstance(shared, str):
        import json

        try:
            shared = json.loads(shared)
        except ValueError:
            shared = []
    return {
        "id": str(r["id"]),
        "description": r["description"],
        "amount": float(r["amount"]),
        "currency": r["currency"],
        "paid_by": r["paid_by"],
        "shared_by": shared or [],
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


def _settle(expenses: list[dict[str, Any]]) -> dict[str, Any]:
    """Net balances per person + the minimal set of transfers to settle up.

    Positive balance = the group owes this person; negative = they owe the group.
    """
    balances: dict[str, float] = {}
    currency = "MYR"
    for e in expenses:
        currency = e.get("currency") or currency
        payer = (e.get("paid_by") or "").strip()
        shared = [s.strip() for s in (e.get("shared_by") or []) if s and s.strip()]
        if not payer or not shared:
            continue
        amount = float(e.get("amount") or 0)
        share = amount / len(shared)
        balances[payer] = balances.get(payer, 0.0) + amount
        for p in shared:
            balances[p] = balances.get(p, 0.0) - share

    # Greedy settle-up: match biggest debtor to biggest creditor.
    debtors = sorted(([n, -b] for n, b in balances.items() if b < -0.01), key=lambda x: x[1], reverse=True)
    creditors = sorted(([n, b] for n, b in balances.items() if b > 0.01), key=lambda x: x[1], reverse=True)
    transfers: list[dict[str, Any]] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        pay = min(debtors[i][1], creditors[j][1])
        transfers.append({"from": debtors[i][0], "to": creditors[j][0], "amount": round(pay, 2), "currency": currency})
        debtors[i][1] -= pay
        creditors[j][1] -= pay
        if debtors[i][1] <= 0.01:
            i += 1
        if creditors[j][1] <= 0.01:
            j += 1

    return {
        "balances": [{"name": n, "net": round(b, 2), "currency": currency} for n, b in sorted(balances.items())],
        "settlements": transfers,
        "total": round(sum(float(e.get("amount") or 0) for e in expenses), 2),
        "currency": currency,
    }


@router.get("")
async def list_expenses(request: Request, trip_key: str) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"expenses": [], "balances": [], "settlements": [], "total": 0}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM trip_expenses WHERE (user_id = $1 OR $1 IS NULL) AND trip_key = $2 "
            "ORDER BY created_at",
            uuid.UUID(uid) if uid else None, trip_key,
        )
    expenses = [_row(dict(r)) for r in rows]
    return {"expenses": expenses, **_settle(expenses)}


@router.post("")
async def add_expense(body: ExpenseIn, request: Request) -> dict[str, Any]:
    import json

    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    shared = [s.strip() for s in body.shared_by if s and s.strip()] or [body.paid_by.strip()]
    async with pool.acquire() as conn:
        await conn.fetchrow(
            """INSERT INTO trip_expenses (user_id, trip_key, description, amount, currency, paid_by, shared_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
            uuid.UUID(uid) if uid else None, body.trip_key, body.description.strip()[:200],
            body.amount, body.currency, body.paid_by.strip()[:80], json.dumps(shared),
        )
    return await list_expenses(request, body.trip_key)


@router.delete("/{expense_id}")
async def delete_expense(expense_id: str, request: Request, trip_key: str) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM trip_expenses WHERE id = $1 AND (user_id = $2 OR $2 IS NULL)",
            uuid.UUID(expense_id), uuid.UUID(uid) if uid else None,
        )
    return await list_expenses(request, trip_key)
