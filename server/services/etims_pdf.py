"""
services/etims_pdf.py — eTIMS rendering fragments + the KRA Monthly Report PDF.

THE RENDERING CONTRACT (spec §3)
--------------------------------
Every function here returns an EMPTY STRING when the conditions aren't met, and
callers embed the result unconditionally. That shape is deliberate: it makes
"render nothing" the natural outcome of a missing PIN, a disabled property or an
unrecorded invoice, rather than something each of the four document templates
has to remember to special-case.

Nothing here ever emits a placeholder, a dash, an empty table cell, or a
"pending" state. A payment with no eTIMS number produces no eTIMS block at all,
even on a property where the feature is switched on.
"""

from __future__ import annotations

import base64
from html import escape
from io import BytesIO

# QR size on the page. ~22mm reads reliably from a printed receipt without
# crowding the footer.
_QR_MM = 22


def qr_data_uri(url: str | None) -> str | None:
    """
    A KRA verification URL as an embeddable PNG data URI.

    The URL is encoded verbatim — SahilPay does not build, shorten or validate
    KRA links, it only reproduces what the user pasted. Returns None on any
    failure so a bad paste can never break a receipt.
    """
    if not url:
        return None
    try:
        import qrcode

        image = qrcode.make(url)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:
        return None


def receipt_block_html(payment, property_obj, tenant) -> str:
    """
    The compact eTIMS block near a receipt's footer (§3.1).

    Returns "" unless the property has opted in AND enabled receipts AND the
    payment actually carries a number. There is deliberately no "pending"
    rendering: an invoice the landlord hasn't issued yet is simply absent.
    """
    if property_obj is None or not property_obj.etims_shows("receipts"):
        return ""
    if not payment.etims_invoice_number:
        return ""

    rows = []
    seller_pin = property_obj.effective_kra_pin
    if seller_pin:
        rows.append(f"<div><span class='k'>Seller KRA PIN:</span> {escape(seller_pin)}</div>")
    buyer_pin = getattr(tenant, "kra_pin", None) if tenant else None
    if buyer_pin:
        rows.append(f"<div><span class='k'>Buyer KRA PIN:</span> {escape(buyer_pin)}</div>")

    issued = ""
    if payment.etims_issued_at:
        issued = f" &middot; issued {payment.etims_issued_at.strftime('%d %b %Y')}"
    rows.append(
        f"<div><span class='k'>eTIMS Invoice No:</span> "
        f"{escape(payment.etims_invoice_number)}{issued}</div>"
    )

    qr = qr_data_uri(payment.etims_qr_url)
    qr_html = (
        f"<img src='{qr}' alt='KRA verification QR' "
        f"style='width:{_QR_MM}mm;height:{_QR_MM}mm;'/>"
        if qr else ""
    )

    return (
        "<div style='margin-top:14px;padding-top:8px;border-top:1px solid #e2e2e8;"
        "display:flex;justify-content:space-between;align-items:flex-start;gap:12px;"
        "font-size:10px;color:#3a3a52;'>"
        "<style>.etims .k{color:#6b6b80;}</style>"
        f"<div class='etims'>{''.join(rows)}</div>{qr_html}"
        "</div>"
    )


def statement_footer_pins_html(*pins: tuple[str, str | None]) -> str:
    """
    Footer PIN lines for a statement (§3.2, §3.3), e.g.
    ("Owner KRA PIN", pin), ("Managing agent KRA PIN", pm_pin).
    Pairs with no value contribute nothing.
    """
    parts = [f"{escape(label)}: {escape(value)}"
             for label, value in pins if value]
    if not parts:
        return ""
    return (
        "<div style='margin-top:10px;font-size:10px;color:#6b6b80;'>"
        + " &middot; ".join(parts) + "</div>"
    )


