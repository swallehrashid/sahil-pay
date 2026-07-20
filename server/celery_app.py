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

from config import get_config

_cfg = get_config()

celery = Celery(
    "sahilpay",
    broker=_cfg.CELERY_BROKER_URL,
    backend=_cfg.CELERY_RESULT_BACKEND,
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

# NOTE: the Celery Beat schedule (monthly invoices, trial expiry, etc.) is
# already defined in app.py::make_celery() for when that's wired up via
# `celery -A celery_app beat`. Not duplicated here to avoid two schedules
# drifting apart — out of scope for getting the API layer running today.
