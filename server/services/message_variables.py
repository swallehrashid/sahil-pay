"""
SahilPay — services/message_variables.py
============================================
§9.1  Universal message variables and the default template catalogue.

Landlords write SMS/message templates once using placeholders like
``{tenant_name}`` or ``{balance}``; at send time each placeholder is replaced
with the specific tenant's / landlord's value. This module owns:

  * UNIVERSAL_VARIABLES — the documented placeholder set shown in the UI,
  * build_context()     — resolve those placeholders for one tenant + landlord,
  * render_message()    — substitute placeholders in a body,
  * DEFAULT_TEMPLATES   — ready-to-use starter templates (invoice, payment
    reminder, overdue balance) that already include the landlord's payment
    method so a landlord can send immediately without writing anything.
"""

from __future__ import annotations

# The placeholder catalogue surfaced to landlords in the template editor.
UNIVERSAL_VARIABLES = [
    {"key": "{tenant_name}",      "label": "Tenant first name"},
    {"key": "{tenant_full_name}", "label": "Tenant full name"},
    {"key": "{unit}",             "label": "Unit name / number"},
    {"key": "{property}",         "label": "Property name"},
    {"key": "{balance}",          "label": "Outstanding balance (KES)"},
    {"key": "{debt}",             "label": "Outstanding balance — alias of {balance}"},
    {"key": "{account_number}",   "label": "Tenant account / reference number"},
    {"key": "{phone}",            "label": "Tenant phone number"},
    {"key": "{landlord}",         "label": "Your company name"},
    {"key": "{payment_method}",   "label": "Your payment instructions / M-Pesa details"},
    {"key": "{breakdown}",        "label": "Itemised breakdown of the tenant's balance"},
    {"key": "{landlord_details}", "label": "Your name, location, phone & email"},
]


def payment_method_for(landlord) -> str:
    """
    A human-readable "how to pay" string for a landlord, preferring their
    free-text payment_instructions, then M-Pesa paybill/till, then account no.
    """
    if landlord is None:
        return ""
    if getattr(landlord, "payment_instructions", None):
        return landlord.payment_instructions.strip()
    parts = []
    mpesa_type = getattr(landlord, "mpesa_type", None)
    mpesa_number = getattr(landlord, "mpesa_number", None)
    if mpesa_type and mpesa_number:
        label = "Paybill" if mpesa_type == "paybill" else "Till"
        parts.append(f"M-Pesa {label} {mpesa_number}")
    if getattr(landlord, "default_account_number", None):
        parts.append(f"Acc {landlord.default_account_number}")
    return " | ".join(parts)


def breakdown_text_for(tenant, landlord) -> str:
    """A one-line-per-charge itemised breakdown + total (plain text)."""
    if tenant is None:
        return ""
    from services.balance_breakdown import build_breakdown, breakdown_as_lines
    currency = (getattr(landlord, "currency", None) or "KES") if landlord else "KES"
    bd = build_breakdown(tenant)
    lines = breakdown_as_lines(bd, currency)
    if not lines:
        return f"Total due: {currency} 0.00"
    body = "; ".join(lines)
    return f"{body}; TOTAL {currency} {bd['total_due']:,.2f}"


def landlord_details_for(landlord) -> str:
    """Landlord name, location, phone & email as a single plain-text line."""
    if landlord is None:
        return ""
    user = getattr(landlord, "user", None)
    from services import branding
    parts = [
        getattr(landlord, "company_name", "") or "",
        getattr(landlord, "company_address", None) or branding.BRAND_LOCATION,
        (getattr(user, "phone", None) if user else None) or "",
        (getattr(user, "email", None) if user else None) or "",
    ]
    return " · ".join(p for p in parts if p)


