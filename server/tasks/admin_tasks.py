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
