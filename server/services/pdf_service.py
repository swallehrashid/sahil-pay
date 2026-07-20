"""
SahilPay — services/pdf_service.py
=====================================
WeasyPrint-backed PDF generation. All HTML is built inline (simple,
genuinely-rendered documents) rather than via Jinja2 template files — no
templates/ directory exists yet, and these are small enough to compose
directly. Every function returns raw PDF bytes; routes decide whether to
stream, email, or upload them.
"""

from __future__ import annotations

from html import escape

from utils import render_pdf

_BASE_STYLE = """
<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1a1a2e; font-size: 13px; }
  h1 { font-size: 20px; font-weight: 300; margin-bottom: 4px; }
  h2 { font-size: 15px; font-weight: 500; margin-top: 24px; margin-bottom: 8px; }
  .muted { color: #6b6b80; font-size: 12px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #e2e2e8; font-size: 12px; }
  th { background: #f4f4f8; font-weight: 600; }
  .total-row td { font-weight: 700; border-top: 2px solid #1a1a2e; }
  .header { display: flex; justify-content: space-between; border-bottom: 2px solid #200497; padding-bottom: 12px; margin-bottom: 16px; }
</style>
"""


def _money(value) -> str:
    try:
        return f"KES {float(value):,.2f}"
    except (TypeError, ValueError):
        return "KES 0.00"


