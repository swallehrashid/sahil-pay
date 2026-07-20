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
            "Dear {tenant_name}, your rent invoice for {unit} is ready. "
            "Outstanding balance: KES {balance}. Pay via: {payment_method}. "
            "Thank you, {landlord}."
        ),
    },
    {
        "name": "Payment reminder",
        "template_type": "balance_reminder",
        "channel": "sms",
        "body": (
            "Hi {tenant_name}, a friendly reminder that rent for {unit} is due. "
            "Balance: KES {balance}. Kindly pay via: {payment_method}. {landlord}."
        ),
    },
    {
        "name": "Overdue balance",
        "template_type": "balance_reminder",
        "channel": "sms",
        "body": (
            "Dear {tenant_name}, your account for {unit} is overdue. "
            "Outstanding: KES {balance}. Please settle via: {payment_method} to "
            "avoid penalties. {landlord}."
        ),
    },
]
