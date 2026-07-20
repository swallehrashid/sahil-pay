"""
SahilPay — services/affiliate_service.py
==========================================
Affiliate program business logic (AFFILIATE_PROGRAM_SPEC.md).

The commission-accrual algorithm here was backtested standalone (17
scenarios, see the spec's §12.1 fixture table) before this module was
written; the exact figures in those fixtures are reproduced by this
implementation and are enforced by server/tests/test_affiliate_service.py.

Contract shared with services/audit_service.py and services/notification_service.py:
every function here FLUSHES but never COMMITS — the caller (a route handler)
commits once, so the mutation and its audit/notification rows succeed or
roll back together.

Balance is NEVER stored — always derived (get_balance) from confirmed
commissions minus non-rejected withdrawals. See spec §5.
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

Q = Decimal("0.01")

# Referral-code alphabet: no 0/O/1/I/L — avoids transcription errors when an
# affiliate reads their code aloud or a landlord retypes it (spec D4).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _quantize(value) -> Decimal:
    return Decimal(str(value)).quantize(Q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Program config
# ---------------------------------------------------------------------------

def get_program_config():
    """The single global settings row. Created by the migration seed; this is
    a defensive fallback only (e.g. a fresh test DB that skipped the seed)."""
    from extensions import db
    from models import AffiliateProgramConfig

    cfg = AffiliateProgramConfig.query.first()
    if cfg is None:
        cfg = AffiliateProgramConfig()
        db.session.add(cfg)
        db.session.flush()
    return cfg


# ---------------------------------------------------------------------------
# Affiliate lifecycle
# ---------------------------------------------------------------------------

def generate_referral_code() -> str:
    from models import Affiliate

    for _ in range(50):
        code = "SAH-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        if not Affiliate.query.filter_by(referral_code=code).first():
            return code
    raise RuntimeError("Could not generate a unique referral code after 50 attempts.")


def create_affiliate(user, full_name: str, phone: str) -> "Affiliate":
    from extensions import db
    from models import Affiliate, AffiliateStatus

    affiliate = Affiliate(
        user_id=user.id,
        full_name=full_name,
        phone=phone,
        referral_code=generate_referral_code(),
        status=AffiliateStatus.pending.value,
    )
    db.session.add(affiliate)
    db.session.flush()
    return affiliate


def approve_affiliate(affiliate, admin_id: int, mpesa_number: str | None = None,
                       national_id: str | None = None) -> None:
    from models import AffiliateStatus
    from services.notification_service import notify

    if mpesa_number:
        affiliate.mpesa_number = mpesa_number
    if national_id:
        affiliate.national_id = national_id
    affiliate.status = AffiliateStatus.active.value
    affiliate.approved_by_admin_id = admin_id
    affiliate.approved_at = datetime.utcnow()

    notify(
        recipient_user_id=affiliate.user_id,
        category="affiliate_approved",
        title="You're approved!",
        body=f"Your affiliate account is active. Your referral code is {affiliate.referral_code}.",
        entity_type="affiliate",
        entity_id=affiliate.id,
    )


def reject_affiliate(affiliate, admin_id: int, reason: str | None = None) -> None:
    from models import AffiliateStatus
    affiliate.status = AffiliateStatus.rejected.value
    affiliate.approved_by_admin_id = admin_id
    if reason:
        affiliate.notes = reason


def suspend_affiliate(affiliate, admin_id: int) -> None:
    """Code stops attributing new landlords; existing referrals KEEP accruing
    and withdrawals are blocked (D15) — money already earned isn't seized."""
    from models import AffiliateStatus
    affiliate.status = AffiliateStatus.suspended.value


def reactivate_affiliate(affiliate) -> None:
    from models import AffiliateStatus
    affiliate.status = AffiliateStatus.active.value


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

class AttributionError(ValueError):
    pass


def _is_self_referral(landlord, affiliate) -> bool:
    landlord_user = landlord.user
    affiliate_user = affiliate.user
    if landlord_user is None or affiliate_user is None:
        return False
    if landlord_user.email and affiliate_user.email and landlord_user.email == affiliate_user.email:
        return True
    if landlord_user.phone and affiliate_user.phone and landlord_user.phone == affiliate_user.phone:
        return True
    return False


