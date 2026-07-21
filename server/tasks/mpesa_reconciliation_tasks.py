"""
SahilPay — tasks/mpesa_reconciliation_tasks.py
================================================
MPESA_INTEGRATION_SPEC.md §9 — sweeps up STK pushes whose Daraja callback
never arrived (network blip, Daraja outage, tenant closed the app before the
webhook landed) and stuck B2C payouts. Skipped entirely in simulation mode,
since there is no external Daraja state to reconcile against.

Runs every 5 minutes via Celery Beat (see celery_app.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery_app import celery

logger = logging.getLogger(__name__)

_STALE_AFTER = timedelta(minutes=3)
_EXPIRE_AFTER = timedelta(hours=24)
_STUCK_B2C_AFTER = timedelta(minutes=30)
_MAX_QUERIES_PER_RUN = 20

# Daraja ResultCode values that are DEFINITIVE failures — safe to mark failed
# without further inquiry. Any other non-zero code is ambiguous; leave it for
# the next run rather than guessing.
_DEFINITIVE_FAILURE_CODES = {1032, 1037, 1}  # cancelled, timeout, insufficient funds


@celery.task(name="tasks.mpesa_reconciliation_tasks.reconcile_pending_mpesa")
def reconcile_pending_mpesa() -> None:
    from flask import current_app

    if current_app.config.get("MPESA_SIMULATION_MODE", True):
        return

    _reconcile_stale_stk()
    _expire_ancient_pending()
    _flag_stuck_b2c()


def _reconcile_stale_stk() -> None:
    """Pending STK-originated BillingTransactions whose callback never
    arrived: query Daraja directly for the definitive outcome."""
    from extensions import db
    from models import BillingTransaction, BillingTransactionStatus
    from services import billing_service, daraja_service
    from services.daraja_service import DarajaError

    cutoff_recent = datetime.utcnow() - _STALE_AFTER
    cutoff_old = datetime.utcnow() - _EXPIRE_AFTER

    candidates = (
        BillingTransaction.query
        .filter(
            BillingTransaction.status == BillingTransactionStatus.pending.value,
            BillingTransaction.is_verified.is_(False),
            BillingTransaction.payment_reference.isnot(None),
            BillingTransaction.payment_reference.like("ws_CO_%"),
            BillingTransaction.created_at <= cutoff_recent,
            BillingTransaction.created_at > cutoff_old,
        )
        .order_by(BillingTransaction.created_at.asc())
        .limit(_MAX_QUERIES_PER_RUN)
        .all()
    )

    for txn in candidates:
        try:
            resp = daraja_service.stk_query(txn.payment_reference)
        except DarajaError:
            logger.warning("reconcile_pending_mpesa: stk_query failed for txn %s.", txn.id, exc_info=True)
            continue

        result_code = resp.get("ResultCode")
        if result_code is None:
            continue

        try:
            result_code = int(result_code)
        except (TypeError, ValueError):
            continue

        if result_code == 0:
            if txn.type == "sms_purchase":
                billing_service.finalize_sms_purchase(txn)
            else:
                billing_service.finalize_subscription_payment(txn)
            db.session.commit()
            logger.info("reconcile_pending_mpesa: txn %s verified via stk_query sweep.", txn.id)
        elif result_code in _DEFINITIVE_FAILURE_CODES:
            billing_service.mark_subscription_payment_failed(txn)
            db.session.commit()
            logger.info("reconcile_pending_mpesa: txn %s marked failed (code %s).", txn.id, result_code)
        # else: ambiguous — leave pending for the next sweep.


def _expire_ancient_pending() -> None:
    """Pending STK transactions older than 24h — Daraja will never call back
    this late; stop carrying them as pending forever."""
    from extensions import db
    from models import BillingTransaction, BillingTransactionStatus
    from services import billing_service

    cutoff = datetime.utcnow() - _EXPIRE_AFTER
    stale = (
        BillingTransaction.query
        .filter(
            BillingTransaction.status == BillingTransactionStatus.pending.value,
            BillingTransaction.is_verified.is_(False),
            BillingTransaction.created_at <= cutoff,
        )
        .all()
    )
    for txn in stale:
        billing_service.mark_subscription_payment_failed(txn)
    if stale:
        db.session.commit()
        logger.info("reconcile_pending_mpesa: expired %d stale pending transaction(s).", len(stale))


def _flag_stuck_b2c() -> None:
    """B2C payouts sent but never got a result/timeout callback — notify
    admins once (never auto-retry a money movement)."""
    from extensions import db
    from models import AffiliateWithdrawal, User, UserRole
    from services.notification_service import notify_many

    cutoff = datetime.utcnow() - _STUCK_B2C_AFTER
    stuck = (
        AffiliateWithdrawal.query
        .filter(
            AffiliateWithdrawal.b2c_status == "sent",
            AffiliateWithdrawal.updated_at <= cutoff,
        )
        .all()
    )
    if not stuck:
        return

    admin_user_ids = [
        uid for (uid,) in db.session.query(User.id).filter(User.role == UserRole.system_admin.value).all()
    ]
    for withdrawal in stuck:
        # b2c_status='flagged' so this withdrawal doesn't re-notify every run.
        withdrawal.b2c_status = "flagged"
        if admin_user_ids:
            notify_many(
                admin_user_ids,
                category="affiliate_payout_failed",
                title="B2C payout stuck",
                body=(
                    f"Withdrawal #{withdrawal.id} was sent via B2C over 30 minutes ago with no result "
                    f"callback. Check the M-Pesa Organization portal statement or pay manually."
                ),
                entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
            )
    db.session.commit()
    logger.warning("reconcile_pending_mpesa: flagged %d stuck B2C payout(s).", len(stuck))
