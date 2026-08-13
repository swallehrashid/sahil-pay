"""
tasks/etims_tasks.py — the two monthly KRA nudges (ETIMS spec §4.5).

Both tasks sweep only accounts that have OPTED IN — the account master switch
on plus at least one eTIMS-enabled property — and each nudge has its own
toggle. An account that has never touched the feature is never woken by it,
which is the whole contract of this layer.

Tone matters as much as targeting. Neither message may suggest the landlord is
behind, missing something, or non-compliant: the 5th is "you can do this now",
the 15th is "here is the deadline and here is your report". Nothing here
inspects how many invoices someone has or hasn't recorded.
"""

from __future__ import annotations

from datetime import date

from celery_app import celery
from extensions import db


def _opted_in_landlords():
    """
    Landlords with the master switch on AND at least one enabled property.

    Both halves matter: the master switch alone can be left on by someone who
    later disabled every property, and an enabled property under a switched-off
    account must stay silent.
    """
    from models import Landlord, LandlordSettings, Property

    return (
        db.session.query(Landlord)
        .join(LandlordSettings, LandlordSettings.landlord_id == Landlord.id)
        .filter(LandlordSettings.etims_enabled.is_(True),
                Landlord.is_demo.is_(False),
                db.session.query(Property.id)
                .filter(Property.landlord_id == Landlord.id,
                        Property.is_deleted.is_(False),
                        Property.etims_enabled.is_(True))
                .exists())
        .all()
    )


def _previous_month_label(today: date) -> str:
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return date(year, month, 1).strftime("%B %Y")


@celery.task(name="tasks.etims_tasks.send_etims_record_reminders")
def send_etims_record_reminders() -> dict:
    """
    ~5th of the month, soft sweep: rent has started arriving, the Register is
    there when they want it. Purely informational.
    """
    from flask import current_app
    from services import etims_service as etims
    from services.notification_service import notify

    if not etims.features_enabled():
        return {"sent": 0, "skipped": "features_disabled"}

    sent = 0
    for landlord in _opted_in_landlords():
        settings = landlord.landlord_settings
        if not (settings and settings.etims_reminder_record_enabled):
            continue
        if not landlord.user_id:
            continue
        try:
            notify(
                recipient_user_id = landlord.user_id,
                category          = "etims_record_invoices",
                template_key      = "etims_record_invoices",
                landlord_id       = landlord.id,
                link              = "/landlord/etims-register",
                entity_type       = "etims",
            )
            sent += 1
        except Exception:
            current_app.logger.exception(
                "[etims] record reminder failed for landlord %s", landlord.id)
    db.session.commit()
    return {"sent": sent}


@celery.task(name="tasks.etims_tasks.send_mri_filing_reminders")
def send_mri_filing_reminders() -> dict:
    """15th of the month: last month's MRI is due at KRA by the 20th."""
    from flask import current_app
    from services import etims_service as etims
    from services.notification_service import notify

    if not etims.features_enabled():
        return {"sent": 0, "skipped": "features_disabled"}

    period = _previous_month_label(date.today())
    sent = 0
    for landlord in _opted_in_landlords():
        settings = landlord.landlord_settings
        if not (settings and settings.etims_reminder_filing_enabled):
            continue
        if not landlord.user_id:
            continue
        try:
            notify(
                recipient_user_id = landlord.user_id,
                category          = "mri_filing_due",
                template_key      = "mri_filing_due",
                template_kwargs   = {"period": period},
                landlord_id       = landlord.id,
                link              = "/landlord/reports/kra-monthly",
                entity_type       = "etims",
            )
            sent += 1
        except Exception:
            current_app.logger.exception(
                "[etims] filing reminder failed for landlord %s", landlord.id)
    db.session.commit()
    return {"sent": sent, "period": period}
