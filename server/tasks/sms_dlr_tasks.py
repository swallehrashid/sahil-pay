"""
tasks/sms_dlr_tasks.py — SMS delivery-report (DLR) reconciliation.

A landlord's SMS can be accepted by FluxSMS yet sit as SCHEDULED / SentToNetwork
for a while before it actually reaches the handset (the classic symptom of an
alphanumeric sender ID pending network approval). The synchronous send path can
only record the provider's immediate response; this Celery Beat task polls
FluxSMS's /smsstatus for recently-sent SMS logs that carry a provider message id
and updates communication_logs.status from the real delivery report.

Terminal DLR states (FluxSMS delivery-description):
  DeliveredToTerminal            -> delivered
  Rejected / Expired / Undeliverable / Failed / DeliveryImpossible -> failed
Non-terminal (SentToNetwork, Scheduled, Buffered, ...) are left as-is so the
next sweep re-checks them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery_app import celery

logger = logging.getLogger(__name__)

_DELIVERED_DESCRIPTIONS = {"deliveredtoterminal"}
_FAILED_DESCRIPTIONS = {
    "rejected", "expired", "undeliverable", "failed", "deliveryimpossible",
    "unknownsubscriber", "absentsubscriber",
}
# FluxSMS numeric delivery-status: 32 = DeliveredToTerminal (per spec sample).
_DELIVERED_CODES = {32}


@celery.task(name="tasks.sms_dlr_tasks.reconcile_sms_delivery")
def reconcile_sms_delivery(max_age_hours: int = 48) -> None:
    """
    Sweep recent SMS logs with a provider message id whose status is not yet
    terminal, query FluxSMS, and flip delivered/failed accordingly.
    """
    from app import create_app
    from extensions import db
    from models import CommunicationLog, Landlord, LandlordSettings
    from services.sms_service import get_delivery_status

    app = create_app()
    with app.app_context():
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        rows = (
            CommunicationLog.query
            .filter(
                CommunicationLog.message_type == "sms",
                CommunicationLog.provider_message_id.isnot(None),
                CommunicationLog.status.notin_(["delivered", "failed"]),
                CommunicationLog.sent_at >= cutoff,
            )
            .limit(200)
            .all()
        )
        if not rows:
            return

        updated = 0
        for log in rows:
            # Custom-sender sends must be queried with the landlord's own key.
            api_key = None
            if log.uses_own_sender and log.landlord_id:
                landlord = db.session.get(Landlord, log.landlord_id)
                settings = landlord.landlord_settings if landlord else None
                if settings and settings.sms_connected:
                    api_key = settings.sms_api_key

            try:
                dlr = get_delivery_status(log.provider_message_id, api_key=api_key)
            except Exception:
                logger.warning("reconcile_sms_delivery: /smsstatus failed for log %s.", log.id, exc_info=True)
                continue
            if not dlr:
                continue

            desc = str(dlr.get("delivery-description") or "").strip().lower()
            code = dlr.get("delivery-status")
            if desc in _DELIVERED_DESCRIPTIONS or code in _DELIVERED_CODES:
                log.status = "delivered"
                updated += 1
            elif desc in _FAILED_DESCRIPTIONS:
                log.status = "failed"
                updated += 1
            # else: still in flight — leave for the next sweep.

        if updated:
            db.session.commit()
            logger.info("reconcile_sms_delivery: updated %d SMS log(s) from provider DLR.", updated)