def _shell(title: str, body_html: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head><body><h1>{escape(title)}</h1>{body_html}</body></html>"


def generate_invoice_pdf(invoice) -> bytes:
    """Render a single invoice (header + line items) to PDF."""
    tenant = invoice.tenant
    landlord = invoice.landlord
    rows = "".join(
        f"<tr><td>{escape(li.item)}</td><td>{escape(li.description or '')}</td>"
        f"<td>{li.quantity}</td><td>{_money(li.unit_price)}</td><td>{_money(li.amount)}</td></tr>"
        for li in invoice.line_items
    )
    body = f"""
    <div class="header">
      <div>
        <strong>{escape(landlord.company_name)}</strong><br/>
        <span class="muted">{escape(landlord.company_address or '')}</span>
      </div>
      <div class="muted">
        Invoice #{escape(invoice.invoice_number)}<br/>
        Issued: {invoice.issue_date}<br/>
        Due: {invoice.due_date or '—'}
      </div>
    </div>
    <p>Billed to: <strong>{escape(tenant.first_name)} {escape(tenant.last_name)}</strong> — Unit {escape(invoice.unit.name if invoice.unit else '')}</p>
    <table>
      <thead><tr><th>Item</th><th>Description</th><th>Qty</th><th>Unit Price</th><th>Amount</th></tr></thead>
      <tbody>{rows}</tbody>
      <tfoot>
        <tr class="total-row"><td colspan="4">Total</td><td>{_money(invoice.total_amount)}</td></tr>
        <tr><td colspan="4">Paid</td><td>{_money(invoice.amount_paid)}</td></tr>
        <tr><td colspan="4">Balance</td><td>{_money(invoice.balance)}</td></tr>
      </tfoot>
    </table>
    """
    return render_pdf(_shell(invoice.title or f"Invoice {invoice.invoice_number}", body))


def generate_receipt_pdf(payment) -> bytes:
    """Render a payment receipt to PDF."""
    landlord = payment.landlord
    tenant = payment.tenant
    body = f"""
    <div class="header">
      <div>
        <strong>{escape(landlord.company_name)}</strong><br/>
        <span class="muted">{escape(landlord.company_address or '')}</span>
      </div>
      <div class="muted">
        Receipt — {escape(payment.payment_ref)}<br/>
        Date: {payment.payment_date}
      </div>
    </div>
    <p>Received from: <strong>{escape(tenant.first_name) if tenant else 'N/A'} {escape(tenant.last_name) if tenant else ''}</strong></p>
    <table>
      <tbody>
        <tr><td>Amount</td><td>{_money(payment.amount)}</td></tr>
        <tr><td>Method</td><td>{escape(payment.payment_method or payment.source or '—')}</td></tr>
        <tr><td>Reference</td><td>{escape(payment.mpesa_reference or payment.payment_ref)}</td></tr>
        <tr><td>Status</td><td>{escape(payment.status or '')}</td></tr>
      </tbody>
    </table>
    <p class="muted">Thank you for your payment.</p>
    """
    return render_pdf(_shell("Payment Receipt", body))


def generate_tax_invoice_pdf(transaction, landlord) -> bytes:
    """
    Render a branded SahilPay payment receipt / tax invoice for a platform
    charge (subscription or SMS purchase). VAT is shown as inclusive of the
    charged amount (Kenya standard-rate 16%), which is the format landlords
    submit for their own records.
    """
    from decimal import Decimal, ROUND_HALF_UP

    # Human line-item description for the charge.
    if transaction.type == "sms_purchase":
        line_desc = f"SMS credit purchase — {transaction.sms_count or 0} credits"
    else:
        line_desc = "SahilPay subscription — platform fee"

    gross = Decimal(str(transaction.amount or 0))
    net = (gross / Decimal("1.16")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vat = gross - net

    issued = transaction.created_at.strftime("%d %b %Y") if transaction.created_at else "—"
    receipt_no = f"SP-RCPT-{transaction.id:06d}"
    is_paid = (transaction.status or "").lower() == "paid"
    status_pill = (
        f"<span style='display:inline-block;padding:4px 12px;border-radius:999px;"
        f"font-weight:700;font-size:11px;letter-spacing:.05em;"
        f"background:{'#e6f7ef' if is_paid else '#fdeceb'};"
        f"color:{'#0f7a4d' if is_paid else '#b5382f'};'>"
        f"{escape((transaction.status or 'PENDING').upper())}</span>"
    )

    style = """
    <style>
      .brand { font-size: 24px; font-weight: 700; color: #200497; letter-spacing: -0.5px; }
      .brand-tag { color: #6b6b80; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; }
      .rcpt-title { text-align: right; }
      .rcpt-title h2 { color:#200497; margin:0 0 4px; font-size:18px; font-weight:600; }
      .block { margin-top: 18px; }
      .foot { margin-top: 28px; border-top: 1px solid #e2e2e8; padding-top: 12px; }
    </style>
    """

    body = f"""
    {style}
    <div class="header" style="align-items:flex-start;">
      <div>
        <div class="brand">SahilPay</div>
        <div class="brand-tag">Property Management Platform</div>
      </div>
      <div class="rcpt-title">
        <h2>Payment Receipt</h2>
        <div class="muted">Receipt No: <strong>{receipt_no}</strong></div>
        <div class="muted">Date: {issued}</div>
        <div class="block">{status_pill}</div>
      </div>
    </div>

    <div class="block">
      <div class="muted">Billed to</div>
      <strong>{escape(landlord.company_name)}</strong><br/>
      <span class="muted">{escape(landlord.company_address or '')}</span>
    </div>

    <table class="block">
      <thead><tr><th>Description</th><th style="text-align:right;">Amount</th></tr></thead>
      <tbody>
        <tr><td>{escape(line_desc)}</td><td style="text-align:right;">{_money(net)}</td></tr>
        <tr><td>VAT (16%)</td><td style="text-align:right;">{_money(vat)}</td></tr>
      </tbody>
      <tfoot>
        <tr class="total-row"><td>Total paid</td><td style="text-align:right;">{_money(gross)}</td></tr>
      </tfoot>
    </table>

    <table class="block">
      <tbody>
        <tr><td>Payment reference</td><td>{escape(transaction.payment_reference or '—')}</td></tr>
        <tr><td>Transaction ID</td><td>#{transaction.id}</td></tr>
      </tbody>
    </table>

    <div class="foot muted">
      Thank you for your business. This is a system-generated receipt and is valid
      without a signature. Amounts are shown in KES and are inclusive of VAT where applicable.
    </div>
    """
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head>"
        f"<body>{body}</body></html>"
    )
    return render_pdf(html)


def generate_affiliate_receipt_pdf(withdrawal) -> bytes:
    """
    KRA-compliant affiliate commission payout receipt — gross / withholding
    tax / Sahil platform fee / net breakdown. Every figure is read from the
    withdrawal row's own snapshotted columns (never live config), so a
    receipt regenerated years later is byte-identical regardless of later
    rate changes (AFFILIATE_PROGRAM_SPEC.md D11/D7/E24).
    """
    affiliate = withdrawal.affiliate
    issued = withdrawal.processed_at.strftime("%d %b %Y") if withdrawal.processed_at else "—"
    fee_label = f"{withdrawal.fee_value}%" if withdrawal.fee_type == "percent" else _money(withdrawal.fee_value)

    style = """
    <style>
      .brand { font-size: 24px; font-weight: 700; color: #200497; letter-spacing: -0.5px; }
      .brand-tag { color: #6b6b80; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; }
      .rcpt-title { text-align: right; }
      .rcpt-title h2 { color:#200497; margin:0 0 4px; font-size:18px; font-weight:600; }
      .block { margin-top: 18px; }
      .foot { margin-top: 28px; border-top: 1px solid #e2e2e8; padding-top: 12px; }
      .net-row td { font-weight: 700; border-top: 2px solid #1a1a2e; font-size: 14px; }
    </style>
    """

    body = f"""
    {style}
    <div class="header" style="align-items:flex-start;">
      <div>
        <div class="brand">SahilPay</div>
        <div class="brand-tag">Affiliate Program</div>
      </div>
      <div class="rcpt-title">
        <h2>Affiliate Commission Payout Receipt</h2>
        <div class="muted">Receipt No: <strong>{escape(withdrawal.receipt_number or '—')}</strong></div>
        <div class="muted">Date paid: {issued}</div>
      </div>
    </div>

    <div class="block">
      <div class="muted">Paid to</div>
      <strong>{escape(affiliate.full_name)}</strong><br/>
      <span class="muted">National ID: {escape(affiliate.national_id or '—')}</span><br/>
      <span class="muted">KRA PIN: {escape(affiliate.kra_pin or '—')}</span><br/>
      <span class="muted">M-Pesa number: {escape(affiliate.mpesa_number or '—')}</span>
    </div>

    <table class="block">
      <thead><tr><th>Description</th><th style="text-align:right;">Amount</th></tr></thead>
      <tbody>
        <tr><td>Gross commission withdrawn</td><td style="text-align:right;">{_money(withdrawal.gross_amount)}</td></tr>
        <tr><td>Withholding tax ({withdrawal.wht_rate}%)</td><td style="text-align:right;">-{_money(withdrawal.wht_amount)}</td></tr>
        <tr><td>SahilPay platform fee ({fee_label})</td><td style="text-align:right;">-{_money(withdrawal.fee_amount)}</td></tr>
      </tbody>
      <tfoot>
        <tr class="net-row"><td>Net paid to affiliate</td><td style="text-align:right;">{_money(withdrawal.net_amount)}</td></tr>
      </tfoot>
    </table>

    <table class="block">
      <tbody>
        <tr><td>M-Pesa transaction reference</td><td>{escape(withdrawal.mpesa_reference or '—')}</td></tr>
        <tr><td>Withdrawal ID</td><td>#{withdrawal.id}</td></tr>
      </tbody>
    </table>

    <div class="foot muted">
      Withholding tax deducted at source and remitted to KRA by SahilPay. This is a
      system-generated receipt and is valid without a signature. Amounts are shown in KES.
    </div>
    """
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head>"
        f"<body>{body}</body></html>"
    )
    return render_pdf(html)


