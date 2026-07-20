"""
Regression suite for the affiliate commission ledger — a direct port of the
17-scenario standalone backtest (see AFFILIATE_PROGRAM_SPEC.md §12.1) onto
the REAL services/affiliate_service.py + real Postgres constraints. Every
expected figure here is an acceptance criterion from the spec, not a
convenience number — do not "fix" a failing assertion by changing the
expected value without re-reading the spec section it cites.
"""

import itertools
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from models import (
    User, Landlord, Subscription, SubscriptionStatus,
    AffiliateStatus, ReferralStatus, CommissionStatus,
    BillingTransaction, BillingTransactionType, BillingTransactionStatus,
    AffiliateCommission, AffiliateWithdrawal,
)
from services import affiliate_service as svc

Q = Decimal("0.01")
_counter = itertools.count()


def q(x):
    from decimal import ROUND_HALF_UP
    return Decimal(str(x)).quantize(Q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_landlord(session, monthly_cost="1000", email=None, phone=None):
    n = next(_counter)
    landlord_user = User(
        email=email or f"landlord{n}@test.sahilpay",
        phone=phone or f"254700{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord",
        is_verified=True,
    )
    session.add(landlord_user)
    session.flush()

    landlord = Landlord(user_id=landlord_user.id, company_name=f"Test Landlord {n}", currency="KES")
    session.add(landlord)
    session.flush()

    sub = Subscription(
        landlord_id=landlord.id, unit_count=5, subscription_cost=Decimal(monthly_cost),
        status=SubscriptionStatus.active.value, billing_cycle="monthly", amount_due=Decimal("0"),
    )
    session.add(sub)
    session.flush()
    return landlord


def make_affiliate(session, rate=None, months=None):
    n = next(_counter)
    user = User(
        email=f"affiliate{n}@test.sahilpay",
        phone=f"254711{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="affiliate",
        is_verified=True,
    )
    session.add(user)
    session.flush()

    affiliate = svc.create_affiliate(user, f"Test Affiliate {n}", user.phone)
    affiliate.status = AffiliateStatus.active.value
    if rate is not None:
        affiliate.commission_rate_override = Decimal(str(rate))
    if months is not None:
        affiliate.commission_months_override = months
    session.flush()
    return affiliate


def make_txn(session, landlord, amount, months_covered, billing_cycle="monthly"):
    txn = BillingTransaction(
        landlord_id=landlord.id,
        type=BillingTransactionType.subscription.value,
        amount=Decimal(str(amount)),
        status=BillingTransactionStatus.paid.value,
        is_verified=True,
        context_json={
            "billing_cycle": billing_cycle, "months": months_covered,
            "discount": "0", "package_id": None, "applied": True,
        },
    )
    session.add(txn)
    session.flush()
    return txn


def payout_profile(affiliate):
    affiliate.mpesa_number = "254700123456"
    affiliate.national_id = "12345678"


def make_admin_id(session):
    """processed_by_admin_id / verified_by_admin_id FK to users.id — needs a real row."""
    n = next(_counter)
    user = User(
        email=f"admin{n}@test.sahilpay", phone=f"254722{n:06d}",
        password_hash=generate_password_hash("Testpass1"), role="system_admin", is_verified=True,
    )
    session.add(user)
    session.flush()
    return user.id


# ---------------------------------------------------------------------------
# S1 — monthly landlord, KES 1000/mo, 6 payments -> exactly 4 commissioned
# ---------------------------------------------------------------------------

def test_s1_monthly_six_payments_caps_at_four(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)

    amounts = []
    for _ in range(6):
        txn = make_txn(db_session, landlord, 1000, 1)
        c = svc.accrue_for_transaction(txn)
        amounts.append(c.amount if c else None)

    assert amounts == [q(400)] * 4 + [None, None]
    assert referral.status == ReferralStatus.completed.value
    assert svc.get_balance(affiliate.id) == q(1600)


# ---------------------------------------------------------------------------
# S2 — annual prepay (10200 covers 12 months) capped to 4 -> ONE commission of 1360.00
# ---------------------------------------------------------------------------

def test_s2_annual_prepay_caps_to_four_months(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)

    txn = make_txn(db_session, landlord, "10200", 12, billing_cycle="annual")
    c = svc.accrue_for_transaction(txn)

    assert c.amount == q(1360)
    assert referral.status == ReferralStatus.completed.value

    txn2 = make_txn(db_session, landlord, "10200", 12, billing_cycle="annual")
    c2 = svc.accrue_for_transaction(txn2)
    assert c2 is None


# ---------------------------------------------------------------------------
# S3 — quarterly 2700 x2 -> 1080.00 then 360.00 (capped to 1 remaining month)
# ---------------------------------------------------------------------------

def test_s3_quarterly_caps_on_second_payment(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    svc.attribute_referral(landlord, affiliate)

    txn1 = make_txn(db_session, landlord, "2700", 3, billing_cycle="quarterly")
    c1 = svc.accrue_for_transaction(txn1)
    txn2 = make_txn(db_session, landlord, "2700", 3, billing_cycle="quarterly")
    c2 = svc.accrue_for_transaction(txn2)

    assert c1.amount == q(1080) and c1.months_commissioned == 3
    assert c2.amount == q(360) and c2.months_commissioned == 1
    assert svc.get_balance(affiliate.id) == q(1440)


# ---------------------------------------------------------------------------
# S4 — reversal restores months; a fresh payment accrues again
# ---------------------------------------------------------------------------

def test_s4_reversal_restores_months_and_rebills(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)

    txn = make_txn(db_session, landlord, 1000, 1)
    svc.accrue_for_transaction(txn)
    assert svc.get_balance(affiliate.id) == q(400)
    assert referral.months_used == 1

    svc.reverse_for_transaction(txn)
    assert svc.get_balance(affiliate.id) == q(0)
    assert referral.months_used == 0

    txn2 = make_txn(db_session, landlord, 1000, 1)
    c2 = svc.accrue_for_transaction(txn2)
    assert c2.amount == q(400)
    assert svc.get_balance(affiliate.id) == q(400)


# ---------------------------------------------------------------------------
# S5 — clawback AFTER payout: balance goes negative, nets back on repay
# ---------------------------------------------------------------------------

def test_s5_clawback_after_payout_goes_negative_then_nets(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    payout_profile(affiliate)
    referral = svc.attribute_referral(landlord, affiliate)

    txns = [make_txn(db_session, landlord, 1000, 1) for _ in range(4)]
    for t in txns:
        svc.accrue_for_transaction(t)
    assert svc.get_balance(affiliate.id) == q(1600)

    withdrawal = svc.request_withdrawal(affiliate, "1600")
    assert withdrawal.wht_amount == q(80)
    assert withdrawal.fee_amount == q(48)
    assert withdrawal.net_amount == q(1472)
    assert withdrawal.wht_amount + withdrawal.fee_amount + withdrawal.net_amount == withdrawal.gross_amount

    admin_id = make_admin_id(db_session)
    svc.pay_withdrawal(withdrawal, admin_id=admin_id, mpesa_reference="TEST-REF-1")
    assert svc.get_balance(affiliate.id) == q(0)
    assert withdrawal.receipt_number is not None

    svc.reverse_for_transaction(txns[3])  # 4th month's payment bounced
    assert svc.get_balance(affiliate.id) == q(-400)
    assert referral.status == ReferralStatus.active.value
    assert referral.months_used == 3

    retry = make_txn(db_session, landlord, 1000, 1)
    c = svc.accrue_for_transaction(retry)
    assert c.amount == q(400)
    assert svc.get_balance(affiliate.id) == q(0)


# ---------------------------------------------------------------------------
# S6 — changing the global default rate never touches an existing referral
# ---------------------------------------------------------------------------

def test_s6_global_default_change_does_not_touch_existing_referral(db_session):
    landlord1 = make_landlord(db_session)
    affiliate = make_affiliate(db_session)  # no override -> uses global default (40)
    svc.attribute_referral(landlord1, affiliate)

    txn1 = make_txn(db_session, landlord1, 1000, 1)
    c1 = svc.accrue_for_transaction(txn1)
    assert c1.amount == q(400)

    cfg = svc.get_program_config()
    cfg.default_commission_rate = Decimal("50")
    db_session.flush()

    txn2 = make_txn(db_session, landlord1, 1000, 1)
    c2 = svc.accrue_for_transaction(txn2)
    assert c2.amount == q(400)   # unchanged — referral.rate was snapshotted at 40

    landlord2 = make_landlord(db_session)
    svc.attribute_referral(landlord2, affiliate)   # new referral snapshots the NEW default
    txn3 = make_txn(db_session, landlord2, 1000, 1)
    c3 = svc.accrue_for_transaction(txn3)
    assert c3.amount == q(500)


# ---------------------------------------------------------------------------
# S7 — admin edits ONE referral's rate mid-window -> future accruals only
# ---------------------------------------------------------------------------

def test_s7_per_referral_rate_edit_applies_to_future_only(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)

    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))
    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))

    referral.rate = Decimal("50")
    db_session.flush()

    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))
    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))

    assert svc.get_balance(affiliate.id) == q(400 + 400 + 500 + 500)


