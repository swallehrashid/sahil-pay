"""
services/receipt_service.py — detailed, branded payment receipts.

A tenant receipt is only issued for a CONFIRMED payment. It shows the same
breakdown the landlord's reports use — a Rent section (rent due + balance
carried forward), a Utilities section (each utility charged + its balance
carried forward), then Total due, Amount paid (this receipt) and Balance
remaining — under the landlord's full letterhead (logo + company + address),
exactly like the landlord's report documents.

build_receipt(payment)      -> dict  (for on-screen "view before download")
render_receipt_pdf(payment) -> bytes (branded PDF, same letterhead as reports)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape

from utils import render_pdf
from services.allocation_service import categorize_invoice
from services.report_builder import build_meta, _letterhead_html, _signature_html, _platform_credit_html, _REPORT_STYLE


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_receipt(payment) -> dict:
    """Structured receipt data with rent / utilities / other breakdown."""
    tenant   = payment.tenant
    landlord = payment.landlord
    unit     = payment.unit
    property = payment.property or (unit.property if unit else None)
    ref_date = payment.payment_date or date.today()

    # What this specific payment was allocated to.
    alloc_by_invoice = {
        a.invoice_id: (a.amount_allocated or Decimal("0"))
        for a in payment.payment_allocations
    }

    sections = {"rent": [], "utilities": [], "other": []}
    for inv in (tenant.invoices if tenant else []):
        if inv.is_deleted:
            continue
        paid_here = alloc_by_invoice.get(inv.id, Decimal("0"))
        balance_cf = (inv.total_amount or Decimal("0")) - (inv.amount_paid or Decimal("0"))
        amount_due = balance_cf + paid_here          # what was owed entering this receipt
        # Skip invoices irrelevant to this receipt (nothing owed, nothing paid here).
        if amount_due <= 0 and paid_here <= 0:
            continue

        cat = categorize_invoice(inv, ref_date)       # rent_cf/current, utilities_*, other
        group = "rent" if cat.startswith("rent") else "utilities" if cat.startswith("utilities") else "other"
        carried = cat.endswith("_cf")
        label = inv.title or inv.invoice_type or "Charge"
        if carried:
            label = f"{label} (balance b/f)"

        sections[group].append({
            "description":       label,
            "invoice_number":    inv.invoice_number,
            "carried_forward":   carried,
            "amount_due":        _f(amount_due),
            "paid_this_receipt": _f(paid_here),
            "balance_cf":        _f(balance_cf),
        })

    def _subtotal(rows, key):
        return round(sum(r[key] for r in rows), 2)

    total_due       = round(sum(_subtotal(rows, "amount_due") for rows in sections.values()), 2)
    total_allocated = round(sum(_subtotal(rows, "paid_this_receipt") for rows in sections.values()), 2)
    amount_paid     = _f(payment.amount)
    advance_credit  = round(max(0.0, amount_paid - total_allocated), 2)
    balance_remaining = round(sum(_subtotal(rows, "balance_cf") for rows in sections.values()), 2)

    return {
        "payment_ref":    payment.payment_ref,
        "payment_date":   str(payment.payment_date) if payment.payment_date else None,
        "status":         payment.status,
        "method":         payment.payment_method or payment.source,
        "reference":      payment.mpesa_reference or payment.till_number or payment.payment_ref,
        "tenant_name":    f"{tenant.first_name} {tenant.last_name}".strip() if tenant else None,
        "unit_name":      unit.name if unit else None,
        "property_name":  property.name if property else None,
        "currency":       landlord.currency if landlord else "KES",
        "landlord": {
            "company_name":    landlord.company_name if landlord else None,
            "company_address": getattr(landlord, "company_address", None) if landlord else None,
            "logo_url":        getattr(landlord, "logo_url", None) if landlord else None,
        },
        "rent_section":      sections["rent"],
        "utilities_section": sections["utilities"],
        "other_section":     sections["other"],
        "rent_due":          _subtotal(sections["rent"], "amount_due"),
        "utilities_due":     _subtotal(sections["utilities"], "amount_due"),
        "other_due":         _subtotal(sections["other"], "amount_due"),
        "total_due":         total_due,
        "amount_paid":       amount_paid,
        "advance_credit":    advance_credit,
        "balance_remaining": balance_remaining,
    }


def _money(value, currency="KES") -> str:
    return f"{currency} {_f(value):,.2f}"


def _section_html(title: str, rows: list, currency: str) -> str:
    if not rows:
        return ""
    body = "".join(
        f"<tr><td>{escape(r['description'])}</td>"
        f"<td class='right'>{_money(r['amount_due'], currency)}</td>"
        f"<td class='right'>{_money(r['paid_this_receipt'], currency)}</td>"
        f"<td class='right'>{_money(r['balance_cf'], currency)}</td></tr>"
        for r in rows
    )
    return (
        f"<h2>{escape(title)}</h2>"
        "<table><thead><tr>"
        "<th>Item</th><th class='right'>Amount due</th>"
        "<th class='right'>Paid (this receipt)</th><th class='right'>Balance c/f</th>"
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def render_receipt_pdf(payment) -> bytes:
    """Branded receipt PDF — same letterhead/signature as landlord reports."""
    data     = build_receipt(payment)
    landlord = payment.landlord
    currency = data["currency"]

    subject_bits = [b for b in [data.get("tenant_name"), data.get("unit_name"), data.get("property_name")] if b]
    meta = build_meta(
        landlord,
        report_title="Payment Receipt",
        subject=" · ".join(subject_bits),
        property_name=data.get("property_name"),
        extra={"period": data.get("payment_date")},
    )

    info = (
        "<table class='kv'><tbody>"
        f"<tr><td>Receipt no.</td><td class='right'>{escape(data['payment_ref'])}</td></tr>"
        f"<tr><td>Date</td><td class='right'>{escape(data.get('payment_date') or '')}</td></tr>"
        f"<tr><td>Received from</td><td class='right'>{escape(data.get('tenant_name') or '')}</td></tr>"
        f"<tr><td>Method</td><td class='right'>{escape(str(data.get('method') or '—'))}</td></tr>"
        f"<tr><td>Reference</td><td class='right'>{escape(str(data.get('reference') or '—'))}</td></tr>"
        "</tbody></table>"
    )

    sections_html = (
        _section_html("Rent", data["rent_section"], currency)
        + _section_html("Utilities", data["utilities_section"], currency)
        + _section_html("Other charges", data["other_section"], currency)
    )

    advance_row = (
        f"<tr><td>Advance / credit</td><td class='right'>{_money(data['advance_credit'], currency)}</td></tr>"
        if data["advance_credit"] > 0 else ""
    )
    totals = (
        "<h2>Summary</h2><table class='kv'><tbody>"
        f"<tr><td>Total amount due</td><td class='right'>{_money(data['total_due'], currency)}</td></tr>"
        f"<tr class='total-row'><td>Amount paid (this receipt)</td><td class='right'>{_money(data['amount_paid'], currency)}</td></tr>"
        f"{advance_row}"
        f"<tr class='total-row'><td>Balance remaining</td><td class='right'>{_money(data['balance_remaining'], currency)}</td></tr>"
        "</tbody></table>"
    )

    body = (
        f"{_letterhead_html(meta)}{info}{sections_html}{totals}"
        "<p class='muted'>Thank you for your payment.</p>"
        f"{_signature_html(meta)}{_platform_credit_html()}"
    )
    html = f"<!doctype html><html><head><meta charset='utf-8'>{_REPORT_STYLE}</head><body>{body}</body></html>"
    return render_pdf(html)
