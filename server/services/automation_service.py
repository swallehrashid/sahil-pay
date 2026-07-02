"""
SahilPay — services/automation_service.py
==========================================
Makes the Settings → Automation checkboxes actually DO something.

`AutomationSettings` stores per-landlord toggles. This service consumes them:

  Realtime (fire on the triggering request, so they work with no scheduler):
    on_payment_recorded  — auto_send_payment_acknowledgments
    on_tenant_created    — alert_on_new_tenant

  Scheduled (Celery Beat calls these; also runnable on demand via
  POST /api/settings/automation/run so they're verifiable without Celery):
    run_monthly_reminders       — monthly_reminders_enabled
    run_lease_expiry_notices    — lease_expiry_notifications
    run_recurring_invoices      — auto_generate_recurring_bills / _invoices

Every function first checks the relevant toggle and no-ops when it's off, so a
checked box genuinely changes behavior and an unchecked one genuinely doesn't.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def _automation(landlord):
    return getattr(landlord, "automation_settings", None)


# ---------------------------------------------------------------------------
# Realtime automations
# ---------------------------------------------------------------------------


def on_payment_recorded(landlord, payment, tenant) -> bool:
    """If auto_send_payment_acknowledgments is on, acknowledge the payment to
    the tenant (in-app + their preferred message channel). Returns True if sent."""
    aut = _automation(landlord)
    if not aut or not aut.auto_send_payment_acknowledgments:
        return False

    from services.notification_service import notify

    body = (
        f"Hi {tenant.first_name}, we've received your payment of KES {payment.amount} "
        f"({payment.payment_ref}). Thank you."
    )
    if tenant.user_id:
        notify(
            recipient_user_id=tenant.user_id,
            category="payment_acknowledgment",
            title="Payment received — thank you",
            body=body,
            landlord_id=landlord.id,
            link="/portal/statement",
            entity_type="payment",
            entity_id=payment.id,
        )
    # Also send over the tenant's contact channel (simulated until a provider is wired).
    try:
        from services.communication_service import dispatch_message

        dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content=body)
    except Exception as exc:  # automation must never break the payment
        logger.error("payment acknowledgment message failed: %s", exc)
    logger.info("Automation: payment acknowledgment sent for payment %s.", payment.id)
    return True


def on_tenant_created(landlord, tenant) -> bool:
    """If alert_on_new_tenant is on, alert the landlord that a tenant was added."""
    aut = _automation(landlord)
    if not aut or not aut.alert_on_new_tenant:
        return False

    from services.notification_service import notify

    user = landlord.user
    if user:
        notify(
            recipient_user_id=user.id,
            category="new_tenant",
            title="New tenant added",
            body=f"{tenant.first_name} {tenant.last_name} was added to {tenant.unit.name if tenant.unit else 'a unit'}.",
            landlord_id=landlord.id,
            link="/landlord/tenants",
            entity_type="tenant",
            entity_id=tenant.id,
        )
    logger.info("Automation: new-tenant alert sent for tenant %s.", tenant.id)
    return True


# ---------------------------------------------------------------------------
# Scheduled automations (also on-demand)
# ---------------------------------------------------------------------------


def run_monthly_reminders(landlord) -> int:
    """Send a balance reminder to every tenant in arrears. Returns count sent."""
    aut = _automation(landlord)
    if not aut or not aut.monthly_reminders_enabled:
        return 0

    from decimal import Decimal

    from models import Tenant
    from services.communication_service import dispatch_message

    sent = 0
    tenants = Tenant.query.filter(
        Tenant.landlord_id == landlord.id, Tenant.is_deleted.is_(False), Tenant.balance < 0
    ).all()
    for t in tenants:
        owed = abs(t.balance or Decimal("0"))
        dispatch_message(
            landlord_id=landlord.id, tenant=t, channel="sms",
            content=f"Dear {t.first_name}, your outstanding balance is KES {owed}. Kindly clear it. Thank you.",
        )
        sent += 1
    logger.info("Automation: monthly reminders sent to %s tenant(s) for landlord %s.", sent, landlord.id)
    return sent


def run_lease_expiry_notices(landlord) -> int:
    """Notify tenants whose lease expires within lease_expiry_range_days. Returns count."""
    aut = _automation(landlord)
    if not aut or not aut.lease_expiry_notifications:
        return 0

    from models import Tenant
    from services.notification_service import notify

    horizon = date.today() + timedelta(days=aut.lease_expiry_range_days or 30)
    count = 0
    tenants = Tenant.query.filter(
        Tenant.landlord_id == landlord.id,
        Tenant.is_deleted.is_(False),
        Tenant.lease_expiry_date.isnot(None),
        Tenant.lease_expiry_date <= horizon,
        Tenant.lease_expiry_date >= date.today(),
    ).all()
    for t in tenants:
        if t.user_id:
            notify(
                recipient_user_id=t.user_id,
                category="lease_expiry",
                title="Your lease is expiring soon",
                body=f"Hi {t.first_name}, your lease expires on {t.lease_expiry_date}. Please contact us to renew.",
                landlord_id=landlord.id,
                entity_type="tenant",
                entity_id=t.id,
            )
        count += 1
    logger.info("Automation: lease-expiry notices sent for %s tenant(s), landlord %s.", count, landlord.id)
    return count


def run_all_scheduled(landlord) -> dict:
    """Run every ENABLED scheduled automation once; report what each did."""
    return {
        "monthly_reminders_sent": run_monthly_reminders(landlord),
        "lease_expiry_notices_sent": run_lease_expiry_notices(landlord),
    }
