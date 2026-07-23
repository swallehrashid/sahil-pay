"""
services/reminder_content.py — the default tenant reminder communications.

Requirement (2026-07-23): NO reminder may ever be "just a balance". Every one
of the three default communications —
    invoice_notification | overdue_balance | payment_reminder
must always carry, across ALL channels (email / SMS / in-app):
  1. an itemised breakdown of exactly what the tenant owes (where the balance
     came from) — shared with the tenant dashboard via balance_breakdown.py,
  2. the LANDLORD's details (company name, location, phone, email),
  3. the PAYMENT details the tenant should pay to (M-Pesa paybill/till + account
     number + any instructions).

This module returns a `ReminderContent` with three renderings so each channel
uses the right one:
  - `.text`      plain multi-line text  → SMS, in-app, WhatsApp
  - `.html`      full Sahil-themed HTML → email (via email_templates.render_email)
  - `.subject`   email subject line
  - `.title`     short in-app notification title

Landlords can still override the wording with their own saved templates; these
are the DEFAULTS applied when no custom template is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

from services import branding
from services import email_templates as T
from services.balance_breakdown import build_breakdown, breakdown_as_lines
from services.message_variables import payment_method_for


# The three default reminder kinds.
KIND_INVOICE = "invoice_notification"
KIND_OVERDUE = "overdue_balance"
KIND_PAYMENT = "payment_reminder"

_KIND_META = {
    KIND_INVOICE: {
        "title": "New invoice",
        "subject": "Your latest invoice from {landlord}",
        "opening": "A new invoice has been raised on your account. Here is exactly what it covers:",
    },
    KIND_OVERDUE: {
        "title": "Overdue balance",
        "subject": "Overdue balance on your account — {landlord}",
        "opening": "Your account is overdue. Please find the full breakdown of what is outstanding below:",
    },
    KIND_PAYMENT: {
        "title": "Payment reminder",
        "subject": "Payment reminder from {landlord}",
        "opening": "This is a friendly reminder about your outstanding balance. Here is exactly what it is made up of:",
    },
}


@dataclass
class ReminderContent:
    title: str
    subject: str
    text: str
    html: str


def _landlord_contact(landlord) -> dict:
    """Company name, location, phone, email for the landlord (contact defaults)."""
    user = getattr(landlord, "user", None)
    return {
        "name": getattr(landlord, "company_name", "") or "Your landlord",
        "location": getattr(landlord, "company_address", None) or branding.BRAND_LOCATION,
        "phone": (getattr(user, "phone", None) if user else None) or "",
        "email": (getattr(user, "email", None) if user else None) or "",
    }


def _payment_lines(landlord, tenant) -> list[tuple[str, str]]:
    """Label/value payment-detail rows the tenant pays to."""
    rows: list[tuple[str, str]] = []
    mpesa_type = getattr(landlord, "mpesa_type", None)
    mpesa_number = getattr(landlord, "mpesa_number", None)
    if mpesa_type and mpesa_number:
        label = "M-Pesa Paybill" if mpesa_type == "paybill" else "M-Pesa Till"
        rows.append((label, str(mpesa_number)))
    acc = getattr(tenant, "account_number", None) or getattr(landlord, "default_account_number", None)
    if acc:
        rows.append(("Account / Reference", str(acc)))
    if getattr(landlord, "payment_instructions", None):
        rows.append(("Instructions", landlord.payment_instructions.strip()))
    return rows


def build_reminder(kind: str, tenant, landlord, *, custom_message: str | None = None) -> ReminderContent:
    """
    Build the default reminder content for `kind`. If `custom_message` is given
    it becomes the opening line, but the breakdown + landlord + payment blocks
    are ALWAYS appended so the guarantee holds even for custom text.
    """
    meta = _KIND_META.get(kind, _KIND_META[KIND_PAYMENT])
    contact = _landlord_contact(landlord)
    currency = getattr(landlord, "currency", None) or "KES"
    breakdown = build_breakdown(tenant)
    item_lines = breakdown_as_lines(breakdown, currency)
    pay_rows = _payment_lines(landlord, tenant)
    total = breakdown["total_due"]

    unit = getattr(tenant, "unit", None)
    prop = getattr(unit, "property", None) if unit else None
    tenant_name = getattr(tenant, "first_name", "") or "there"

    opening = custom_message.strip() if custom_message else meta["opening"]
    subject = meta["subject"].format(landlord=contact["name"])
    title = meta["title"]

    # ── Plain text (SMS / in-app / WhatsApp) ─────────────────────────────────
    text_parts = [f"Dear {tenant_name},", opening, ""]
    if unit:
        text_parts.append(f"Unit: {unit.name}" + (f" · {prop.name}" if prop else ""))
    text_parts.append("Breakdown:")
    text_parts.extend(f"  • {ln}" for ln in item_lines)
    text_parts.append(f"TOTAL DUE: {currency} {total:,.2f}")
    text_parts.append("")
    text_parts.append("Pay to:")
    for lbl, val in pay_rows:
        text_parts.append(f"  {lbl}: {val}")
    text_parts.append("")
    text_parts.append(f"{contact['name']}")
    loc_line = " · ".join(p for p in (contact["location"], contact["phone"], contact["email"]) if p)
    if loc_line:
        text_parts.append(loc_line)
    text = "\n".join(text_parts)

    # ── Themed HTML (email) ──────────────────────────────────────────────────
    blocks = [T.paragraph(T.escape(opening))]
    if unit:
        loc = f"Unit {T.escape(unit.name)}" + (f" · {T.escape(prop.name)}" if prop else "")
        blocks.append(T.note(loc))
    # Breakdown table
    breakdown_rows = [(it["label"] + (" (refundable deposit)" if it["is_deposit"] else ""),
                       f"{currency} {it['amount']:,.2f}") for it in breakdown["items"]]
    breakdown_rows.append(("TOTAL DUE", f"{currency} {total:,.2f}"))
    blocks.append(T.credentials(breakdown_rows))
    # Payment details
    if pay_rows:
        blocks.append(T.note("<strong>How to pay</strong>"))
        blocks.append(T.credentials(pay_rows))
    # Landlord contact
    contact_rows = [("From", contact["name"])]
    if contact["location"]:
        contact_rows.append(("Location", contact["location"]))
    if contact["phone"]:
        contact_rows.append(("Phone", contact["phone"]))
    if contact["email"]:
        contact_rows.append(("Email", contact["email"]))
    blocks.append(T.credentials(contact_rows))

    html = T.render_email(
        heading=f"{title} — {contact['name']}",
        intro=f"Dear {T.escape(tenant_name)},",
        blocks=blocks,
        preheader=f"{title}: {currency} {total:,.2f} outstanding.",
        footer_note=f"Sent by {contact['name']} via Sahil Pay.",
    )

    return ReminderContent(title=title, subject=subject, text=text, html=html)
