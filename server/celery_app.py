"""
SahilPay — celery_app.py
==========================
Celery worker / beat entrypoint:

    celery -A celery_app worker --loglevel=info
    celery -A celery_app beat --loglevel=info

services/email_service.py, services/sms_service.py, and every module under
tasks/ do `from celery_app import celery` at module level (so `@celery.task`
can decorate their functions at import time). Those same modules are
imported by routes/*.py — some of them at the top of the file — which are
in turn imported by app.py's create_app() while it registers blueprints.

That means this module must NEVER import app.py's `app` at module level:
doing so would recreate the exact cycle that broke `flask db init` earlier
(app.py → routes → services/email_service → celery_app → app.py, with the
last hop landing back on a partially-initialized module). So this builds
the Celery instance from plain config (no Flask app required), and only
touches the Flask app lazily, inside ContextTask, at task-EXECUTION time —
by which point app.py has always finished importing.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from config import get_config

_cfg = get_config()

# Every module that defines a @celery.task. Celery imports these AFTER the
# app object below is fully built, so this does NOT reintroduce the circular
# import the module docstring warns about (app.py is still only touched
# lazily, inside _ContextTask, at task-execution time).
#
# Without this the worker registers zero tasks and rejects everything the
# web process queues with "Received unregistered task of type ...", because
# task registration otherwise only happens as a side-effect of
# app.py::create_app() importing routes/* — which the worker never runs.
TASK_MODULES = [
    "services.email_service",
    "services.sms_service",
    "tasks.admin_tasks",
    "tasks.backup_tasks",
    "tasks.communication_tasks",
    "tasks.invoice_tasks",
    "tasks.mpesa_reconciliation_tasks",
    "tasks.payment_tasks",
]

celery = Celery(
    "sahilpay",
    broker=_cfg.CELERY_BROKER_URL,
    backend=_cfg.CELERY_RESULT_BACKEND,
    include=TASK_MODULES,
)

celery.conf.update(
    task_always_eager=getattr(_cfg, "CELERY_TASK_ALWAYS_EAGER", False),
    timezone=getattr(_cfg, "CELERY_TIMEZONE", "Africa/Nairobi"),
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


class _ContextTask(celery.Task):
    """Pushes a Flask app context for every task so bodies can use db.session / current_app."""

    abstract = True

    def __call__(self, *args, **kwargs):
        from app import app as flask_app  # lazy on purpose — see module docstring

        with flask_app.app_context():
            return super().__call__(*args, **kwargs)


celery.Task = _ContextTask


# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------
# This lives here, not in app.py::make_celery(), because `celery -A
# celery_app:celery beat` only ever sees THIS instance. make_celery() builds a
# separate Celery object that nothing calls, so the schedule it defined was
# never loaded by the running beat process.
#
# Only tasks that actually exist and are registered via TASK_MODULES are
# scheduled. make_celery() also referenced three that have no Celery task
# behind them — tasks.billing_tasks.generate_recurring_expenses,
# tasks.notification_tasks.lease_expiry_notifications and
# .low_sms_balance_alerts (no such modules; the lease-expiry/SMS-balance logic
# exists only as per-landlord helpers in services/automation_service.py, with
# no task wrapper). Scheduling those would make Beat raise NotRegistered on
# every tick, so they are deliberately left out until a real task wraps them.
#
# No per-entry {"queue": ...} routing here on purpose: the deployed worker
# (deploy/systemd/sahilpay-celery.service) runs without -Q, so it consumes
# only the default queue. Routing these to a "periodic" queue — as the old
# make_celery() schedule did — would leave Beat publishing jobs no worker
# ever drains, failing silently with nothing in the logs.

celery.conf.beat_schedule = {
    # 1st of every month at 00:05 Africa/Nairobi — month-end billing +
    # rollover for every landlord.
    "generate-monthly-invoices": {
        "task": "tasks.invoice_tasks.run_monthly_billing_all",
        "schedule": crontab(day_of_month="1", hour="0", minute="5"),
    },
    # Daily at 00:30 — expire trials whose trial_ends_at has passed.
    "check-trial-expirations": {
        "task": "tasks.admin_tasks.check_trial_expirations",
        "schedule": crontab(hour="0", minute="30"),
    },
    # Every 5 minutes — sweep up STK pushes whose Daraja callback never
    # arrived and flag stuck B2C payouts. No-ops while MPESA_SIMULATION_MODE.
    "reconcile-pending-mpesa": {
        "task": "tasks.mpesa_reconciliation_tasks.reconcile_pending_mpesa",
        "schedule": crontab(minute="*/5"),
    },
}
