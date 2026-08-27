"""Compile a produced trip plan into a branded PDF (reportlab, pure-Python).

Used by the consumer "offline pass" download and the agency "send to client"
flow. Reads the same plan-results dict the consumer UI renders and lays it out
as a real travel document: a brand cover band, an at-a-glance stat strip,
flights, stays, a day-by-day itinerary (time · title · place · note), a budget
breakdown, and "good to know" notes — with a footer on every page.

Best-effort per section — a missing agent just drops its block. The layout is
built from design tokens (the teal brand, slate ink/muted, subtle surfaces and
elevation) so it reads as designed, not as a default reportlab dump.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("journava")

# --- Palette (design tokens) ------------------------------------------------ #
_BRAND = colors.HexColor("#0F766E")
_BRAND_DARK = colors.HexColor("#115E59")
_BRAND_TINT = colors.HexColor("#E6F3F1")
_INK = colors.HexColor("#0F172A")
_MUTED = colors.HexColor("#64748B")
_FAINT = colors.HexColor("#94A3B8")
_SURFACE = colors.HexColor("#F8FAFC")
_BORDER = colors.HexColor("#E2E8F0")
_SUCCESS = colors.HexColor("#15803D")
_WARN = colors.HexColor("#B45309")
_ON_BRAND = colors.HexColor("#D7EDE9")  # muted text on the brand band

# Page geometry.
_LEFT = _RIGHT = 16 * mm
_TOP = 16 * mm
_BOTTOM = 20 * mm
_CONTENT_W = A4[0] - _LEFT - _RIGHT

_KIND_LABEL = {
    "flight": "Flight",
    "hotel": "Stay",
    "activity": "Activity",
    "meal": "Meal",
    "restaurant": "Meal",
    "transport": "Transport",
}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        # Shared with build_receipt_pdf — keep these keys.
        "title": ParagraphStyle("t", parent=base["Title"], textColor=_BRAND, fontSize=22, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], textColor=_MUTED, fontSize=10, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=_BRAND_DARK, fontName="Helvetica-Bold", fontSize=12.5, spaceBefore=2, spaceAfter=2),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=10, leading=14, textColor=_INK, alignment=TA_LEFT),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=9, textColor=_MUTED, leading=12),
        # Cover band.
        "eyebrow": ParagraphStyle("eb", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, textColor=_ON_BRAND, leading=10),
        "cover_title": ParagraphStyle("ct", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, textColor=colors.white, leading=28, spaceBefore=2, spaceAfter=2),
        "cover_sub": ParagraphStyle("cs", parent=base["Normal"], fontSize=10.5, textColor=_ON_BRAND, leading=14),
        # Stat cards.
        "stat_label": ParagraphStyle("sl", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7, textColor=_MUTED, leading=9),
        "stat_value": ParagraphStyle("sv", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12.5, textColor=_INK, leading=15, spaceBefore=2),
        # Day + itinerary rows.
        "day_num": ParagraphStyle("dn", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=12, textColor=_BRAND_DARK, leading=14),
        "day_date": ParagraphStyle("dd", parent=base["Normal"], fontSize=9, textColor=_MUTED, leading=14, alignment=TA_RIGHT),
        "time": ParagraphStyle("tm", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9.5, textColor=_BRAND, leading=12),
        "item": ParagraphStyle("it", parent=base["Normal"], fontSize=10, textColor=_INK, leading=13),
        "price": ParagraphStyle("pr", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=_INK, leading=13, alignment=TA_RIGHT),
        "note": ParagraphStyle("nt", parent=base["Normal"], fontSize=9.5, textColor=_INK, leading=13, spaceAfter=4),
        "intro": ParagraphStyle("in", parent=base["Normal"], fontSize=10, textColor=_MUTED, leading=14, spaceAfter=2),
    }


_ST = _styles()


def _esc(text: Any) -> str:
    s = str(text or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _money(opt: dict[str, Any]) -> str:
    amt, cur = opt.get("price_amount"), opt.get("price_currency") or ""
    if amt is None:
        return ""
    try:
        return f"{cur} {float(amt):,.0f}".strip()
    except (TypeError, ValueError):
        return f"{cur} {amt}".strip()


def _fmt_amount(amt: Any, cur: str) -> str:
    if amt in (None, 0, "0"):
        return ""
    try:
        return f"{cur} {float(amt):,.0f}".strip()
    except (TypeError, ValueError):
        return f"{cur} {amt}".strip()


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _date_range(start: datetime | None, end: datetime | None) -> str:
    if not start:
        return ""
    if not end or end == start:
        return start.strftime("%d %b %Y")
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.strftime('%d %b %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def _location(details: Any) -> str:
    if not isinstance(details, dict):
        return ""
    for key in ("location", "address", "area", "neighbourhood", "neighborhood", "place", "venue", "where"):
        val = details.get(key)
        if val:
            return str(val)
    return ""


def _section(title: str) -> Table:
    """A section heading with a brand underline — clean, not border-heavy."""
    return Table(
        [[Paragraph(_esc(title), _ST["h2"])]],
        colWidths=[_CONTENT_W],
        style=TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 1.2, _BRAND),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]),
    )


def _stat_card(label: str, value: str, width: float) -> Table:
    return Table(
        [[[Paragraph(_esc(label).upper(), _ST["stat_label"]), Paragraph(_esc(value), _ST["stat_value"])]]],
        colWidths=[width],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.75, _BORDER),
            ("ROUNDEDCORNERS", [8, 8, 8, 8]),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]),
    )


def _stat_strip(stats: list[tuple[str, str]]) -> Table | None:
    stats = [(lbl, val) for lbl, val in stats if val]
    if not stats:
        return None
    gap = 8
    n = len(stats)
    card_w = (_CONTENT_W - gap * (n - 1)) / n
    row: list[Any] = []
    widths: list[float] = []
    for i, (label, value) in enumerate(stats):
        if i:
            row.append("")
            widths.append(gap)
        row.append(_stat_card(label, value, card_w))
        widths.append(card_w)
    return Table(
        [row],
        colWidths=widths,
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]),
    )


def _option_table(rows: list[tuple[str, str]]) -> Table:
    """Two-column option list: rich left cell (title + tags), right-aligned price."""
    price_w = 34 * mm
    data = [[Paragraph(left, _ST["item"]), Paragraph(right, _ST["price"])] for left, right in rows]
    return Table(
        data,
        colWidths=[_CONTENT_W - price_w, price_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, _BORDER),
        ]),
    )


def _day_header(day_index: int, start: datetime | None) -> Table:
    date_txt = ""
    if start:
        date_txt = (start + timedelta(days=max(0, day_index - 1))).strftime("%a, %d %b")
    return Table(
        [[Paragraph(f"Day {day_index}", _ST["day_num"]), Paragraph(_esc(date_txt), _ST["day_date"])]],
        colWidths=[_CONTENT_W * 0.55, _CONTENT_W * 0.45],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _BRAND_TINT),
            ("ROUNDEDCORNERS", [8, 8, 8, 8]),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]),
    )


def _itinerary_day(items: list[dict[str, Any]]) -> Table:
    time_w = 20 * mm
    rows: list[list[Any]] = []
    for it in items:
        starts = str(it.get("starts_at") or "").strip()
        ends = str(it.get("ends_at") or "").strip()
        if starts and ends:
            time_html = f'{_esc(starts)}<br/><font size="7" color="#94A3B8">{_esc(ends)}</font>'
        elif starts:
            time_html = _esc(starts)
        else:
            time_html = '<font color="#CBD5E1">•</font>'

        meta = [_KIND_LABEL.get(str(it.get("kind") or ""), str(it.get("kind") or "").title() or "Stop")]
        loc = _location(it.get("details"))
        if loc:
            meta.append(_esc(loc))
        cost = _fmt_amount(it.get("cost_amount"), str(it.get("cost_currency") or ""))
        if cost:
            meta.append(_esc(cost))
        content = f'<b>{_esc(it.get("title"))}</b>'
        content += f'<br/><font size="8" color="#64748B">{"  ·  ".join(meta)}</font>'
        reason = str(it.get("reasoning") or "").strip()
        if reason:
            content += f'<br/><font size="8" color="#94A3B8">{_esc(reason[:200])}</font>'
        rows.append([Paragraph(time_html, _ST["time"]), Paragraph(content, _ST["item"])])

    return Table(
        rows,
        colWidths=[time_w, _CONTENT_W - time_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, -1), 2),
            ("LEFTPADDING", (1, 0), (1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, _BORDER),
        ]),
    )


def build_trip_pdf(results: dict[str, Any], *, title: str = "Your Trip", agency: str = "Journava") -> bytes:
    """Render the plan into PDF bytes — a designed, offline-ready trip document."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, topMargin=_TOP, bottomMargin=_BOTTOM, leftMargin=_LEFT, rightMargin=_RIGHT,
        title=title, author=agency,
    )
    flow: list[Any] = []

    chief = (results.get("chief") or {}).get("data") or {}
    resolved = chief.get("resolved_request") or {}
    destination = chief.get("destination") or resolved.get("destination") or ""
    start = _parse_date(resolved.get("start_date") or chief.get("start_date"))
    end = _parse_date(resolved.get("end_date") or chief.get("end_date"))
    dest_short = str(destination) or "Your trip"

    generated_on = datetime.now().strftime("%d %b %Y")

    # --- Cover band --------------------------------------------------------- #
    date_range = _date_range(start, end)
    sub_bits = [b for b in [date_range, f"Prepared by {agency}"] if b]
    band_cell = [
        Paragraph("OFFLINE TRIP PASS", _ST["eyebrow"]),
        Spacer(1, 4),
        Paragraph(_esc(destination or title), _ST["cover_title"]),
    ]
    if sub_bits:
        band_cell.append(Paragraph(_esc("  ·  ".join(sub_bits)), _ST["cover_sub"]))
    flow.append(Table(
        [[band_cell]],
        colWidths=[_CONTENT_W],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _BRAND),
            ("ROUNDEDCORNERS", [12, 12, 12, 12]),
            ("LEFTPADDING", (0, 0), (-1, -1), 18),
            ("RIGHTPADDING", (0, 0), (-1, -1), 18),
            ("TOPPADDING", (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ]),
    ))
    flow.append(Spacer(1, 14))

    # --- At a glance -------------------------------------------------------- #
    items = (results.get("itinerary") or {}).get("items") or []
    nights = None
    if start and end:
        nights = max(1, (end - start).days)
    # Prefer the real trip span for "Duration"; fall back to the itinerary's day
    # count when dates are missing (a flights-only lookup, say).
    days_count = (nights + 1) if nights else (max(int(i.get("day_index") or 1) for i in items) if items else None)
    travellers = resolved.get("travellers") or chief.get("travellers")
    budget_data = (results.get("budget") or {}).get("data") or {}
    cur = budget_data.get("currency") or resolved.get("budget_currency") or ""
    budget_total = budget_data.get("spent_estimate") or (budget_data.get("breakdown") or {}).get("total_estimate")

    stats: list[tuple[str, str]] = [
        ("Dates", date_range),
        ("Duration", f"{days_count} days" if days_count else (f"{nights} nights" if nights else "")),
        ("Travellers", str(travellers) if travellers else ""),
        ("Est. budget", _fmt_amount(budget_total, cur)),
    ]
    strip = _stat_strip(stats)
    if strip is not None:
        flow.append(strip)
        flow.append(Spacer(1, 6))

    # A one-line overview if an agent produced a friendly summary.
    intro = ""
    for key in ("concierge", "recommendation", "chief"):
        blk = results.get(key)
        if isinstance(blk, dict) and str(blk.get("summary") or "").strip():
            intro = str(blk["summary"]).strip()
            break
    if intro:
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(_esc(intro[:400]), _ST["intro"]))

    def add_block(block: Table | None, spacer_before: int = 14) -> None:
        if block is None:
            return
        flow.append(Spacer(1, spacer_before))
        flow.append(block)

    # --- Flights ------------------------------------------------------------ #
    flights = (results.get("flight") or {}).get("options") or []
    if flights:
        rows: list[tuple[str, str]] = []
        for o in flights[:6]:
            tags: list[str] = []
            if o.get("bookable"):
                tags.append('<font color="#15803D">Bookable now</font>')
            src = o.get("source")
            if src == "atlas":
                tags.append("Atlas direct")
            elif src in ("camofox", "research"):
                tags.append("Research")
            left = f'<b>{_esc(o.get("title"))}</b>'
            if tags:
                left += f'<br/><font size="8" color="#64748B">{"  ·  ".join(tags)}</font>'
            rows.append((left, f'<b>{_esc(_money(o))}</b>' if _money(o) else ""))
        add_block(KeepTogether([_section("Flights"), Spacer(1, 4), _option_table(rows)]))

    # --- Stays -------------------------------------------------------------- #
    hotels = (results.get("hotel") or {}).get("options") or []
    if hotels:
        rows = []
        for o in hotels[:6]:
            if o.get("source") == "supplier":
                tag = '<font color="#15803D">Direct — no OTA fee</font>'
            elif o.get("provider"):
                tag = f'via {_esc(o.get("provider"))}'
            else:
                tag = ""
            left = f'<b>{_esc(o.get("title"))}</b>'
            if tag:
                left += f'<br/><font size="8" color="#64748B">{tag}</font>'
            rows.append((left, f'<b>{_esc(_money(o))}</b>' if _money(o) else ""))
        add_block(KeepTogether([_section("Where you'll stay"), Spacer(1, 4), _option_table(rows)]))

    # --- Day-by-day itinerary ---------------------------------------------- #
    if items:
        by_day: dict[int, list[dict[str, Any]]] = {}
        for it in items:
            by_day.setdefault(int(it.get("day_index") or 1), []).append(it)
        flow.append(Spacer(1, 14))
        flow.append(_section("Day-by-day itinerary"))
        for day in sorted(by_day):
            flow.append(Spacer(1, 8))
            flow.append(KeepTogether([
                _day_header(day, start),
                Spacer(1, 2),
                _itinerary_day(by_day[day]),
            ]))

    # --- Budget breakdown --------------------------------------------------- #
    breakdown = budget_data.get("breakdown") or {}
    if breakdown or budget_total:
        line_rows: list[list[Any]] = []

        def money_row(label: str, amt: Any, *, strong: bool = False, tone: colors.Color | None = None) -> None:
            txt = _fmt_amount(amt, cur)
            if not txt:
                return
            lbl_style = _ST["body"] if not strong else ParagraphStyle("bstrong", parent=_ST["body"], fontName="Helvetica-Bold")
            val_style = ParagraphStyle("bval", parent=_ST["body"], alignment=TA_RIGHT, fontName="Helvetica-Bold" if strong else "Helvetica", textColor=tone or _INK)
            line_rows.append([Paragraph(_esc(label), lbl_style), Paragraph(_esc(txt), val_style)])

        money_row("Flights", breakdown.get("flights"))
        if breakdown.get("hotels_total"):
            money_row(f"Stays ({breakdown.get('nights', '?')} nights)", breakdown.get("hotels_total"))
        money_row("Activities", breakdown.get("activities"))
        money_row("Estimated total", budget_total or breakdown.get("total_estimate"), strong=True, tone=_BRAND_DARK)

        if line_rows:
            budget_tbl = Table(
                line_rows,
                colWidths=[_CONTENT_W - 40 * mm, 40 * mm],
                style=TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.5, _BORDER),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.75, _BRAND),
                ]),
            )
            extra = []
            cap = budget_data.get("budget_amount")
            if cap:
                if budget_data.get("over_budget"):
                    extra = [Paragraph(
                        f'<font color="#B45309"><b>Over budget</b> by {_esc(_fmt_amount(abs(budget_data.get("remaining") or 0), cur))}</font> '
                        f'· cap {_esc(_fmt_amount(cap, cur))}', _ST["small"])]
                else:
                    extra = [Paragraph(
                        f'Within your {_esc(_fmt_amount(cap, cur))} budget · '
                        f'<font color="#15803D">{_esc(_fmt_amount(budget_data.get("remaining"), cur))} to spare</font>', _ST["small"])]
            add_block(KeepTogether([_section("Budget"), Spacer(1, 4), budget_tbl, *([Spacer(1, 4), *extra] if extra else [])]))

    # --- Good to know ------------------------------------------------------- #
    notes: list[Any] = []
    gtk = [
        ("risk_advisory", "Safety"),
        ("visa", "Entry & visa"),
        ("entry", "Entry & visa"),
        ("weather_risk", "Weather"),
        ("insurance", "Insurance"),
        ("language", "Language"),
        ("emergency", "Emergency"),
    ]
    seen_labels: set[str] = set()
    for key, label in gtk:
        if label in seen_labels:
            continue
        blk = results.get(key)
        if not isinstance(blk, dict):
            continue
        data = blk.get("data") or {}
        text = ""
        if key == "risk_advisory" and data.get("advisory_text"):
            text = f"{data.get('safety_level', '')} — {data['advisory_text']}".strip(" —")
        elif key in ("visa", "entry") and data.get("visa_required") is not None:
            text = "Visa required — arrange before you fly." if data.get("visa_required") else "Visa-free or visa on arrival."
        if not text:
            text = str(blk.get("summary") or "").strip()
        if text:
            seen_labels.add(label)
            notes.append(Paragraph(f'<b>{_esc(label)}:</b> {_esc(text[:280])}', _ST["note"]))
    if notes:
        add_block(KeepTogether([_section("Good to know"), Spacer(1, 4), *notes]))

    if len(flow) <= 4:  # only cover + stats rendered → nothing useful
        flow.append(Spacer(1, 20))
        flow.append(Paragraph("This plan is still being prepared — reopen it once your agents finish.", _ST["body"]))

    def _footer(canvas: Any, doc_: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_BORDER)
        canvas.setLineWidth(0.5)
        y = 13 * mm
        canvas.line(_LEFT, y + 6, A4[0] - _RIGHT, y + 6)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(_LEFT, y, f"{agency} · {dest_short} · saved offline — opens with no signal")
        canvas.drawRightString(A4[0] - _RIGHT, y, f"Page {doc_.page}  ·  {generated_on}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def build_receipt_pdf(txn: dict[str, Any], *, org: str = "Journava") -> bytes:
    """A clean, well-formatted receipt for one finance transaction."""
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
