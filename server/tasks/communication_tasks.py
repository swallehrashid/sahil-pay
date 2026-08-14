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


@celery.task(name="tasks.communication_tasks.send_owner_monthly_statements")
def send_owner_monthly_statements(run_date=None) -> dict:
    """
    Celery Beat (daily): email every property owner last month's statement for
    each property they own.

    A property manager holds one 'owner'-preset team member per landlord whose
    block they manage, scoped to that landlord's properties. On the landlord's
    configured owner_reports_day, each of those owners gets one PDF per property
    — which is the whole reporting relationship a management company owes the
    owners, automated.

    Demo shadow landlords never send (DEMO_MODE_SPEC.md §3.4). A failure on one
    property is logged and skipped; it never aborts the batch, because one
    broken property must not cost 99 other owners their statement.
    """
    from datetime import date

    from dateutil.relativedelta import relativedelta

    from models import AutomationSettings, Landlord, TeamMember, User
    from services.email_service import send_owner_statement_email
    from services.report_builder import render_document
    from services.report_generators import build_property_statement

    today = run_date or date.today()
    if isinstance(today, str):
        from utils import parse_date
        today = parse_date(today) or date.today()

    # Last complete calendar month.
    period_end = today.replace(day=1) - relativedelta(days=1)
    period_start = period_end.replace(day=1)
    period_label = period_start.strftime("%B %Y")

    totals = {"landlords": 0, "owners": 0, "statements": 0, "errors": 0}

    landlords = (
        Landlord.query
        .join(AutomationSettings, AutomationSettings.landlord_id == Landlord.id)
        .filter(
            Landlord.is_demo.is_(False),
            AutomationSettings.owner_reports_enabled.is_(True),
            AutomationSettings.owner_reports_day == today.day,
        )
        .all()
    )

    for landlord in landlords:
        totals["landlords"] += 1
        owners = (
            TeamMember.query
            .filter_by(landlord_id=landlord.id, preset="owner", is_active=True)
            .all()
        )
        for member in owners:
            user = User.query.get(member.user_id) if member.user_id else None
            email = (user.email if user else None) or None
            if not email:
                continue
            totals["owners"] += 1

            # An owner sees exactly the properties they've been granted. One
            # with property_access_all (unusual, but possible if hand-edited)
            # gets every property of the manager.
            property_ids = [a.property_id for a in member.property_accesses]
            if member.property_access_all:
                property_ids = [p.id for p in landlord.properties if not p.is_deleted]

            for property_id in property_ids:
                try:
                    doc = build_property_statement(
                        landlord, property_id,
                        period_start.isoformat(), period_end.isoformat(),
                    )
                    pdf_bytes = render_document(doc, "pdf", None, None)
                    property_name = (
                        doc.meta.get("property_name")
                        or doc.meta.get("subject")
                        or f"Property {property_id}"
                    )
                    send_owner_statement_email.delay(
                        email,
                        member.first_name or member.username,
                        property_name,
                        period_label,
                        landlord.company_name,
                        pdf_bytes,
                    )
                    totals["statements"] += 1
                except Exception:
                    totals["errors"] += 1
                    logger.exception(
                        "send_owner_monthly_statements: failed for landlord %s property %s",
                        landlord.id, property_id,
                    )

    logger.info("send_owner_monthly_statements(%s): %s", today, totals)
    return totals


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