def include_etims_column(rows: list, properties_by_id: dict, checkbox: bool) -> bool:
    """
    Whether a statement should carry the slim "eTIMS No." column (§3.2).

    True only when the caller ticked the box AND at least one line in the
    document actually has a number. A column of blanks is exactly the kind of
    "you haven't done this" nagging the whole feature is built to avoid, so a
    statement where nothing was recorded omits the column entirely.
    """
    if not checkbox:
        return False
    for row in rows:
        number = row.get("etims_invoice_number") if isinstance(row, dict) \
            else getattr(row, "etims_invoice_number", None)
        if not number:
            continue
        property_id = row.get("property_id") if isinstance(row, dict) \
            else getattr(row, "property_id", None)
        prop = properties_by_id.get(property_id)
        if prop is not None and prop.etims_shows("statements"):
            return True
    return False


# ---------------------------------------------------------------------------
# KRA Monthly Report PDF (§4.3)
# ---------------------------------------------------------------------------

def render_kra_monthly_pdf(landlord_id: int, report: dict) -> bytes:
    """The filing aid as a branded PDF, using the same letterhead as every report."""
    from extensions import db
    from models import Landlord
    from services.report_builder import (
        build_meta, _letterhead_html, _platform_credit_html, _REPORT_STYLE,
    )
    from utils import render_pdf

    landlord = db.session.get(Landlord, landlord_id)
    meta = build_meta(landlord, report_title="KRA Monthly Rental Income Report",
                      period=report["month"])

    sections = []
    for group in report["groups"]:
        pin = (f"<div class='muted'>KRA PIN: {escape(group['kra_pin'])}</div>"
               if group["kra_pin"] else "")
        properties = ", ".join(escape(p["name"]) for p in group["properties"])

        lines = "".join(
            "<tr>"
            f"<td>{escape(row['date'] or '')}</td>"
            f"<td>{escape(row['tenant'] or '')}</td>"
            f"<td>{escape(row['unit'] or '')}</td>"
            f"<td>{escape(row['property'] or '')}</td>"
            f"<td style='text-align:right'>{escape(row['amount'])}</td>"
            f"<td>{escape(row['etims_invoice_number'] or '')}</td>"
            "</tr>"
            for row in group["appendix"]
        )

        sections.append(
            "<div style='margin-top:22px;'>"
            f"<h2 style='margin-bottom:2px;'>{escape(group['name'])}</h2>"
            f"{pin}"
            f"<div class='muted'>{properties}</div>"
            "<table style='margin-top:10px;'>"
            "<thead><tr><th>Date</th><th>Tenant</th><th>Unit</th><th>Property</th>"
            "<th style='text-align:right'>Rent received</th>"
            "<th>eTIMS invoice no.</th></tr></thead>"
            f"<tbody>{lines}</tbody>"
            "<tfoot>"
            "<tr class='total-row'><td colspan='4'>Gross rent received (cash basis)</td>"
            f"<td style='text-align:right'>KES {escape(group['gross_rent_received'])}</td><td></td></tr>"
            "<tr class='total-row'><td colspan='4'>Monthly Rental Income tax @ 7.5%</td>"
            f"<td style='text-align:right'>KES {escape(group['mri_due'])}</td><td></td></tr>"
            "</tfoot></table>"
            f"<div class='muted' style='margin-top:6px;'>{escape(group['coverage_line'])}</div>"
            "</div>"
        )

    body = (
        _letterhead_html(meta)
        + f"<div class='muted'>Period: {escape(report['period_start'])} to "
          f"{escape(report['period_end'])} &middot; cash basis (rent received in "
          f"the month, including arrears cleared this month)</div>"
        + "".join(sections)
        + "<div style='margin-top:26px;padding:10px;background:#f4f4f8;border-radius:4px;'>"
          f"<strong>Total gross rent received: KES {escape(report['totals']['gross_rent_received'])}</strong><br/>"
          f"<strong>Total indicative MRI @ 7.5%: KES {escape(report['totals']['mri_due'])}</strong><br/>"
          f"<span class='muted'>{escape(report['filing_note'])}</span></div>"
        + f"<div class='muted' style='margin-top:14px;font-size:9px;'>{escape(report['disclaimer'])}</div>"
        + _platform_credit_html()
    )

    html = (f"<!doctype html><html><head><meta charset='utf-8'>{_REPORT_STYLE}"
            f"</head><body>{body}</body></html>")
    return render_pdf(html)