# ---------------------------------------------------------------------------
# S8-S10 — withdrawal guards fire in D13 order; a rejected withdrawal
# releases the funds it had held
# ---------------------------------------------------------------------------

def test_s8_s9_s10_withdrawal_guard_order_and_rejection_releases_funds(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    payout_profile(affiliate)
    svc.attribute_referral(landlord, affiliate)

    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))  # balance 400
    assert svc.get_balance(affiliate.id) == q(400)

    with pytest.raises(svc.WithdrawalError, match="Minimum withdrawal"):
        svc.request_withdrawal(affiliate, "100")

    with pytest.raises(svc.WithdrawalError, match="exceeds your available balance"):
        svc.request_withdrawal(affiliate, "9999")

    svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))  # balance 800
    assert svc.get_balance(affiliate.id) == q(800)

    w = svc.request_withdrawal(affiliate, "500")
    with pytest.raises(svc.WithdrawalError, match="already have a withdrawal in progress"):
        svc.request_withdrawal(affiliate, "500")

    admin_id = make_admin_id(db_session)
    svc.reject_withdrawal(w, admin_id=admin_id, reason="test rejection")
    assert svc.get_balance(affiliate.id) == q(800)


# ---------------------------------------------------------------------------
# S11 — a duplicate accrual attempt on the same transaction is a no-op
# ---------------------------------------------------------------------------