def generate_tenant_statement_pdf(tenant) -> bytes:
    """Render a tenant's full running statement (invoices + payments, chronological) to PDF."""
    entries = []
    for inv in tenant.invoices:
        entries.append((inv.issue_date, f"Invoice {inv.invoice_number} ({inv.invoice_type})", inv.total_amount, 0))
    for pay in tenant.payments:
        entries.append((pay.payment_date, f"Payment {pay.payment_ref}", 0, pay.amount))
    entries.sort(key=lambda e: e[0] or "")

    rows = ""
    running = 0.0
    for d, label, due, paid in entries:
        running += float(due or 0) - float(paid or 0)
        rows += (
            f"<tr><td>{d}</td><td>{escape(label)}</td><td>{_money(due)}</td>"
            f"<td>{_money(paid)}</td><td>{_money(running)}</td></tr>"
        )

    body = f"""
    <p class="muted">Tenant: <strong>{escape(tenant.first_name)} {escape(tenant.last_name)}</strong> — Unit {escape(tenant.unit.name if tenant.unit else '')}</p>
    <table>
      <thead><tr><th>Date</th><th>Item</th><th>Due</th><th>Paid</th><th>Running balance</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p class="muted">Current balance: {_money(tenant.balance)}</p>
    """
    return render_pdf(_shell("Tenant Statement", body))


def generate_tenants_list_pdf(tenants: list) -> bytes:
    """Render a simple tenants directory (name, unit, phone, balance) to PDF."""
    rows = "".join(
        f"<tr><td>{escape(t.first_name)} {escape(t.last_name)}</td>"
        f"<td>{escape(t.unit.name if t.unit else '')}</td>"
        f"<td>{escape(t.phone)}</td><td>{_money(t.balance)}</td></tr>"
        for t in tenants
    )
    body = f"""
    <table>
      <thead><tr><th>Tenant</th><th>Unit</th><th>Phone</th><th>Balance</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    return render_pdf(_shell("Tenants", body))


def render_document_template(html_body: str) -> bytes:
    """
    Wrap an already-rendered document body (placeholders already substituted
    by the caller) in a minimal HTML shell and convert to PDF. Used for
    dispatching lease/tenancy/deposit document templates to tenants.
    """
    return render_pdf(f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head><body>{html_body}</body></html>")
