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
    from extensions import db
    from models import CommunicationLog, Landlord
    from services.email_service import _send_email
    from services.sms_service import send_sms
    from utils import decrement_sms_balance

    status = "failed"
    sms_charge = Decimal("0.00")

    if channel == "sms":
        result = send_sms(tenant.phone, content)
        status = "delivered" if result else "pending"
        sms_charge = _SMS_UNIT_CHARGE
        landlord = db.session.get(Landlord, landlord_id)
        if landlord is not None:
            decrement_sms_balance(landlord)
    elif channel == "email":
        sent = _send_email(tenant.email, "Message from your landlord", f"<p>{content}</p>")
        status = "delivered" if sent else "pending"
    elif channel == "whatsapp":
        # WhatsApp Business API isn't wired yet — logged so the flow still
        # completes; nothing is actually delivered until that's built.
        logger.info("WhatsApp [stub — not implemented] to %s: %s", getattr(tenant, "phone", None), content)
        status = "pending"
    else:
        logger.warning("dispatch_message: unknown channel '%s'", channel)

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
