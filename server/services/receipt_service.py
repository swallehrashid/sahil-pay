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

import logging
from datetime import date, datetime
from decimal import Decimal
from html import escape

from utils import render_pdf
from services.report_builder import build_meta, _signature_html

logger = logging.getLogger(__name__)


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


class ReceiptNotAvailable(Exception):
    """This payment cannot have a receipt (yet) — see receipt_blocker()."""


def receipt_blocker(payment) -> str | None:
    """
    Why this payment cannot have a receipt, or None when it can.

    A receipt says "we received this money and applied it". Until a payment is
    confirmed AND applied to a tenant's account, neither half is true: a
    pending Co-pilot SMS, a suspense payment nobody has matched, a declined or
    reversed one — issuing a receipt for any of those hands the tenant a
    document that proves a payment the books do not have.
    """
    from models import PaymentStatus

    if payment is None or getattr(payment, "is_deleted", False):
        return "This payment no longer exists."
    if payment.status != PaymentStatus.confirmed.value:
        label = {
            "pending": "is still awaiting review",
            "suspense": "has not been matched to a tenant yet",
            "declined": "was declined",
            "reversed": "was reversed",
        }.get(payment.status, f"is {payment.status}")
        return (f"No receipt yet: this payment {label}. Review and allocate it "
                "first — receipts are issued only for confirmed, allocated payments.")
    if payment.tenant_id is None:
        return "No receipt yet: this payment is not allocated to a tenant."
    if not payment.payment_allocations and not _credited(payment):
        return ("No receipt yet: this payment has not been allocated to any "
                "charge or held as credit.")
    return None


def _credited(payment) -> bool:
    from models import CreditLedger
    return CreditLedger.query.filter(CreditLedger.payment_id == payment.id,
                                     CreditLedger.amount > 0).first() is not None


def assert_receiptable(payment) -> None:
    reason = receipt_blocker(payment)
    if reason:
        raise ReceiptNotAvailable(reason)


_METHOD_LABELS = {
    "mpesa": "M-Pesa", "m-pesa": "M-Pesa", "co_pilot": "M-Pesa (Co-pilot)",
    "stk": "M-Pesa", "c2b": "M-Pesa", "bank_statement": "Bank", "bank": "Bank",
    "cash": "Cash", "manual": "Manual entry", "cheque": "Cheque",
    "credit": "Account credit",
}


def _method_label(payment) -> str:
    raw = (payment.payment_method or payment.source or "").strip()
    return _METHOD_LABELS.get(raw.lower(), raw.replace("_", " ").title() or "—")


