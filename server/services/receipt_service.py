"""
services/receipt_service.py — detailed, branded payment receipts.

A tenant receipt is only issued for a CONFIRMED payment. It itemises the
receipt at the LINE-ITEM level (not the invoice level), so every distinct
charge the tenant owes — Rent, each utility, and crucially every DEPOSIT — is
its own row with what was owed, what this payment paid toward it, and the
balance carried forward. Deposits (money held, refundable) are surfaced in
their own "Deposits" section so a paid deposit is always visible and never
collapsed into a merged "Rent Deposit, Rent, Water" line.

The SAME PDF is used everywhere a tenant can obtain a receipt — the tenant
portal download, the landlord's "send receipt", the emailed copy, and the
public SMS-link download — so a receipt looks identical however it is fetched.

build_receipt(payment)      -> dict  (for on-screen "view before download")
render_receipt_pdf(payment) -> bytes (branded PDF, same letterhead as reports)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape

from utils import render_pdf
from services.report_builder import build_meta, _letterhead_html, _signature_html, _platform_credit_html, _REPORT_STYLE


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# --- Public receipt link (SMS) ---------------------------------------------
# A signed, expiring token so a tenant can fetch their receipt from an SMS link
# without logging in — no DB column/migration needed (signed with SECRET_KEY).
_RECEIPT_TOKEN_SALT = "sahilpay-receipt-link"
_RECEIPT_TOKEN_MAX_AGE = 60 * 60 * 24 * 30   # 30 days


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_RECEIPT_TOKEN_SALT)


def make_receipt_token(payment) -> str:
    """A signed token encoding the payment id for the public SMS receipt link."""
    return _serializer().dumps({"pid": payment.id})


def verify_receipt_token(token: str):
    """Return the payment id encoded in a valid, unexpired token, else None."""
    from itsdangerous import BadSignature, SignatureExpired
    try:
        data = _serializer().loads(token, max_age=_RECEIPT_TOKEN_MAX_AGE)
        return data.get("pid")
    except (BadSignature, SignatureExpired, Exception):
        return None


def receipt_link_for(payment) -> str:
    """The public URL that, when opened, downloads this receipt and emails a copy.

    Points at the backend public endpoint. In production the app is single-domain
    (the SPA host proxies /api to the backend), so RECEIPT_PUBLIC_BASE_URL — or
    FRONTEND_URL as a fallback — plus the /api path resolves to the backend.
    """
    from flask import current_app
    base = (
        current_app.config.get("RECEIPT_PUBLIC_BASE_URL")
        or current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    ).rstrip("/")
    return f"{base}/api/receipts/public/{make_receipt_token(payment)}"


def _line_group_and_label(li, ref_date):
    """(group, label, is_deposit) for one line item.

    group    one of: rent | utilities | deposits | other
    label    a human row label, using the category's subcategory display name
             ("Water Deposit", "Rent Balance", "Water") when the line carries a
             (category, subcategory); otherwise the line's own item text.
    """
    from models import ChargeCategoryKind, SubCategory

    cat = li.category
    sub = li.subcategory
    is_deposit = sub == SubCategory.deposit.value

    if cat is not None and sub is not None:
        label = cat.subcategory_display().get(sub, li.item)
        if is_deposit:
            group = "deposits"
        elif cat.kind == ChargeCategoryKind.utility.value:
            group = "utilities"
        elif cat.name and cat.name.strip().lower() == "rent":
            group = "rent"
        else:
            group = "other"
        return group, label, is_deposit

    # Un-categorised legacy line: fall back to the line's own text, and infer a
    # deposit from the wording so an old deposit line still lands in Deposits.
    label = li.item or "Charge"
    if "deposit" in (label or "").lower():
        return "deposits", label, True
    return "other", label, False


def build_receipt(payment) -> dict:
    """Structured receipt data, itemised at the line-item level, with a
    dedicated deposits section so a paid deposit is always shown."""
    tenant   = payment.tenant
    landlord = payment.landlord
    unit     = payment.unit
    property = payment.property or (unit.property if unit else None)
    ref_date = payment.payment_date or date.today()

    # What this specific payment paid toward each line item.
    alloc_by_line = {}
    for a in payment.payment_allocations:
        if a.line_item_id is not None:
            alloc_by_line[a.line_item_id] = (a.amount_allocated or Decimal("0"))
    # Legacy allocations that only recorded an invoice (no line_item_id) — keep a
    # per-invoice remainder to attribute across that invoice's lines below.
    alloc_by_invoice_remainder = {}
    for a in payment.payment_allocations:
        if a.line_item_id is None:
            alloc_by_invoice_remainder[a.invoice_id] = (
                alloc_by_invoice_remainder.get(a.invoice_id, Decimal("0"))
                + (a.amount_allocated or Decimal("0"))
            )

    sections = {"rent": [], "utilities": [], "deposits": [], "other": []}

    from models import InvoiceStatus, InvoiceLineItem, Invoice
    invoices = (
        Invoice.query
        .filter_by(tenant_id=tenant.id, is_deleted=False)
        .filter(Invoice.status != InvoiceStatus.void.value)
        .all()
        if tenant else []
    )

    for inv in invoices:
        inv_remainder = alloc_by_invoice_remainder.get(inv.id, Decimal("0"))
        for li in inv.line_items:
            paid_here = alloc_by_line.get(li.id, Decimal("0"))
            # Attribute any legacy invoice-level allocation across the invoice's
            # lines, oldest/open first, so a legacy receipt still itemises.
            if paid_here == 0 and inv_remainder > 0:
                take = min(inv_remainder, li.remaining if li.remaining > 0 else Decimal("0"))
                if take > 0:
                    paid_here = take
                    inv_remainder -= take

            balance_cf = (li.amount or Decimal("0")) - (li.amount_paid or Decimal("0"))
            amount_due = balance_cf + paid_here      # what was owed entering this receipt
            # Skip lines irrelevant to this receipt (nothing owed, nothing paid here).
            if amount_due <= 0 and paid_here <= 0:
                continue

            group, label, is_deposit = _line_group_and_label(li, ref_date)
            sections[group].append({
                "description":       label,
                "invoice_number":    inv.invoice_number,
                "is_deposit":        is_deposit,
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

    # Total deposit held = refundable deposit money the tenant has PAID across all
    # confirmed history (not just this receipt) — the onboarding deposit on the
    # tenant record PLUS any paid deposit-subcategory line items, less returns.
    deposit_paid_total = 0.0
    if tenant:
        from models import SubCategory
        deposit_paid_total += _f(getattr(tenant, "deposit_paid", 0))
        for inv in invoices:
            for li in inv.line_items:
                if li.subcategory == SubCategory.deposit.value:
                    deposit_paid_total += _f(li.amount_paid)
        deposit_paid_total -= _f(getattr(tenant, "deposit_returned", 0))

    # eTIMS details for the on-screen receipt (§3.1). The key is present ONLY
    # when the property opted in, kept receipts on, and a number was recorded —
    # so the UI has nothing to render an empty state from, which is the point.
    etims = None
    if (property is not None and property.etims_shows("receipts")
            and payment.etims_invoice_number):
        etims = {
            "invoice_number": payment.etims_invoice_number,
            "issued_at":      (payment.etims_issued_at.isoformat()
                               if payment.etims_issued_at else None),
            "qr_url":         payment.etims_qr_url,
            "seller_kra_pin": property.effective_kra_pin,
            "buyer_kra_pin":  getattr(tenant, "kra_pin", None) if tenant else None,
        }

    return {
        "payment_ref":    payment.payment_ref,
        "payment_date":   str(payment.payment_date) if payment.payment_date else None,
        "etims":          etims,
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
        "deposits_section":  sections["deposits"],
        "other_section":     sections["other"],
        "rent_due":          _subtotal(sections["rent"], "amount_due"),
        "utilities_due":     _subtotal(sections["utilities"], "amount_due"),
        "deposits_due":      _subtotal(sections["deposits"], "amount_due"),
        "other_due":         _subtotal(sections["other"], "amount_due"),
        "total_due":         total_due,
        "amount_paid":       amount_paid,
        "advance_credit":    advance_credit,
        "balance_remaining": balance_remaining,
        "deposit_held_total": round(deposit_paid_total, 2),
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


def render_receipt_pdf(payment, layout: dict | None = None) -> bytes:
    """
    Branded receipt PDF.

    `layout` is the landlord's chosen receipt layout (paper size, header slot
    arrangement, density) — see services/receipt_layout.py. Omitted, it is read
    from their settings; a landlord who has never touched the screen gets the
    original A4 receipt unchanged.
    """
    from services import receipt_layout as rl

    data     = build_receipt(payment)
    landlord = payment.landlord
    currency = data["currency"]
    layout   = rl.normalise(layout) if layout is not None else rl.for_landlord(landlord)

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
        + _section_html("Deposits", data["deposits_section"], currency)
        + _section_html("Other charges", data["other_section"], currency)
    )

    advance_row = (
        f"<tr><td>Advance / credit</td><td class='right'>{_money(data['advance_credit'], currency)}</td></tr>"
        if data["advance_credit"] > 0 else ""
    )
    deposit_held_row = (
        f"<tr><td>Total deposit held (refundable)</td><td class='right'>{_money(data['deposit_held_total'], currency)}</td></tr>"
        if data.get("deposit_held_total", 0) > 0 else ""
    )
    totals = (
        "<h2>Summary</h2><table class='kv'><tbody>"
        f"<tr><td>Total amount due</td><td class='right'>{_money(data['total_due'], currency)}</td></tr>"
        f"<tr class='total-row'><td>Amount paid (this receipt)</td><td class='right'>{_money(data['amount_paid'], currency)}</td></tr>"
        f"{advance_row}"
        f"<tr class='total-row'><td>Balance remaining</td><td class='right'>{_money(data['balance_remaining'], currency)}</td></tr>"
        f"{deposit_held_row}"
        "</tbody></table>"
    )

    # The landlord's own header arrangement replaces the shared report
    # letterhead; sections they've switched off are simply not drawn.
    sections_on = layout.get("sections", {})
    # These rows are already inside `totals`, so hiding one means removing it
    # from the built string rather than blanking the variable it came from.
    if not sections_on.get("deposits", True) and deposit_held_row:
        totals = totals.replace(deposit_held_row, "", 1)
    if not sections_on.get("balance", True):
        balance_row = (
            f"<tr class='total-row'><td>Balance remaining</td>"
            f"<td class='right'>{_money(data['balance_remaining'], currency)}</td></tr>"
        )
        totals = totals.replace(balance_row, "", 1)

    signature = _signature_html(meta) if sections_on.get("signature", True) else ""
    thanks = (
        "<p class='muted'>Thank you for your payment.</p>"
        if sections_on.get("notes", True) else ""
    )

    # eTIMS block (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §3.1). Returns "" —
    # and so changes this receipt not at all — unless the property opted in,
    # kept receipts switched on, AND this payment carries a recorded number.
    # A payment without one produces no block, no placeholder and no "pending"
    # marker, even on an eTIMS-enabled property.
    from services.etims_pdf import receipt_block_html
    etims_block = receipt_block_html(payment, payment.property, payment.tenant)

    body = (
        f"{rl.header_html(layout, meta)}{info}{sections_html}{totals}"
        f"{thanks}{etims_block}{signature}{_platform_credit_html()}"
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{_REPORT_STYLE}<style>{rl.page_css(layout)}</style>"
        f"</head><body>{body}</body></html>"
    )
    return render_pdf(html)


# ---------------------------------------------------------------------------
# Layout preview
# ---------------------------------------------------------------------------

def render_sample_receipt_pdf(landlord, layout: dict) -> bytes:
    """
    A receipt built from FAKE data, so the layout editor can show the real paper
    size and header arrangement without needing a real payment to point at — a
    landlord setting this up on day one has no payments yet.

    Deliberately obvious sample values: nobody should mistake a preview for a
    document they can hand to a tenant.
    """
    from services import receipt_layout as rl
    from services.report_builder import build_meta

    layout = rl.normalise(layout)
    currency = getattr(landlord, "currency", "KES") or "KES"

    meta = build_meta(
        landlord,
        report_title="Payment Receipt",
        subject="SAMPLE — Jane Wanjiku · Unit A1",
        property_name="Sunrise Apartments",
    )
    meta["phone"] = getattr(landlord, "mpesa_number", None)

    info = (
        "<table class='kv'><tbody>"
        "<tr><td>Receipt no.</td><td class='right'>SAMPLE-0001</td></tr>"
        "<tr><td>Date</td><td class='right'>"
        f"{date.today().isoformat()}</td></tr>"
        "<tr><td>Received from</td><td class='right'>Jane Wanjiku</td></tr>"
        "<tr><td>Method</td><td class='right'>M-Pesa</td></tr>"
        "<tr><td>Reference</td><td class='right'>SGH7X2K9QP</td></tr>"
        "</tbody></table>"
    )

    def rows(title, items):
        body = "".join(
            f"<tr><td>{escape(label)}</td><td class='right'>{_money(amount, currency)}</td></tr>"
            for label, amount in items
        )
        return f"<h2>{escape(title)}</h2><table class='kv'><tbody>{body}</tbody></table>"

    sections = rows("Rent", [("Rent — this month", 25000)])
    sections += rows("Utilities", [("Water", 1200), ("Garbage", 300)])
    if layout["sections"].get("deposits", True):
        sections += rows("Deposits", [("Security deposit (held)", 25000)])

    totals_rows = (
        "<tr><td>Total amount due</td><td class='right'>"
        f"{_money(26500, currency)}</td></tr>"
        "<tr class='total-row'><td>Amount paid (this receipt)</td>"
        f"<td class='right'>{_money(26500, currency)}</td></tr>"
    )
    if layout["sections"].get("balance", True):
        totals_rows += (
            "<tr class='total-row'><td>Balance remaining</td>"
            f"<td class='right'>{_money(0, currency)}</td></tr>"
        )
    totals = f"<h2>Summary</h2><table class='kv'><tbody>{totals_rows}</tbody></table>"

    thanks = (
        "<p class='muted'>Thank you for your payment.</p>"
        if layout["sections"].get("notes", True) else ""
    )
    signature = _signature_html(meta) if layout["sections"].get("signature", True) else ""

    body = (
        f"{rl.header_html(layout, meta)}"
        "<p class='muted'><strong>SAMPLE RECEIPT — not a real payment.</strong></p>"
        f"{info}{sections}{totals}{thanks}{signature}{_platform_credit_html()}"
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{_REPORT_STYLE}<style>{rl.page_css(layout)}</style>"
        f"</head><body>{body}</body></html>"
    )
    return render_pdf(html)