def attribute_referral(landlord, affiliate, attributed_by: str = "registration"):
    """
    Create the AffiliateReferral row, snapshotting the affiliate's current
    rate/months (D5). Raises AttributionError on:
      - program kill switch off (D14)
      - affiliate not active (D15/D9)
      - self-referral (D9)
      - landlord already has a referral (unique landlord_id / E23)

    Callers at registration should catch AttributionError and skip silently
    (E3 — an invalid code must never block registration itself); the admin
    grace-tool route should surface it as a 400/409.
    """
    from extensions import db
    from models import AffiliateReferral, AffiliateStatus, ReferralStatus

    cfg = get_program_config()
    if not cfg.is_program_active:
        raise AttributionError("The affiliate program is not currently active.")
    if affiliate.status != AffiliateStatus.active.value:
        raise AttributionError("This affiliate account is not active.")
    if _is_self_referral(landlord, affiliate):
        raise AttributionError("An affiliate cannot refer their own account.")

    existing = AffiliateReferral.query.filter_by(landlord_id=landlord.id).first()
    if existing is not None:
        raise AttributionError("This landlord already has a referring affiliate.")

    rate   = affiliate.commission_rate_override if affiliate.commission_rate_override is not None \
        else cfg.default_commission_rate
    months = affiliate.commission_months_override if affiliate.commission_months_override is not None \
        else cfg.default_commission_months

    referral = AffiliateReferral(
        affiliate_id=affiliate.id,
        landlord_id=landlord.id,
        rate=rate,
        months_total=months,
        months_used=0,
        status=ReferralStatus.active.value,
        attributed_by=attributed_by,
    )
    db.session.add(referral)
    db.session.flush()

    from services.notification_service import notify
    notify(
        recipient_user_id=affiliate.user_id,
        category="affiliate_new_referral",
        title="New referral",
        body=f"{landlord.company_name} registered using your referral code.",
        entity_type="affiliate_referral",
        entity_id=referral.id,
    )
    return referral


def attribute_from_code(landlord, raw_code: str | None, attributed_by: str = "registration"):
    """
    Best-effort attribution from a raw code string. NEVER raises — an
    invalid/expired/unknown code must not block landlord registration (E3).
    Returns the AffiliateReferral, or None if nothing was attributed.
    """
    from models import Affiliate, AffiliateStatus

    if not raw_code:
        return None
    code = raw_code.strip().upper()
    landlord.referral_code_entered = code

    affiliate = Affiliate.query.filter_by(referral_code=code, status=AffiliateStatus.active.value).first()
    if affiliate is None:
        return None

    try:
        return attribute_referral(landlord, affiliate, attributed_by=attributed_by)
    except AttributionError:
        return None


def void_referral(referral) -> None:
    from models import ReferralStatus
    referral.status = ReferralStatus.void.value


# ---------------------------------------------------------------------------
# Commission accrual  (the backtested algorithm — see spec §12.1)
# ---------------------------------------------------------------------------

def accrue_for_transaction(txn):
    """
    Idempotent. Call ONLY with a verified subscription BillingTransaction —
    services/billing_service.py::finalize_subscription_payment is the sole
    caller. Returns the created AffiliateCommission, or None when nothing
    should accrue (no referral, SMS transaction, unverified, window
    exhausted, or already accrued for this txn).
    """
    from extensions import db
    from sqlalchemy.exc import IntegrityError
    from models import (
        AffiliateReferral, AffiliateCommission, BillingTransactionType,
        CommissionStatus, ReferralStatus,
    )

    if txn.type != BillingTransactionType.subscription.value:
        return None
    if not txn.is_verified:
        return None

    referral = (
        AffiliateReferral.query
        .filter_by(landlord_id=txn.landlord_id, status=ReferralStatus.active.value)
        .with_for_update()
        .first()
    )
    if referral is None:
        return None

    # Idempotency guard (app-level; the partial unique index is the DB-level backstop).
    already = AffiliateCommission.query.filter(
        AffiliateCommission.billing_transaction_id == txn.id,
        AffiliateCommission.status != CommissionStatus.reversed.value,
    ).first()
    if already is not None:
        return None

    ctx = txn.context_json or {}
    months_covered = ctx.get("months")
    if not months_covered:
        # Defensive fallback (E25) — should not happen for any txn created via
        # billing_service, which always stamps context_json["months"].
        return None

    remaining = referral.months_total - referral.months_used
    commissionable = min(months_covered, remaining)
    if commissionable <= 0:
        return None

    amount = Decimal(str(txn.amount))
    monthly_equivalent = amount / months_covered
    commission_amount = _quantize(referral.rate / 100 * monthly_equivalent * commissionable)

    if referral.window_started_at is None:
        referral.window_started_at = datetime.utcnow()

    referral.months_used += commissionable
    if referral.months_used >= referral.months_total:
        referral.status = ReferralStatus.completed.value

    commission = AffiliateCommission(
        referral_id=referral.id,
        affiliate_id=referral.affiliate_id,
        billing_transaction_id=txn.id,
        amount=commission_amount,
        rate_applied=referral.rate,
        monthly_equivalent=_quantize(monthly_equivalent),
        months_commissioned=commissionable,
        status=CommissionStatus.confirmed.value,
    )
    db.session.add(commission)
    try:
        db.session.flush()
    except IntegrityError:
        # Lost a race with a concurrent accrual attempt on the same txn (E16) —
        # the partial unique index caught it; treat as the idempotent no-op it is.
        db.session.rollback()
        return None

    from services.notification_service import notify
    notify(
        recipient_user_id=referral.affiliate.user_id,
        category="affiliate_commission_earned",
        title="Commission earned",
        body=f"You earned KES {commission_amount} from {referral.landlord.company_name}'s subscription payment.",
        entity_type="affiliate_commission",
        entity_id=commission.id,
    )

    return commission


