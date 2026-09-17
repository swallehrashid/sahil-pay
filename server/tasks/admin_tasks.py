"""
SahilPay — tasks/admin_tasks.py
==================================
Platform-level periodic maintenance dispatched by Celery Beat.

§10.4 — trial lifecycle. `check_trial_expirations` runs daily (see the beat
schedule in celery_app.py) and ends every trial whose `trial_ends_at`
has elapsed, so a trial actually stops instead of running forever. The real
work lives in services.trial_service.expire_due_trials so it can also be
called directly (tests, an admin "run now" action, or a shell).
"""

from __future__ import annotations

import logging

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.admin_tasks.check_trial_expirations")
def check_trial_expirations() -> dict:
    """Expire every landlord trial whose end date has passed. Idempotent."""
    from services.trial_service import expire_due_trials

    result = expire_due_trials()
    logger.info("check_trial_expirations: %s trial(s) expired.", result["count"])
    return result


@celery.task(name="tasks.admin_tasks.roll_subscription_billing")
def roll_subscription_billing() -> dict:
    """
    Daily: add every subscription charge whose billing date has passed and
    settle each account's status (active / past due). Idempotent — see
    services/billing_service.py "Balance ledger".
    """
    from extensions import db
    from models import Landlord
    from services import billing_service

    charged = 0
    for landlord in Landlord.query.filter(Landlord.is_demo.is_(False)).all():
        try:
            charged += billing_service.roll_forward(landlord)
            db.session.commit()
        except Exception:                                  # noqa: BLE001
            db.session.rollback()
    return {"charges_added": charged}
