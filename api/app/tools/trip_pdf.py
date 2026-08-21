"""Compile a produced trip plan into a branded PDF (reportlab, pure-Python).

Used by the agency "send to client" flow and (later) hotel receipts. Reads the
same plan-results dict the consumer UI renders and lays out the key sections:
header, flights, stays, day-by-day itinerary, budget, and safety/visa notes.
Best-effort per section — a missing agent just drops its block.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

logger = logging.getLogger("journava")

_BRAND = colors.HexColor("#0F766E")
_MUTED = colors.HexColor("#64748B")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=_BRAND, fontSize=22, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], textColor=_MUTED, fontSize=10, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=_BRAND, fontSize=13, spaceBefore=12, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=10, leading=14, alignment=TA_LEFT),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=9, textColor=_MUTED, leading=12),
    }


def _esc(text: Any) -> str:
    s = str(text or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(opt: dict[str, Any]) -> str:
    amt, cur = opt.get("price_amount"), opt.get("price_currency") or ""
    if amt is None:
        return ""
    try:
        return f"{cur} {float(amt):,.0f}"
    except (TypeError, ValueError):
        return f"{cur} {amt}"


def build_trip_pdf(results: dict[str, Any], *, title: str = "Your Trip", agency: str = "Journava") -> bytes:
    """Render the plan into PDF bytes."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm)
    flow: list[Any] = []

    chief = (results.get("chief") or {}).get("data") or {}
    resolved = chief.get("resolved_request") or {}
    destination = chief.get("destination") or resolved.get("destination") or ""
    flow.append(Paragraph(_esc(title), st["title"]))
    meta_bits = [b for b in [destination, resolved.get("start_date"), f"prepared by {agency}"] if b]
    flow.append(Paragraph(_esc(" · ".join(str(m) for m in meta_bits)), st["sub"]))
    flow.append(HRFlowable(width="100%", color=_BRAND, thickness=1.2, spaceAfter=6))

    def section(heading: str, body_items: list[Any]) -> None:
        if not body_items:
            return
        flow.append(Paragraph(heading, st["h2"]))
        flow.extend(body_items)

    # Flights
    flights = (results.get("flight") or {}).get("options") or []
    if flights:
        rows = []
        for o in flights[:5]:
            price = _money(o)
            book = " · bookable" if o.get("bookable") else ""
            rows.append(ListItem(Paragraph(f"{_esc(o.get('title'))} — <b>{_esc(price)}</b>{book}", st["body"])))
        section("Flights", [ListFlowable(rows, bulletType="bullet", start="•")])

    # Stays
    hotels = (results.get("hotel") or {}).get("options") or []
    if hotels:
        rows = []
        for o in hotels[:5]:
            price = _money(o)
            tag = " · direct (no OTA fee)" if o.get("source") == "supplier" else ""
            rows.append(ListItem(Paragraph(f"{_esc(o.get('title'))} — <b>{_esc(price)}</b>{tag}", st["body"])))
        section("Where you'll stay", [ListFlowable(rows, bulletType="bullet", start="•")])

    # Itinerary
    items = (results.get("itinerary") or {}).get("items") or []
    if items:
        by_day: dict[int, list[dict[str, Any]]] = {}
        for it in items:
            by_day.setdefault(int(it.get("day_index") or 0), []).append(it)
        blocks: list[Any] = []
        for day in sorted(by_day):
            blocks.append(Paragraph(f"<b>Day {day + 1}</b>", st["body"]))
            lines = []
            for it in by_day[day]:
                when = it.get("starts_at") or ""
                lines.append(ListItem(Paragraph(f"{_esc(when)}  {_esc(it.get('title'))}", st["small"])))
            blocks.append(ListFlowable(lines, bulletType="bullet", start="–"))
            blocks.append(Spacer(1, 4))
        section("Day-by-day itinerary", blocks)

    # Budget
    budget = (results.get("budget") or {}).get("data") or {}
    if budget:
        total = budget.get("total") or budget.get("estimated_total") or budget.get("grand_total")
        cur = budget.get("currency") or resolved.get("budget_currency") or ""
        if total is not None:
            section("Budget", [Paragraph(f"Estimated total: <b>{_esc(cur)} {_esc(total)}</b>", st["body"])])

    # Safety / visa
    notes: list[Any] = []
    risk = (results.get("risk_advisory") or {}).get("data") or {}
    if risk.get("advisory_text"):
        notes.append(Paragraph(f"<b>Safety:</b> {_esc(risk.get('safety_level', ''))} — {_esc(risk['advisory_text'])}", st["small"]))
    entry = (results.get("entry") or {}).get("data") or {}
    if entry.get("visa_required") is not None:
        notes.append(Paragraph(f"<b>Entry:</b> {'visa required' if entry.get('visa_required') else 'visa-free / on arrival'}", st["small"]))
    section("Good to know", notes)

    flow.append(Spacer(1, 12))
    flow.append(HRFlowable(width="100%", color=_MUTED, thickness=0.5, spaceAfter=4))
    flow.append(Paragraph(f"Generated by {agency} on Journava — an AI travel platform.", st["small"]))

    if len(flow) <= 3:  # only the header rendered → nothing useful
        flow.append(Paragraph("This plan is still being prepared.", st["body"]))

    doc.build(flow)
    return buf.getvalue()


def build_receipt_pdf(txn: dict[str, Any], *, org: str = "Journava") -> bytes:
    """A clean, well-formatted receipt for one finance transaction."""
    from reportlab.platypus import Table, TableStyle

    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=20 * mm, rightMargin=20 * mm)
    flow: list[Any] = []

    kind = str(txn.get("kind") or "income")
    is_refund = kind == "refund"
    heading = "REFUND RECEIPT" if is_refund else "RECEIPT"
    amount = float(txn.get("amount") or 0)
    cur = txn.get("currency") or "MYR"
    sign = "-" if is_refund else ""

    flow.append(Paragraph(_esc(org), st["title"]))
    flow.append(Paragraph(heading, st["sub"]))
    flow.append(HRFlowable(width="100%", color=_BRAND, thickness=1.2, spaceAfter=8))

    rid = str(txn.get("id") or "")[:8].upper()
    meta = [
        ["Receipt no.", rid],
        ["Date", str(txn.get("created_at") or "")[:19].replace("T", " ")],
        ["Type", kind.title()],
        ["Status", str(txn.get("status") or "completed").title()],
        ["Reference", str(txn.get("reference") or "—")],
        ["Party", str(txn.get("counterparty") or "—")],
    ]
    t = Table(meta, colWidths=[35 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 10))

    line = Table(
        [["Description", "Amount"], [_esc(txn.get("description") or kind.title()), f"{sign}{cur} {amount:,.2f}"]],
        colWidths=[120 * mm, 35 * mm],
    )
    line.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 11),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _MUTED),
        ("LINEABOVE", (0, 1), (-1, 1), 0.25, colors.HexColor("#E2E8F0")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#B91C1C") if is_refund else _BRAND),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flow.append(line)
    flow.append(Spacer(1, 14))
    flow.append(HRFlowable(width="100%", color=_MUTED, thickness=0.5, spaceAfter=4))
    flow.append(Paragraph(f"Issued by {_esc(org)} via Journava. This is a computer-generated receipt.", st["small"]))

    doc.build(flow)
    return buf.getvalue()