def reverse_for_transaction(txn):
    """
    Claw back the commission tied to a reversed BillingTransaction (D10).
    Flips the commission's status in place (does not insert a negative row),
    restores the referral's consumed months, and reopens a completed referral
    if this reversal drops it below its month cap. Idempotent.
    """
    from extensions import db
    from models import AffiliateCommission, CommissionStatus, ReferralStatus

    commission = AffiliateCommission.query.filter_by(
        billing_transaction_id=txn.id, status=CommissionStatus.confirmed.value
    ).first()
    if commission is None:
        return None

    referral = commission.referral
    referral.months_used -= commission.months_commissioned
    if referral.status == ReferralStatus.completed.value:
        referral.status = ReferralStatus.active.value

    commission.status = CommissionStatus.reversed.value
    commission.reversed_at = datetime.utcnow()
    db.session.flush()
    return commission


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------

def get_balance(affiliate_id: int) -> Decimal:
    """confirmed commissions − (requested + processing + paid) withdrawals.
    A rejected withdrawal drops out of the sum entirely — it releases the
    funds it had provisionally held (spec §5 / backtest S8-S10)."""
    from extensions import db
    from models import AffiliateCommission, AffiliateWithdrawal, CommissionStatus, WithdrawalStatus

    confirmed = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
        AffiliateCommission.affiliate_id == affiliate_id,
        AffiliateCommission.status == CommissionStatus.confirmed.value,
    ).scalar()

    held = db.session.query(db.func.coalesce(db.func.sum(AffiliateWithdrawal.gross_amount), 0)).filter(
        AffiliateWithdrawal.affiliate_id == affiliate_id,
        AffiliateWithdrawal.status.in_([
            WithdrawalStatus.requested.value,
            WithdrawalStatus.processing.value,
            WithdrawalStatus.paid.value,
        ]),
    ).scalar()

    return _quantize(Decimal(str(confirmed)) - Decimal(str(held)))


def get_affiliate_summary(affiliate) -> dict:
    """Dashboard aggregates for both the affiliate portal and the admin drill-down."""
    from extensions import db
    from models import (
        AffiliateReferral, AffiliateCommission, AffiliateWithdrawal,
        CommissionStatus, ReferralStatus, WithdrawalStatus, SubscriptionStatus,
    )

    referrals = AffiliateReferral.query.filter_by(affiliate_id=affiliate.id).all()

    total_referrals     = len(referrals)
    completed_referrals = sum(1 for r in referrals if r.status == ReferralStatus.completed.value)
    active_paying       = sum(1 for r in referrals if r.status == ReferralStatus.active.value and r.window_started_at)
    not_yet_paying      = sum(1 for r in referrals if r.window_started_at is None and r.status != ReferralStatus.void.value)

    lifetime_earned = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
        AffiliateCommission.affiliate_id == affiliate.id,
        AffiliateCommission.status == CommissionStatus.confirmed.value,
    ).scalar()

    total_withdrawn = db.session.query(db.func.coalesce(db.func.sum(AffiliateWithdrawal.net_amount), 0)).filter(
        AffiliateWithdrawal.affiliate_id == affiliate.id,
        AffiliateWithdrawal.status == WithdrawalStatus.paid.value,
    ).scalar()

    pending_withdrawal = AffiliateWithdrawal.query.filter(
        AffiliateWithdrawal.affiliate_id == affiliate.id,
        AffiliateWithdrawal.status.in_([WithdrawalStatus.requested.value, WithdrawalStatus.processing.value]),
    ).first()

    # Projected monthly earnings: rate% of current subscription cost, for every
    # referral still inside its commission window AND whose landlord is actively
    # paying (not on trial) this month — a trial landlord isn't expected to pay
    # yet, so it shouldn't inflate what the affiliate expects to receive.
    projected_monthly = Decimal("0.00")
    for r in referrals:
        if r.status != ReferralStatus.active.value:
            continue
        sub = r.landlord.subscription if r.landlord else None
        if sub and sub.subscription_cost and sub.status == SubscriptionStatus.active.value:
            projected_monthly += (r.rate / 100 * Decimal(str(sub.subscription_cost)))

    return {
        "balance":              str(get_balance(affiliate.id)),
        "lifetime_earned":      str(_quantize(lifetime_earned)),
        "total_withdrawn":      str(_quantize(total_withdrawn)),
        "has_pending_withdrawal": pending_withdrawal is not None,
        "projected_monthly":    str(_quantize(projected_monthly)),
        "referral_counts": {
            "total":         total_referrals,
            "active_paying": active_paying,
            "completed":     completed_referrals,
            "not_yet_paying": not_yet_paying,
        },
        "referral_code": affiliate.referral_code,
    }


