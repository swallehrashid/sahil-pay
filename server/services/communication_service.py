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


def _no_destination_reason(channel: str) -> str:
    """Say WHICH detail is missing. "Failed" alone sends people looking at the
    provider when the actual problem is a blank phone number on the tenancy."""
    if channel == "email":
        return "No email address is recorded for this recipient."
    if channel == "in_app":
        return "No Sahil Pay account is linked to this recipient."
    return "No phone number is recorded for this recipient."


def dispatch_message(landlord_id: int, tenant, channel: str, content: str,
                     *, email_subject: str | None = None, email_html: str | None = None,
                     recipient_type: str = "tenant"):
    """
    Send *content* to *tenant* over *channel* ("sms" | "whatsapp" | "email"),
    decrementing the landlord's SMS balance for SMS sends, and writing one
    communication_logs row regardless of channel or outcome.

    For the email channel, `email_html` (a full themed HTML body, e.g. from
    reminder_content / email_templates.render_email) and `email_subject` are
    used when provided; otherwise `content` is wrapped in the branded shell so
    NO landlord→tenant email ever goes out as plain, unstyled text.

    For SMS, the landlord's own credit balance is checked BEFORE attempting a
    send (regardless of default vs custom sender — a custom sender still
    consumes credits at the admin-set custom rate) and the charge/decrement
    only happens AFTER a send actually succeeds (or is simulated as
    delivered) — a failed provider call never burns credits.

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
    #
    # `tenant` is any recipient with the same shape — a Tenant or a TeamMember.
    # A team member has no email column of its own (it lives on their User row),
    # and an in-app message needs a linked account rather than a phone or an
    # address, so both are resolved here rather than at every call site.
    if channel == "in_app":
        destination = getattr(tenant, "user_id", None)
    elif channel == "email":
        destination = getattr(tenant, "email", None)
        if destination is None:
            user = getattr(tenant, "user", None)
            destination = getattr(user, "email", None)
    else:
        destination = getattr(tenant, "phone", None)

    status = "failed"
    sms_charge = Decimal("0.00")
    platform_cost = Decimal("0.00")
    sms_segments = None
    sms_credits = None
    uses_own = False
    sender_id = None
    sms_api_key = None
    provider_message_id = None
    blocked = None   # reason string when a send can't proceed
    # Why a message failed, in words the sender can act on. Held separately
    # from `blocked` because a send can also fail AFTER passing the gates — no
    # phone number on the tenancy, a provider rejection — and every one of
    # those used to surface as an unexplained "Failed" in the log while the
    # sender was shown a green "Sent to 1 recipient".
    failure_reason = None
    landlord = None
    cfg = None
    econ = None

    if channel == "sms":
        # §9.3 reselling charge model: own connected sender ID (custom) → custom
        # price; SahilPay's shared sender ID (default) → default price by length,
        # delivered out of the shared pool. Both models consume the landlord's
        # own credit balance — custom senders are NOT exempt from the gate.
        landlord = demo_landlord if demo_landlord is not None else db.session.get(Landlord, landlord_id)
        settings = landlord.landlord_settings if landlord else None
        rates = load_rates()
        econ = price_sms(content, settings, rates)
        sender_id    = econ["sender_id"]
        uses_own     = econ["uses_own_sender_id"]
        sms_segments = econ["segments"]
        # Credits (from the admin word→credit tiers) are the billed/decremented
        # unit — a long message can cost several credits.
        sms_credits  = econ["credits"]
        # Deliberately NOT the landlord's own key. Every alphanumeric sender ID
        # is registered with FluxSMS on SahilPay's account, so the platform key
        # is what delivers it — a branded sender ID changes the name on the
        # handset, not whose credits pay for it. send_sms() falls back to the
        # platform key when api_key is None.

        if landlord is not None and not is_demo and (landlord.sms_balance or 0) < sms_credits:
            blocked = "Insufficient SMS balance — top up to keep sending."

        if not blocked and not is_demo:
            # EVERY send is gated by the pool, branded sender or not: the
            # credits come out of SahilPay's FluxSMS account either way. The
            # master toggle still only governs the shared SAHILPAY sender,
            # since switching that off should not strand a landlord who has
            # their own registered name. A demo shadow never draws from the
            # real pool or shows up in platform SMS revenue.
            cfg = SmsPricingConfig.get_singleton()
            if not uses_own and not rates["shared_enabled"]:
                blocked = "Shared-sender sending is disabled by the administrator."
            elif cfg.pool_balance < sms_credits:
                blocked = "Sahil Pay SMS pool is exhausted."

    if channel == "sms" and blocked:
        logger.warning("dispatch_message: SMS to tenant %s blocked — %s", tenant.id, blocked)
        status = "failed"
        failure_reason = blocked
    elif channel not in ("sms", "email", "whatsapp", "in_app"):
        logger.warning("dispatch_message: unknown channel '%s'", channel)
        status = "failed"
        failure_reason = f"'{channel}' is not a channel this system can send on."
    elif channel == "in_app":
        # Deliberately BEFORE the simulation branch. Simulation exists to avoid
        # calling an external provider and spending real money; an in-app
        # notification has neither, so stubbing it would mean a demo or a test
        # environment silently produced no notification at all.
        if not destination:
            status = "failed"          # no linked account to notify
            failure_reason = ("No Sahil Pay account is linked to this recipient, "
                              "so there is nowhere to deliver an in-app message.")
        else:
            from services.notification_service import notify
            notify(
                recipient_user_id=destination,
                category="landlord_message",
                title="A message from your landlord",
                body=content,
                landlord_id=landlord_id,
            )
            status = "delivered"
    elif simulate:
        # No external API call — mark delivered when there's a destination to
        # deliver to, failed otherwise. Flip COMMS_SIMULATION_MODE off + add the
        # provider key to switch to real sending with no other change.
        status = "delivered" if destination else "failed"
        if status == "failed":
            failure_reason = _no_destination_reason(channel)
        logger.info("SIMULATED %s to tenant %s → %s (from %s, %s)", channel, tenant.id, status, sender_id or "-", destination or "no destination")
    elif not destination:
        status = "failed"
        failure_reason = _no_destination_reason(channel)
    elif channel == "sms":
        provider_message_id = send_sms(tenant.phone, content, sender_id=sender_id, api_key=sms_api_key)
        status = "delivered" if provider_message_id else "failed"
        if status == "failed":
            failure_reason = ("The SMS provider did not accept the message. "
                              "Check the sender ID is approved on the network.")
    elif channel == "email":
        # Every landlord→tenant email is Sahil-themed: use the caller's themed
        # HTML when given, else wrap the plain content in the branded shell.
        from services.email_templates import render_email, paragraph, escape
        landlord_for_email = landlord or db.session.get(Landlord, landlord_id)
        subject = email_subject or "A message from your landlord"
        if email_html:
            html_body = email_html
        else:
            sender_name = getattr(landlord_for_email, "company_name", None) or "your landlord"
            html_body = render_email(
                heading="A message from your landlord",
                blocks=[paragraph(escape(content).replace("\n", "<br>"))],
                preheader=content[:90],
                footer_note=f"Sent by {sender_name} via Sahil Pay.",
            )
        status = "delivered" if _send_email(tenant.email, subject, html_body) else "failed"
        if status == "failed":
            failure_reason = "The email provider rejected the message."
    elif channel == "whatsapp":
        # Real WhatsApp Business API not wired yet — nothing is delivered until
        # it is; simulation mode above is the working path for now.
        logger.info("WhatsApp [not implemented] to %s: %s", getattr(tenant, "phone", None), content)
        status = "failed"
        failure_reason = "WhatsApp sending is not connected on this system yet."

    # Charge/decrement only AFTER the outcome is known, and only when the SMS
    # actually went out (or was simulated as delivered) — a failed send never
    # burns credits or records platform cost.
    if channel == "sms" and not blocked and status == "delivered":
        if not is_demo:
            sms_charge    = econ["charge"]
            platform_cost = econ["platform_cost"]
        if landlord is not None:
            # Decrement the landlord's balance by the message's CREDIT cost
            # (from the admin word→credit tiers); the resale price only affects
            # KES billed at purchase.
            decrement_sms_balance(landlord, sms_credits)
        if cfg is not None:
            # Branded senders included — the credits left SahilPay's FluxSMS
            # account regardless of the name printed on the message.
            cfg.pool_balance = max(0, cfg.pool_balance - sms_credits)

    is_team_member = recipient_type == "team_member"
    unit = None if is_team_member else getattr(tenant, "unit", None)
    log = CommunicationLog(
        landlord_id=landlord_id,
        message_type=channel,
        recipient_type=recipient_type,
        tenant_id=None if is_team_member else tenant.id,
        team_member_id=tenant.id if is_team_member else None,
        property_id=unit.property_id if unit else None,
        unit_id=None if is_team_member else getattr(tenant, "unit_id", None),
        content=content,
        sms_charge=sms_charge,
        sms_segments=sms_segments,
        uses_own_sender=uses_own,
        platform_cost=platform_cost,
        status=status,
        failure_reason=failure_reason,
        provider_message_id=provider_message_id,
        sent_at=datetime.utcnow(),
    )
    db.session.add(log)
    db.session.flush()
    return log


def dispatch_invoice(invoice, channel: str):
    """
    Build the invoice-notification content and send it to the invoice's
    tenant over *channel*. Used by invoice_routes.py's "send invoice" action.

    Uses the default themed reminder content (itemised breakdown + landlord
    details + payment details) so an invoice notification is never a bare
    "balance is X" line — the same guarantee as every other reminder.
    """
    from extensions import db
    from models import Landlord
    from services.reminder_content import build_reminder, KIND_INVOICE

    tenant = invoice.tenant
    landlord = db.session.get(Landlord, invoice.landlord_id)
    rc = build_reminder(KIND_INVOICE, tenant, landlord)
    return dispatch_message(
        landlord_id=invoice.landlord_id, tenant=tenant, channel=channel,
        content=rc.text, email_subject=rc.subject, email_html=rc.html,
    )