def build_context(tenant, landlord) -> dict:
    """Resolve every universal variable for one tenant + landlord."""
    unit = getattr(tenant, "unit", None)
    prop = getattr(unit, "property", None) if unit else None
    balance = abs(float(tenant.balance or 0)) if tenant is not None else 0
    balance_str = f"{balance:,.2f}"
    return {
        "{tenant_name}":      (tenant.first_name or "") if tenant else "",
        "{tenant_full_name}": f"{tenant.first_name or ''} {tenant.last_name or ''}".strip() if tenant else "",
        "{unit}":             (unit.name if unit else ""),
        "{property}":         (prop.name if prop else ""),
        "{balance}":          balance_str,
        "{debt}":             balance_str,
        "{account_number}":   (getattr(tenant, "account_number", None) or "") if tenant else "",
        "{phone}":            (getattr(tenant, "phone", None) or "") if tenant else "",
        "{landlord}":         (landlord.company_name if landlord else ""),
        "{payment_method}":   payment_method_for(landlord),
        "{breakdown}":        breakdown_text_for(tenant, landlord),
        "{landlord_details}": landlord_details_for(landlord),
    }


def render_message(body: str, tenant, landlord) -> str:
    """Substitute every universal variable in `body` for this tenant/landlord."""
    if not body:
        return ""
    context = build_context(tenant, landlord)
    rendered = body
    for key, value in context.items():
        rendered = rendered.replace(key, str(value))
    return rendered


# Ready-to-use starter templates. Each already embeds {payment_method} so a
# landlord can send a complete, actionable message with zero editing.
DEFAULT_TEMPLATES = [
    {
        "name": "Invoice notification",
        "template_type": "invoice_reminder",
        "channel": "sms",
        "body": (
            "Dear {tenant_name}, a new invoice for {unit} is ready. "
            "Breakdown: {breakdown}. "
            "Pay via: {payment_method}. "
            "{landlord_details}"
        ),
    },
    {
        "name": "Payment reminder",
        "template_type": "balance_reminder",
        "channel": "sms",
        "body": (
            "Hi {tenant_name}, a friendly reminder for {unit}. "
            "Breakdown: {breakdown}. "
            "Kindly pay via: {payment_method}. "
            "{landlord_details}"
        ),
    },
    {
        "name": "Overdue balance",
        "template_type": "balance_reminder",
        "channel": "sms",
        "body": (
            "Dear {tenant_name}, your account for {unit} is overdue. "
            "Breakdown: {breakdown}. "
            "Please settle via: {payment_method} to avoid penalties. "
            "{landlord_details}"
        ),
    },
    {
        "name": "Welcome message",
        "template_type": "welcome",
        "channel": "sms",
        # The first message a tenant ever gets from their landlord, so it is
        # written to sound like a person welcoming them home rather than a
        # system notification — while still carrying the two things they
        # actually need on day one: how to pay, and who to call.
        "body": (
            "Karibu {tenant_name}! Welcome home to {unit} at {property}. "
            "We're glad to have you with us. "
            "Rent is payable via: {payment_method}. "
            "Anything at all, just reach us on {landlord_details} "
            "Wishing you a wonderful stay. - {landlord}"
        ),
    },
]

# The welcome message used when a landlord has not written their own.
#
# Deliberately emoji-free: a single emoji forces the whole SMS into UCS-2, which
# cuts a segment from 160 characters to 70 and can triple what the landlord pays
# to send it. Warmth here comes from the words, not from pictures.
DEFAULT_WELCOME_BODY = next(
    t["body"] for t in DEFAULT_TEMPLATES if t["template_type"] == "welcome"
)


def welcome_body_for(landlord_id: int) -> str:
    """
    The welcome text for a landlord — their own 'welcome' template when they
    have written one, otherwise the warm default above.
    """
    from models import MessageTemplate

    template = (
        MessageTemplate.query
        .filter_by(landlord_id=landlord_id, template_type="welcome")
        .order_by(MessageTemplate.id.desc())
        .first()
    )
    return (template.body if template and template.body else DEFAULT_WELCOME_BODY)
