"""
SahilPay — services/communication_service.py
================================================
§9.2  The single chokepoint for sending a tenant a message and logging it.
Every outbound message — a custom message, a balance reminder, or an
invoice notification — goes through dispatch_message() (or dispatch_invoice(),
which builds invoice-specific content and delegates to dispatch_message()),
so communication_logs always reflects what was actually sent.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# Flat per-message SMS unit cost — most messages fit in a single SMS segment.
_SMS_UNIT_CHARGE = Decimal("1.00")


def dispatch_message(landlord_id: int, tenant, channel: str, content: str):
    """
    Send *content* to *tenant* over *channel* ("sms" | "whatsapp" | "email"),
    decrementing the landlord's SMS balance for SMS sends, and writing one
    communication_logs row regardless of channel or outcome.

    Does not commit — the caller commits in the same transaction (matches
    every other service in this layer). The returned log is flushed, so
    .id is available immediately.
    """
    from flask import current_app

    from extensions import db
    from models import CommunicationLog, Landlord, SmsPricingConfig
    from services.email_service import _send_email
    from services.sms_service import send_sms
    from services.sms_billing import price_sms, load_rates
    from utils import decrement_sms_balance

    simulate = current_app.config.get("COMMS_SIMULATION_MODE", True)
    # DEMO_MODE_SPEC.md §3.3 — a demo shadow landlord's messages are ALWAYS
    # simulated, no matter the platform's COMMS_SIMULATION_MODE setting. This
    # is layer 1 of the no-real-sends guarantee (layer 2 is that every demo
    # tenant has an obviously fake phone/email — see services/demo_service.py).
    demo_landlord = db.session.get(Landlord, landlord_id)
    is_demo = demo_landlord is not None and demo_landlord.is_demo
    if is_demo:
        simulate = True
    # Destination the message needs to be deliverable at all.
    destination = tenant.email if channel == "email" else getattr(tenant, "phone", None)

    status = "failed"
    sms_charge = Decimal("0.00")
    platform_cost = Decimal("0.00")
    sms_segments = None
    uses_own = False
    sender_id = None
    at_username = None
    at_api_key = None
    blocked = None   # reason string when a shared send can't proceed

    if channel == "sms":
        # §9.3 reselling charge model: own connected sender ID (custom) → custom
        # price; SahilPay's shared sender ID (default) → default price by length,
        # delivered out of the shared pool.
        landlord = demo_landlord if demo_landlord is not None else db.session.get(Landlord, landlord_id)
        settings = landlord.landlord_settings if landlord else None
        rates = load_rates()
        econ = price_sms(content, settings, rates)
        sender_id    = econ["sender_id"]
        uses_own     = econ["uses_own_sender_id"]
        sms_segments = econ["segments"]
        if uses_own and settings is not None:
            at_username = settings.at_username
            at_api_key = settings.at_api_key

        cfg = None
        if not uses_own and not is_demo:
            # Shared (default) sends are gated by the master toggle and the
            # shared pool balance; custom sends never touch the pool. A demo
            # shadow never draws from the real shared pool or shows up in
            # platform SMS revenue — its "balance" is decremented below for a
            # realistic training experience, but nothing platform-facing moves.
            cfg = SmsPricingConfig.get_singleton()
            if not rates["shared_enabled"]:
                blocked = "Shared-sender sending is disabled by the administrator."
            elif cfg.pool_balance < sms_segments:
                blocked = "SahilPay shared SMS pool is exhausted."

        if not blocked:
            if not is_demo:
                sms_charge    = econ["charge"]
                platform_cost = econ["platform_cost"]
            if landlord is not None:
                # Decrement one balance credit per segment (balance is a credit
                # count; the resale price only affects KES billed at purchase).
                decrement_sms_balance(landlord, sms_segments)
            if not uses_own and cfg is not None:
                cfg.pool_balance = max(0, cfg.pool_balance - sms_segments)

    if channel == "sms" and blocked:
        logger.warning("dispatch_message: SMS to tenant %s blocked — %s", tenant.id, blocked)
        status = "failed"
    elif channel not in ("sms", "email", "whatsapp"):
        logger.warning("dispatch_message: unknown channel '%s'", channel)
        status = "failed"
    elif simulate:
        # No external API call — mark delivered when there's a destination to
        # deliver to, failed otherwise. Flip COMMS_SIMULATION_MODE off + add the
        # provider key to switch to real sending with no other change.
        status = "delivered" if destination else "failed"
        logger.info("SIMULATED %s to tenant %s → %s (from %s, %s)", channel, tenant.id, status, sender_id or "-", destination or "no destination")
    elif not destination:
        status = "failed"
    elif channel == "sms":
        status = "delivered" if send_sms(tenant.phone, content, sender_id=sender_id, username=at_username, api_key=at_api_key) else "failed"
    elif channel == "email":
        status = "delivered" if _send_email(tenant.email, "Message from your landlord", f"<p>{content}</p>") else "failed"
    elif channel == "whatsapp":
        # Real WhatsApp Business API not wired yet — nothing is delivered until
        # it is; simulation mode above is the working path for now.
        logger.info("WhatsApp [not implemented] to %s: %s", getattr(tenant, "phone", None), content)
        status = "failed"

    unit = getattr(tenant, "unit", None)
    log = CommunicationLog(
        landlord_id=landlord_id,
        message_type=channel,
        recipient_type="tenant",
        tenant_id=tenant.id,
        property_id=unit.property_id if unit else None,
        unit_id=tenant.unit_id,
        content=content,
        sms_charge=sms_charge,
        sms_segments=sms_segments,
        uses_own_sender=uses_own,
        platform_cost=platform_cost,
        status=status,
        sent_at=datetime.utcnow(),
    )
    db.session.add(log)
    db.session.flush()
    return log


def dispatch_invoice(invoice, channel: str):
    """
    Build the invoice-notification content and send it to the invoice's
    tenant over *channel*. Used by invoice_routes.py's "send invoice" action.
    """
    tenant = invoice.tenant
    due = invoice.due_date.isoformat() if invoice.due_date else "immediately"
    content = (
        f"Dear {tenant.first_name}, your {invoice.invoice_type} invoice {invoice.invoice_number} "
        f"for KES {invoice.total_amount} is due {due}. Outstanding balance: KES {invoice.balance}."
    )
    return dispatch_message(landlord_id=invoice.landlord_id, tenant=tenant, channel=channel, content=content)
