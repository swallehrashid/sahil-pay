"""
SahilPay — tasks/penalty_tasks.py
====================================
Nightly application of per-property late-payment penalties.

Runs EVERY day rather than on a fixed date, because each property carries its
own trigger: one block charges on the 6th, another five days after each
tenant's own invoice due date. A single monthly job could not serve both.
services/penalty_service.py decides, per property and per tenant, whether today
is that day — this module only walks the accounts and owns the transaction.

Safety: the once-per-month guarantee is a partial unique index on
penalty_charges, not a check in this file. That matters because a Celery task
can be retried, run twice by an operator, or executed by two workers at once,
and none of those may fine a tenant twice.
"""

from __future__ import annotations

import logging
from datetime import date

from celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="tasks.penalty_tasks.apply_due_penalties")
def apply_due_penalties(run_date: str | None = None) -> dict:
    """
    Apply every property's penalty policy that falls due today.

    Each landlord is committed separately so one account's bad data cannot roll
    back another's charges — the same isolation the billing task uses.
    """
    from app import create_app
    from extensions import db
    from models import Landlord
    from services import penalty_service as penalties
    from utils import parse_date

    app = create_app()
    with app.app_context():
        today = parse_date(run_date) or date.today()

        landlords = (
            db.session.query(Landlord)
            .filter(Landlord.is_demo.is_(False))    # demo shadows never bill
            .all()
        )

        total_charged, total_amount, failures = 0, 0.0, []
        for landlord in landlords:
            try:
                summary = penalties.run_for_landlord(landlord.id, today=today)
                if summary["charged"]:
                    db.session.commit()
                    total_charged += summary["charged"]
                    total_amount += summary["total"]
                    logger.info(
                        "Penalties: landlord %s charged %s tenants, total %s",
                        landlord.id, summary["charged"], summary["total"],
                    )
                else:
                    db.session.rollback()
            except Exception as exc:            # one account must not stop the rest
                db.session.rollback()
                failures.append({"landlord_id": landlord.id, "error": str(exc)})
                logger.exception("Penalty run failed for landlord %s", landlord.id)

        result = {
            "date": today.isoformat(),
            "landlords_scanned": len(landlords),
            "charged": total_charged,
            "total": round(total_amount, 2),
            "failures": failures,
        }
        logger.info("Penalty run complete: %s", result)
        return result
