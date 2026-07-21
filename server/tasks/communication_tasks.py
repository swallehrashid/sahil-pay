"""
SahilPay — tasks/communication_tasks.py
==========================================
Bulk tenant messaging, dispatched from tenant_routes.py's "bulk reminder"
action via .delay() so the request returns immediately instead of blocking
on N individual sends.
"""

from __future__ import annotations

import logging
import time

from celery_app import celery

logger = logging.getLogger(__name__)

# FluxSMS allows 100 requests/minute per API key. Throttle bulk sends to stay
# comfortably under that (~80/min) instead of bursting the whole batch at once.
SMS_SEND_INTERVAL_SECONDS = 0.75


@celery.task(name="tasks.communication_tasks.send_bulk_reminders")
def send_bulk_reminders(landlord_id: int, tenant_ids: list[int], channel: str, message: str | None) -> dict:
    """
    Send a reminder to every tenant in *tenant_ids*. When *message* is not
    given, falls back to a generic balance-due reminder built from each
    tenant's own balance (so the same task works for both "send this exact
    text" and "send everyone their personalized balance reminder").
    """
    from flask import current_app

    from extensions import db
    from models import Tenant
    from services.communication_service import dispatch_message

    simulate = current_app.config.get("COMMS_SIMULATION_MODE", True)
    tenants = db.session.query(Tenant).filter(Tenant.id.in_(tenant_ids), Tenant.landlord_id == landlord_id).all()

    sent, failed = 0, 0
    for i, tenant in enumerate(tenants):
        content = message or (
            f"Dear {tenant.first_name}, your current balance with us is KES {tenant.balance}. "
            f"Kindly clear this at your earliest convenience."
        )
        try:
            dispatch_message(landlord_id=landlord_id, tenant=tenant, channel=channel, content=content)
            sent += 1
        except Exception:
            logger.error("send_bulk_reminders: failed for tenant #%s", tenant.id, exc_info=True)
            failed += 1

        # Throttle real SMS sends only — simulation never calls the provider.
        if channel == "sms" and not simulate and i < len(tenants) - 1:
            time.sleep(SMS_SEND_INTERVAL_SECONDS)

    db.session.commit()
    return {"sent": sent, "failed": failed}