def test_s11_duplicate_accrual_is_idempotent(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    svc.attribute_referral(landlord, affiliate)

    txn = make_txn(db_session, landlord, 1000, 1)
    c1 = svc.accrue_for_transaction(txn)
    c2 = svc.accrue_for_transaction(txn)

    assert c1 is not None and c2 is None
    assert svc.get_balance(affiliate.id) == q(400)


# ---------------------------------------------------------------------------
# S12 — self-referral is rejected by email match AND by phone match
# ---------------------------------------------------------------------------

def test_s12_self_referral_blocked_by_email_and_phone(db_session):
    # users.email is globally unique, so two persisted User rows can never
    # actually share an email (the registration endpoint's own duplicate-email
    # check refuses it first) — the realistic vector for one person holding
    # both a landlord and an affiliate account is a shared PHONE number under
    # two different emails, exercised end-to-end below via attribute_referral.
    # The email branch of _is_self_referral() is still real defensive code
    # (schemas change), so it's unit-tested directly against plain objects
    # rather than forcing a DB-illegal duplicate-email row.
    class _FakeUser:
        def __init__(self, email=None, phone=None):
            self.email, self.phone = email, phone

    class _FakeOwner:
        def __init__(self, user):
            self.user = user

    same_email = svc._is_self_referral(
        _FakeOwner(_FakeUser(email="shared@test.sahilpay", phone="254700000111")),
        _FakeOwner(_FakeUser(email="shared@test.sahilpay", phone="254700000222")),
    )
    assert same_email is True

    affiliate = make_affiliate(db_session)
    same_phone_landlord = make_landlord(db_session, phone=affiliate.user.phone)
    with pytest.raises(svc.AttributionError, match="cannot refer their own account"):
        svc.attribute_referral(same_phone_landlord, affiliate)


# ---------------------------------------------------------------------------
# S13 — custom-package landlord (negotiated 750/mo) -> 300/mo, 1200 over 4mo
# ---------------------------------------------------------------------------

def test_s13_custom_package_rate_follows_actual_amount_paid(db_session):
    landlord = make_landlord(db_session, monthly_cost="750")
    affiliate = make_affiliate(db_session)
    svc.attribute_referral(landlord, affiliate)

    for _ in range(4):
        svc.accrue_for_transaction(make_txn(db_session, landlord, 750, 1))

    assert svc.get_balance(affiliate.id) == q(1200)


# ---------------------------------------------------------------------------
# S14 — package upgrade mid-window: commission follows the amount actually paid
# ---------------------------------------------------------------------------

def test_s14_package_upgrade_mid_window(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    svc.attribute_referral(landlord, affiliate)

    for amt in (1000, 1000, 2000, 2000):
        svc.accrue_for_transaction(make_txn(db_session, landlord, amt, 1))

    assert svc.get_balance(affiliate.id) == q(2400)


# ---------------------------------------------------------------------------
# S15 — rounding: odd amounts + a withdrawal receipt that sums exactly
# ---------------------------------------------------------------------------

def test_s15_rounding_and_receipt_identity(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    payout_profile(affiliate)
    svc.attribute_referral(landlord, affiliate)

    c1 = svc.accrue_for_transaction(make_txn(db_session, landlord, "999.99", 1))
    assert c1.amount == q("400.00")

    c2 = svc.accrue_for_transaction(make_txn(db_session, landlord, "333.33", 1))
    assert c2.amount == q("133.33")

    # months_used is now 2 of 4 -> only 2 remain, quarterly txn covers 3 -> capped to 2
    c3 = svc.accrue_for_transaction(make_txn(db_session, landlord, "1000.01", 3, billing_cycle="quarterly"))
    assert c3.amount == q("266.67")

    assert svc.get_balance(affiliate.id) == q("800.00")

    w = svc.request_withdrawal(affiliate, "777.77")
    assert w.wht_amount == q("38.89")
    assert w.fee_amount == q("23.33")
    assert w.net_amount == q("715.55")
    assert w.wht_amount + w.fee_amount + w.net_amount == w.gross_amount


# ---------------------------------------------------------------------------
# S16 — admin extends months on a COMPLETED referral -> it reopens
# ---------------------------------------------------------------------------

def test_s16_extending_completed_referral_reopens_accrual(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session, months=6)
    referral = svc.attribute_referral(landlord, affiliate)
    assert referral.months_total == 6

    for _ in range(6):
        svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))
    assert referral.status == ReferralStatus.completed.value
    assert svc.get_balance(affiliate.id) == q(2400)

    referral.months_total = 8
    referral.status = ReferralStatus.active.value
    db_session.flush()

    for _ in range(2):
        svc.accrue_for_transaction(make_txn(db_session, landlord, 1000, 1))

    assert referral.status == ReferralStatus.completed.value
    assert svc.get_balance(affiliate.id) == q(3200)


# ---------------------------------------------------------------------------
# S17 — a referred landlord who never pays: zero accrual, window never starts
# ---------------------------------------------------------------------------

def test_s17_never_converts_stays_at_zero(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)

    assert referral.window_started_at is None
    assert referral.status == ReferralStatus.active.value
    assert svc.get_balance(affiliate.id) == q(0)


# ---------------------------------------------------------------------------
# DB-constraint backstops (E10/E16, D7/D11) — independent of application logic
# ---------------------------------------------------------------------------

def test_db_partial_unique_index_blocks_duplicate_live_commission(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    referral = svc.attribute_referral(landlord, affiliate)
    txn = make_txn(db_session, landlord, 1000, 1)

    row1 = AffiliateCommission(
        referral_id=referral.id, affiliate_id=affiliate.id, billing_transaction_id=txn.id,
        amount=Decimal("400"), rate_applied=Decimal("40"), monthly_equivalent=Decimal("1000"),
        months_commissioned=1, status=CommissionStatus.confirmed.value,
    )
    db_session.add(row1)
    db_session.flush()

    row2 = AffiliateCommission(
        referral_id=referral.id, affiliate_id=affiliate.id, billing_transaction_id=txn.id,
        amount=Decimal("400"), rate_applied=Decimal("40"), monthly_equivalent=Decimal("1000"),
        months_commissioned=1, status=CommissionStatus.confirmed.value,
    )
    db_session.add(row2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_db_check_constraint_rejects_bad_withdrawal_breakdown(db_session):
    landlord = make_landlord(db_session)
    affiliate = make_affiliate(db_session)
    svc.attribute_referral(landlord, affiliate)

    bad = AffiliateWithdrawal(
        affiliate_id=affiliate.id, gross_amount=Decimal("1000"),
        wht_rate=Decimal("5"), wht_amount=Decimal("50"),
        fee_type="percent", fee_value=Decimal("3"), fee_amount=Decimal("30"),
        net_amount=Decimal("999"),  # wrong — should be 920
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.flush()