# ---------------------------------------------------------------------------
# Withdrawals
# ---------------------------------------------------------------------------

class WithdrawalError(ValueError):
    pass


def request_withdrawal(affiliate, gross_amount) -> "AffiliateWithdrawal":
    """
    Guards checked in THIS order (D13 — the backtest caught a bug when they
    weren't): (1) another withdrawal already open, (2) below minimum,
    (3) exceeds available balance.
    """
    from extensions import db
    from models import AffiliateWithdrawal, WithdrawalStatus, AffiliateStatus

    if affiliate.status == AffiliateStatus.suspended.value:
        raise WithdrawalError("Withdrawals are blocked while your account is suspended.")
    if not affiliate.mpesa_number or not affiliate.national_id:
        raise WithdrawalError("Complete your payout profile (M-Pesa number and national ID) before withdrawing.")

    open_withdrawal = AffiliateWithdrawal.query.filter(
        AffiliateWithdrawal.affiliate_id == affiliate.id,
        AffiliateWithdrawal.status.in_([WithdrawalStatus.requested.value, WithdrawalStatus.processing.value]),
    ).first()
    if open_withdrawal is not None:
        raise WithdrawalError("You already have a withdrawal in progress.")

    cfg = get_program_config()
    gross = _quantize(gross_amount)

    if gross < cfg.min_withdrawal:
        raise WithdrawalError(f"Minimum withdrawal is KES {cfg.min_withdrawal}.")

    balance = get_balance(affiliate.id)
    if gross > balance:
        raise WithdrawalError(f"Withdrawal exceeds your available balance of KES {balance}.")

    wht_amount = _quantize(gross * cfg.wht_rate / 100)
    if cfg.fee_type == "flat":
        fee_amount = _quantize(cfg.fee_value)
    else:
        fee_amount = _quantize(gross * cfg.fee_value / 100)
    net_amount = gross - wht_amount - fee_amount

    withdrawal = AffiliateWithdrawal(
        affiliate_id=affiliate.id,
        gross_amount=gross,
        wht_rate=cfg.wht_rate,
        wht_amount=wht_amount,
        fee_type=cfg.fee_type,
        fee_value=cfg.fee_value,
        fee_amount=fee_amount,
        net_amount=net_amount,
        status=WithdrawalStatus.requested.value,
    )
    db.session.add(withdrawal)
    db.session.flush()
    return withdrawal


def _next_receipt_number() -> str:
    from extensions import db
    from models import AffiliateWithdrawal

    year = datetime.utcnow().year
    prefix = f"AFR-{year}-"
    count = AffiliateWithdrawal.query.filter(
        AffiliateWithdrawal.receipt_number.like(f"{prefix}%")
    ).count()
    return f"{prefix}{count + 1:06d}"


def process_withdrawal(withdrawal, admin_id: int) -> None:
    from models import WithdrawalStatus
    withdrawal.status = WithdrawalStatus.processing.value
    withdrawal.processed_by_admin_id = admin_id


def pay_withdrawal(withdrawal, admin_id: int, mpesa_reference: str) -> None:
    from models import WithdrawalStatus
    withdrawal.status = WithdrawalStatus.paid.value
    withdrawal.mpesa_reference = mpesa_reference
    withdrawal.processed_by_admin_id = admin_id
    withdrawal.processed_at = datetime.utcnow()
    withdrawal.receipt_number = _next_receipt_number()

    from services.notification_service import notify
    notify(
        recipient_user_id=withdrawal.affiliate.user_id,
        category="affiliate_withdrawal_processed",
        title="Withdrawal paid",
        body=f"KES {withdrawal.net_amount} has been sent to your M-Pesa number. Receipt {withdrawal.receipt_number}.",
        entity_type="affiliate_withdrawal",
        entity_id=withdrawal.id,
    )


def reject_withdrawal(withdrawal, admin_id: int, reason: str) -> None:
    from models import WithdrawalStatus
    withdrawal.status = WithdrawalStatus.rejected.value
    withdrawal.processed_by_admin_id = admin_id
    withdrawal.processed_at = datetime.utcnow()
    withdrawal.rejection_reason = reason