def _dmy(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _short_month(iso: str | None) -> str:
    if not iso:
        return ""
    y, m = int(iso[:4]), int(iso[5:7])
    return date(y, m, 1).strftime("%b %Y")


def _legacy_rows(payment) -> list[dict]:
    """Allocations that only recorded an invoice (no line) — very old data."""
    from services import line_period as lp
    rows = []
    for a in payment.payment_allocations:
        if a.line_item_id is None and a.invoice is not None:
            month = lp.first_of(a.invoice.issue_date)
            rows.append({
                "line_item_id": None, "invoice_number": a.invoice.invoice_number,
                "group": "other", "base": a.invoice.title or f"Invoice {a.invoice.invoice_number}",
                "month": month.isoformat() if month else None,
                "month_label": lp.month_label(month),
                "label": a.invoice.title or f"Invoice {a.invoice.invoice_number}",
                "amount": Decimal(a.amount_allocated or 0), "is_deposit": False,
            })
    return rows


def build_receipt(payment) -> dict:
    """
    Structured receipt data. Every charge row carries the MONTH it is for
    (services/line_period.py) and is stated as it stood at this payment — so a
    receipt downloaded again months later still says what it said the day it
    was issued.
    """
    from services import line_period as lp

    tenant   = payment.tenant
    landlord = payment.landlord
    unit     = payment.unit
    prop     = payment.property or (unit.property if unit else None)

    paid = lp.paid_lines(payment) + _legacy_rows(payment)
    owed = lp.outstanding_after(payment)

    # One row per (charge, month): what was owed going in, what this payment
    # paid, what is left. Keyed so a line this payment did not touch still
    # shows as owed on the full-page receipt.
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []

    def slot(r):
        key = (r["group"], r["base"], r["month"])
        if key not in merged:
            merged[key] = {
                "description":       r["label"],
                "item":              r["base"],
                "month":             r["month"],
                "month_label":       r["month_label"],
                "invoice_number":    r["invoice_number"],
                "is_deposit":        r["is_deposit"],
                "amount_due":        0.0,
                "paid_this_receipt": 0.0,
                "balance_cf":        0.0,
            }
            order.append(key)
        return merged[key]

    for r in paid:
        row = slot(r)
        row["paid_this_receipt"] += _f(r["amount"])
        row["amount_due"] += _f(r["amount"])
    for r in owed:
        row = slot(r)
        row["balance_cf"] += _f(r["amount"])
        row["amount_due"] += _f(r["amount"])

    sections = {"rent": [], "utilities": [], "deposits": [], "other": []}
    for key in sorted(order, key=lambda k: (k[2] or "9999", k[1])):
        row = merged[key]
        for money in ("amount_due", "paid_this_receipt", "balance_cf"):
            row[money] = round(row[money], 2)
        sections[key[0]].append(row)

    def _subtotal(rows, key):
        return round(sum(r[key] for r in rows), 2)

    total_allocated = round(sum(_f(r["amount"]) for r in paid), 2)
    balance_remaining = round(sum(_f(r["amount"]) for r in owed), 2)
    amount_paid = _f(payment.amount)
    advance_credit = round(max(0.0, amount_paid - total_allocated), 2)
    total_due = round(total_allocated + balance_remaining, 2)

    paid_months = sorted({r["month"] for r in paid if r["month"]})
    if len(paid_months) == 1:
        period_label = lp.month_label(lp.parse_month(paid_months[0]))
    elif paid_months:
        period_label = (f"{lp.month_label(lp.parse_month(paid_months[0]))} – "
                        f"{lp.month_label(lp.parse_month(paid_months[-1]))}")
    else:
        period_label = None

    deposit_paid_total = 0.0
    if tenant:
        from models import Invoice, InvoiceStatus, SubCategory
        deposit_paid_total += _f(getattr(tenant, "deposit_paid", 0))
        for inv in (Invoice.query.filter_by(tenant_id=tenant.id, is_deleted=False)
                    .filter(Invoice.status != InvoiceStatus.void.value).all()):
            for li in inv.line_items:
                if li.subcategory == SubCategory.deposit.value:
                    deposit_paid_total += _f(li.amount_paid)
        deposit_paid_total -= _f(getattr(tenant, "deposit_returned", 0))

    etims = None
    if (prop is not None and prop.etims_shows("receipts")
            and payment.etims_invoice_number):
        etims = {
            "invoice_number": payment.etims_invoice_number,
            "issued_at":      (payment.etims_issued_at.isoformat()
                               if payment.etims_issued_at else None),
            "qr_url":         payment.etims_qr_url,
            "seller_kra_pin": prop.effective_kra_pin,
            "buyer_kra_pin":  getattr(tenant, "kra_pin", None) if tenant else None,
        }

    def _public(rows):
        return [{**r, "amount": _f(r["amount"])} for r in rows]

    return {
        "payment_ref":    payment.payment_ref,
        "payment_date":   str(payment.payment_date) if payment.payment_date else None,
        "etims":          etims,
        "status":         payment.status,
        "method":         _method_label(payment),
        "reference":      payment.mpesa_reference or payment.till_number or payment.payment_ref,
        "tenant_name":    f"{tenant.first_name} {tenant.last_name}".strip() if tenant else None,
        "account_number": getattr(tenant, "account_number", None) if tenant else None,
        "unit_name":      unit.name if unit else None,
        "property_name":  prop.name if prop else None,
        "currency":       landlord.currency if landlord else "KES",
        "landlord": {
            "company_name":    landlord.company_name if landlord else None,
            "company_address": getattr(landlord, "company_address", None) if landlord else None,
            "logo_url":        getattr(landlord, "logo_url", None) if landlord else None,
        },
        "period_label":      period_label,
        "paid_items":        _public(paid),
        "outstanding_items": _public(owed),
        "rent_section":      sections["rent"],
        "utilities_section": sections["utilities"],
        "deposits_section":  sections["deposits"],
        "other_section":     sections["other"],
        "rent_due":          _subtotal(sections["rent"], "amount_due"),
        "utilities_due":     _subtotal(sections["utilities"], "amount_due"),
        "deposits_due":      _subtotal(sections["deposits"], "amount_due"),
        "other_due":         _subtotal(sections["other"], "amount_due"),
        "total_due":         total_due,
        "total_allocated":   total_allocated,
        "amount_paid":       amount_paid,
        "advance_credit":    advance_credit,
        "balance_remaining": balance_remaining,
        "deposit_held_total": round(deposit_paid_total, 2),
    }


def _money(value, currency="KES") -> str:
    return f"{currency} {_f(value):,.2f}"


def _charge_label(row: dict, short: bool) -> str:
    """'Rent — September 2026' (full page) or 'Rent — Sep 2026' (a third)."""
    if not row.get("month"):
        return escape(row["item"])
    month = _short_month(row["month"]) if short else row["month_label"]
    return f"{escape(row['item'])} <span class='month'>— {escape(month)}</span>"


def _charge_groups_html(groups, currency: str, columns: int, max_rows: int | None,
                        period_label: str | None = None) -> str:
    """
    Every charge group as ONE ruled table. Four money columns on a full page
    (due / paid / balance c/f); item + paid on a third or a strip, where only
    what THIS payment paid is listed. Every item names its month.
    """
    wide = columns >= 4
    if wide:
        head = ("<th>Item</th><th class='right'>Amount due</th>"
                "<th class='right'>Paid (this receipt)</th><th class='right'>Balance c/f</th>")
        span = 4
    else:
        head = "<th>Item</th><th class='right'>Paid</th>"
        span = 2

    body = ""
    used = hidden = 0
    for title, rows in groups:
        if not wide:
            rows = [r for r in rows if r["paid_this_receipt"] > 0]
        if not rows:
            continue
        if max_rows is not None:
            room = max(0, max_rows - used)
            shown = rows[:room]
            hidden += len(rows) - len(shown)
        else:
            shown = rows
        if not shown:
            continue
        if wide:
            body += f"<tr class='group-row'><td colspan='{span}'>{escape(title)}</td></tr>"
        for r in shown:
            label = _charge_label(r, short=not wide)
            if wide:
                body += (f"<tr><td>{label}</td>"
                         f"<td class='right'>{_money(r['amount_due'], currency)}</td>"
                         f"<td class='right'>{_money(r['paid_this_receipt'], currency)}</td>"
                         f"<td class='right'>{_money(r['balance_cf'], currency)}</td></tr>")
            else:
                body += (f"<tr><td>{label}</td>"
                         f"<td class='right'>{_money(r['paid_this_receipt'], currency)}</td></tr>")
        used += len(shown)

    if not body:
        body = f"<tr><td colspan='{span}'>Held as credit on the account</td></tr>"

    heading = "Charges"
    if period_label:
        # A third of a page has room for "Jul–Sep 2026", not the full words.
        heading += f" — {escape(_short_period(period_label) if not wide else period_label)}"
    html = (f"<h2>{heading}</h2><table class='grid charges'><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>")
    if hidden:
        html += (f"<p class='muted receipt-small'>+{hidden} more item"
                 f"{'s' if hidden != 1 else ''} — see the full statement.</p>")
    return html


def _short_period(label: str) -> str:
    """'July 2026 – September 2026' → 'Jul–Sep 2026'; 'August 2026' → 'Aug 2026'."""
    from datetime import datetime as _dt
    parts = [p.strip() for p in label.split("–")]
    try:
        dates = [_dt.strptime(p, "%B %Y") for p in parts]
    except ValueError:
        return label
    if len(dates) == 1:
        return dates[0].strftime("%b %Y")
    a, b = dates[0], dates[-1]
    if a.year == b.year:
        return f"{a:%b}–{b:%b %Y}"
    return f"{a:%b %Y}–{b:%b %Y}"


def _details_html(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><td class='k'>{escape(k)}</td><td class='v'>{escape(v or '—')}</td></tr>"
        for k, v in rows
    )
    return f"<h2>Details</h2><table class='grid kv'><tbody>{body}</tbody></table>"


def _owed_html(items: list[dict], currency: str, flow: str, limit: int = 6) -> str:
    """
    What is still owed after this payment, by month — "Rent — Sep 2026 KES
    20,000". A tenant paying August's rent late must see that September is
    still open, on the same piece of paper.
    """
    if not items:
        return ""
    from services.receipt_layout import FLOW_BAND
    shown = items[:limit]
    more = len(items) - len(shown)
    if flow == FLOW_BAND:
        shown = items[:limit]
        more = len(items) - len(shown)
        rows = "".join(
            f"<tr><td>{escape(i['base'])}{(' <span class=month>' + escape(_short_month(i['month'])) + '</span>') if i['month'] else ''}</td>"
            f"<td class='right'>{_money(i['amount'], currency)}</td></tr>" for i in shown)
        if more:
            rows += f"<tr><td colspan='2' class='muted'>+{more} more</td></tr>"
        return ("<p class='owed-line'><strong>Still owed after this payment</strong></p>"
                f"<table class='grid owed totals'><tbody>{rows}</tbody></table>")
    rows = "".join(
        f"<tr><td>{escape(i['label'])}</td><td class='right'>{_money(i['amount'], currency)}</td></tr>"
        for i in shown)
    if more:
        rows += f"<tr><td colspan='2' class='muted'>+{more} more — see the full statement</td></tr>"
    return ("<h2>Still owed after this payment</h2><table class='grid owed'>"
            "<thead><tr><th>Item</th><th class='right'>Balance</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


def _credit_html() -> str:
    from services import branding
    site = branding.BRAND_WEBSITE.replace("https://", "")
    return (f"<p class='credit'>Generated by {branding.BRAND_NAME} · {site} · "
            f"{branding.BRAND_PHONE}</p>")


def _totals_html(data: dict, currency: str, sections_on: dict) -> str:
    rows = [f"<tr><td>Total due</td><td class='right'>{_money(data['total_due'], currency)}</td></tr>",
            f"<tr class='total-row'><td>Amount paid</td>"
            f"<td class='right'>{_money(data['amount_paid'], currency)}</td></tr>"]
    if data["advance_credit"] > 0:
        rows.append(f"<tr><td>Advance credit</td><td class='right'>"
                    f"{_money(data['advance_credit'], currency)}</td></tr>")
    if sections_on.get("balance", True):
        rows.append(f"<tr class='total-row'><td>Balance</td>"
                    f"<td class='right'>{_money(data['balance_remaining'], currency)}</td></tr>")
    if sections_on.get("deposits", True) and data.get("deposit_held_total", 0) > 0:
        rows.append(f"<tr><td>Deposit held</td><td class='right'>"
                    f"{_money(data['deposit_held_total'], currency)}</td></tr>")
    return f"<h2>Summary</h2><table class='grid totals'><tbody>{''.join(rows)}</tbody></table>"


def _render(landlord, layout: dict, theme: dict, data: dict, *, etims_block: str = "",
            sample: bool = False) -> bytes:
    """The one renderer: a real receipt and the settings preview both come through here."""
    from services import receipt_layout as rl

    currency = data["currency"]
    meta = build_meta(landlord, report_title="Official Receipt",
                      property_name=data.get("property_name"))
    if not meta.get("phone"):
        meta["phone"] = getattr(landlord, "mpesa_number", None)

    unit_bits = " · ".join(b for b in (data.get("property_name"), data.get("unit_name")) if b)
    details = _details_html([
        ("Receipt no.", data["payment_ref"]),
        ("Date paid", _dmy(date.fromisoformat(data["payment_date"])) if data.get("payment_date") else ""),
        ("Received from", data.get("tenant_name") or ""),
        ("Unit", unit_bits),
        ("Method", data.get("method") or ""),
        ("Reference", str(data.get("reference") or "")),
    ])

    groups = [("Rent", data["rent_section"]), ("Utilities", data["utilities_section"]),
              ("Deposits", data["deposits_section"]), ("Other charges", data["other_section"])]
    if not layout["sections"].get("deposits", True):
        groups = [g for g in groups if g[0] != "Deposits" or any(r["paid_this_receipt"] for r in g[1])]
    charges = _charge_groups_html(groups, currency, rl.money_columns(layout),
                                  rl.max_charge_rows(layout), data.get("period_label"))

    sections_on = layout.get("sections", {})
    totals = _totals_html(data, currency, sections_on)
    flow = rl.flow_of(layout)
    owed = _owed_html(data.get("outstanding_items") or [], currency, flow, rl.max_owed_rows(layout)) \
        if sections_on.get("balance", True) else ""
    signature = _signature_html(meta) if sections_on.get("signature", True) else ""
    notes = "<p class='muted'>Thank you for your payment.</p>" if sections_on.get("notes", True) else ""
    if sample:
        notes = "<p><strong>SAMPLE — not a real payment.</strong></p>" + notes

    body = rl.compose_body(layout, {
        "details": details, "charges": charges, "totals": totals, "owed": owed,
        "notes": notes, "etims": etims_block, "signature": signature,
        "credit": _credit_html(),
    })
    html = rl.document(layout, theme, rl.header_html(layout, meta), body)
    return render_pdf(html)


def render_receipt_pdf(payment, layout: dict | None = None) -> bytes:
    """
    Branded receipt PDF. Refuses (ReceiptNotAvailable) for a payment that is
    not confirmed and allocated. `layout` defaults to the landlord's saved one.
    """
    from services import receipt_layout as rl
    from services import receipt_theme
    from services.etims_pdf import receipt_block_html

    assert_receiptable(payment)
    landlord = payment.landlord
    layout = rl.normalise(layout) if layout is not None else rl.for_landlord(landlord)
    data = build_receipt(payment)
    etims_block = receipt_block_html(payment, payment.property, payment.tenant)
    return _render(landlord, layout, receipt_theme.for_landlord(landlord), data,
                   etims_block=etims_block)


# ---------------------------------------------------------------------------
# Layout preview
# ---------------------------------------------------------------------------

def render_sample_receipt_pdf(landlord, layout: dict, theme_override: dict | None = None) -> bytes:
    """
    A receipt built from FAKE data so the layout editor shows the real paper
    and letterhead without a real payment. It goes through the SAME renderer
    as a real receipt — a preview that differs from the real thing is worse
    than no preview.
    """
    from services import receipt_layout as rl
    from services import receipt_theme
    from services import line_period as lp

    layout = rl.normalise(layout)
    currency = getattr(landlord, "currency", "KES") or "KES"
    today = date.today()
    this_month = lp.first_of(today)
    last_month = lp.first_of(date(today.year - (1 if today.month == 1 else 0),
                                  12 if today.month == 1 else today.month - 1, 1))

    def row(item, month, due, paid, left=0.0):
        return {"description": f"{item} — {lp.month_label(month)}" if month else item,
                "item": item, "month": month.isoformat() if month else None,
                "month_label": lp.month_label(month), "invoice_number": "SAMPLE",
                "is_deposit": "Deposit" in item,
                "amount_due": due, "paid_this_receipt": paid, "balance_cf": left}

    rent = [row("Rent", this_month, 6000, 6000)]
    utilities = [row("Water", last_month, 850, 850)]
    deposits = [row("Rent Deposit", this_month, 6000, 6000)] if layout["sections"].get("deposits", True) else []
    other = [row("Lease Agreement", None, 500, 500)]
    data = {
        "payment_ref": "SAMPLE-0001", "payment_date": today.isoformat(),
        "method": "M-Pesa", "reference": "UHU0S43PJ8",
        "tenant_name": "Jonah Alex Mwendwa", "unit_name": "Unit A1",
        "property_name": "Sunrise Apartments", "currency": currency,
        "period_label": lp.month_label(this_month),
        "rent_section": rent, "utilities_section": utilities,
        "deposits_section": deposits, "other_section": other,
        "outstanding_items": [{"base": "Water", "label": f"Water — {lp.month_label(this_month)}",
                               "month": this_month.isoformat(), "amount": 900.0}],
        "total_due": 14250.0, "amount_paid": 13350.0, "advance_credit": 0.0,
        "balance_remaining": 900.0, "deposit_held_total": 6000.0,
    }
    theme = receipt_theme.resolve(theme_override) if theme_override is not None \
        else receipt_theme.for_landlord(landlord)
    return _render(landlord, layout, theme, data, sample=True)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
#
# ONE implementation, used by both the landlord pressing "send receipt" and the
# automation that fires when Co-pilot auto-allocates a payment. They used to be
# separate: the manual path sent a real itemised receipt, while the automatic
# path sent a bare "we received your payment" with no breakdown, no PDF and no
# link. A tenant should not get a different quality of answer depending on
# which route their money happened to take.

# Channels that can actually deliver today. WhatsApp is accepted by the API and
# reported back as skipped — there is no integration behind it yet, and
# silently dropping it would look like a delivery failure nobody can explain.
DELIVERABLE_CHANNELS = ("email", "sms", "in_app")


def sms_receipt_text(payment, receipt: dict | None = None) -> str:
    """
    The SMS a tenant gets: what arrived, what it cleared, what is left, and a
    link to the real receipt.

    Kept deliberately tight. SMS is billed per 160-character segment and a
    single emoji or accented character forces UCS-2, which cuts the segment to
    70 characters and can triple the cost of every message an account sends. So
    this is plain ASCII, and only the two largest allocations are itemised —
    the link carries the full detail for anyone who wants it.
    """
    data = receipt or build_receipt(payment)
    currency = data.get("currency") or "KES"

    lines = []
    for section in ("rent_section", "utilities_section", "other_section", "deposits_section"):
        for row in data.get(section) or []:
            paid = row.get("paid_this_receipt") or 0
            if paid > 0:
                # ASCII only: "Rent Sep 2026", never the em dash of the PDF.
                name = row.get("item") or row.get("description") or "Charge"
                if row.get("month"):
                    name = f"{name} {_short_month(row['month'])}"
                lines.append((name, paid))
    lines.sort(key=lambda pair: pair[1], reverse=True)

    parts = [f"Payment received: {currency} {_f(payment.amount):,.0f} ({payment.payment_ref})."]

    if lines:
        shown = "; ".join(f"{name} {amount:,.0f}" for name, amount in lines[:2])
        if len(lines) > 2:
            shown += f"; +{len(lines) - 2} more"
        parts.append(f"Applied to: {shown}.")

    balance = data.get("balance_remaining") or 0
    credit = data.get("advance_credit") or 0
    if balance > 0:
        parts.append(f"Balance: {currency} {balance:,.0f}.")
    elif credit > 0:
        parts.append(f"In credit: {currency} {credit:,.0f}.")
    else:
        parts.append("Your account is settled.")

    parts.append(f"Receipt: {receipt_link_for(payment)}")
    parts.append("Thank you.")
    return " ".join(parts)


def send_receipt(payment, channels, *, landlord_id: int | None = None,
                 force_email: bool = False) -> tuple[list, list]:
    """
    Deliver a receipt for *payment* over *channels*.

    Returns (sent, skipped). Every channel is best-effort and INDEPENDENT: a
    tenant with no email still gets the SMS, and a failing SMS gateway does not
    stop the in-app copy. Skipping is reported with a reason rather than
    swallowed, because "the tenant never got it" is the kind of thing a manager
    finds out about a week later from an angry phone call.

    EMAIL IS SENT ONCE per payment. Several callers can each legitimately decide
    a receipt is due — recording a payment, co-pilot auto-allocation, M-Pesa
    reconciliation — and before `payment.receipt_emailed_at` existed they each
    sent their own copy, because none of them could see what the others had
    done. The stamp is that shared memory.

    *force_email* overrides it for one case only: a human pressing "resend
    receipt", where sending a second copy IS the intent. It is deliberately not
    the default, so a new caller has to think about it.

    The other channels are not de-duplicated. An SMS costs money and is capped
    by the balance check; an in-app notification is idempotent in practice
    because it lands in a list the tenant can already see.

    Does not commit — the caller owns the transaction.
    """
    from services.communication_service import dispatch_message
    from services.email_service import send_receipt_email
    from services.notification_service import notify

    tenant = payment.tenant
    if tenant is None:
        return [], ["no tenant linked to this payment"]
    blocker = receipt_blocker(payment)
    if blocker:
        return [], [blocker]

    landlord_id = landlord_id or payment.landlord_id
    data = build_receipt(payment)
    currency = data.get("currency") or "KES"
    summary = (
        f"Receipt {payment.payment_ref}: payment of {currency} "
        f"{_f(payment.amount):,.2f} received on {payment.payment_date}. Thank you."
    )

    sent, skipped = [], []
    for channel in channels or []:
        if channel == "email":
            if not tenant.email:
                skipped.append("email (no email on file)")
                continue
            if payment.receipt_emailed_at and not force_email:
                skipped.append("email (receipt already emailed for this payment)")
                continue
            try:
                pdf_bytes = render_receipt_pdf(payment)
                send_receipt_email.delay(tenant.email, tenant.first_name,
                                         pdf_bytes, payment.payment_ref,
                                         landlord_id=payment.landlord_id)
                # Stamped before the caller commits, so a second call inside the
                # same request sees it too.
                payment.receipt_emailed_at = datetime.utcnow()
                sent.append("email")
            except Exception as exc:              # never break the payment
                logger.exception("Receipt email failed for payment %s", payment.id)
                skipped.append(f"email ({exc})")

        elif channel == "sms":
            if not tenant.phone:
                skipped.append("sms (no phone on file)")
                continue
            try:
                log = dispatch_message(landlord_id=landlord_id, tenant=tenant,
                                       channel="sms",
                                       content=sms_receipt_text(payment, data))
                if log and log.status == "delivered":
                    sent.append("sms")
                else:
                    skipped.append("sms (send failed or insufficient balance)")
            except Exception as exc:
                logger.exception("Receipt SMS failed for payment %s", payment.id)
                skipped.append(f"sms ({exc})")

        elif channel == "in_app":
            if not tenant.user_id:
                skipped.append("in_app (tenant has no app account yet)")
                continue
            notify(
                recipient_user_id=tenant.user_id,
                category="payment_receipt",
                title="Payment received",
                body=summary,
                landlord_id=landlord_id,
                link="/portal/statement",
                entity_type="payment",
                entity_id=payment.id,
            )
            sent.append("in_app")

        elif channel == "whatsapp":
            skipped.append("whatsapp (not yet integrated)")
        else:
            skipped.append(f"{channel} (unknown channel)")

    return sent, skipped
