"""
SahilPay — services/alert_service.py
====================================
The bridge between an EVENT happening and the landlord's ALERT preferences.

`AlertSetting` rows (Settings → Alerts) say, per alert type, whether the
landlord wants to be alerted and on which channel. Nothing consumed them until
this dispatcher: whenever a relevant event fires (a payment comes in, SMS
balance runs low, …), call `dispatch_alert()` and it will — only if that alert
type is enabled — deliver to the chosen channel:

    dashboard  -> in-app Notification (the immediate default)
    email      -> the landlord's email
    sms        -> the landlord's phone (simulated until a provider is wired)
    invoice    -> treated as dashboard for now (invoice-attached alerts TBD)

Realtime alerts are delivered immediately. daily/weekly/monthly cadences are
metadata for a future digest job; we still drop an in-app record so nothing is
silently lost. Like the other services here, it flushes but does not commit —
the caller commits with the event it describes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Alert types that default to ON (dashboard) when the landlord hasn't saved an
# explicit preference — so alerts work out of the box, then honor overrides.
_DEFAULT_ENABLED = True
_DEFAULT_CHANNEL = "dashboard"


def dispatch_alert(
    landlord_id: int,
    alert_type: str,
    *,
    title: str,
    body: str,
    link: str | None = None,
    sms_text: str | None = None,
    email_subject: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
):
    """
    Deliver an alert to the landlord for `alert_type` per their AlertSetting.
    Returns the channel it was delivered on, or None if the alert is disabled
    or the landlord has no usable destination for the chosen channel.
    """
    from flask import current_app

    from extensions import db
    from models import AlertSetting, Landlord
    from services.notification_service import notify

    landlord = db.session.get(Landlord, landlord_id)
    if landlord is None:
        return None

    setting = AlertSetting.query.filter_by(landlord_id=landlord_id, alert_type=alert_type).first()
    enabled = setting.is_enabled if setting else _DEFAULT_ENABLED
    if not enabled:
        logger.info("Alert '%s' disabled for landlord %s — skipping.", alert_type, landlord_id)
        return None
    channel = (setting.channel if setting and setting.channel else _DEFAULT_CHANNEL)

    user = landlord.user
    delivered = None

    if channel in ("dashboard", "invoice"):
        if user:
            notify(
                recipient_user_id=user.id,
                category=f"alert_{alert_type}",
                title=title,
                body=body,
                landlord_id=landlord_id,
                link=link,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            delivered = "dashboard"
    elif channel == "email":
        delivered = _deliver_email(user, email_subject or title, body, current_app)
    elif channel == "sms":
        delivered = _deliver_sms(user, sms_text or f"{title}: {body}", current_app)

    # Always keep an in-app trail even for email/sms channels, so the landlord's
    # notification center still reflects that the alert fired.
    if delivered and delivered != "dashboard" and user:
        notify(
            recipient_user_id=user.id,
            category=f"alert_{alert_type}",
            title=title,
            body=body,
            landlord_id=landlord_id,
            link=link,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    logger.info("Alert '%s' for landlord %s dispatched via %s.", alert_type, landlord_id, delivered or "none")
    return delivered


def _deliver_email(user, subject: str, body: str, app) -> str | None:
    if not user or not user.email:
        return None
    # DEMO_MODE_SPEC.md §3.3 — a demo shadow landlord's own alert emails/SMS
    # must never really send either, regardless of COMMS_SIMULATION_MODE.
    if app.config.get("COMMS_SIMULATION_MODE", True) or _is_demo_user(user):
        logger.info("SIMULATED alert email to %s | %s", user.email, subject)
        return "email"
    from services.email_service import _send_email

    return "email" if _send_email(user.email, subject, f"<p>{body}</p>") else None


def _deliver_sms(user, text: str, app) -> str | None:
    if not user or not user.phone:
        return None
    if app.config.get("COMMS_SIMULATION_MODE", True) or _is_demo_user(user):
        logger.info("SIMULATED alert SMS to %s | %s", user.phone, text)
        return "sms"
    from services.sms_service import send_sms

    return "sms" if send_sms(user.phone, text) else None


def _is_demo_user(user) -> bool:
    profile = getattr(user, "landlord_profile", None)
    return bool(profile and profile.is_demo)
