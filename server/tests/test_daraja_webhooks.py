"""
Regression suite for the M-Pesa production integration
(MPESA_INTEGRATION_SPEC.md §13.1) — real Flask routes against real Postgres.

Covers: STK billing callback (subscription + SMS, success/failure/duplicate/
amount-mismatch), C2B confirmation (matched/unmatched/duplicate/wrong-amount),
legacy self-reported endpoints no longer granting service, B2C payout
(simulation, double-pay lock), the rent-STK gate, and the end-to-end
affiliate commission chain through a simulated verified subscription payment.
"""

import itertools
import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from models import (
    User, Landlord, Subscription, SubscriptionStatus,
    BillingTransaction, BillingTransactionType, BillingTransactionStatus,
    PlatformC2BPayment, DarajaCallbackLog,
    Affiliate, AffiliateReferral, AffiliateCommission, AffiliateWithdrawal,
    AffiliateStatus, ReferralStatus, CommissionStatus, WithdrawalStatus,
)
from services import affiliate_service as svc

_counter = itertools.count()


def _uniq() -> str:
    """6-digit unique-enough suffix, unique per process AND across reruns
    (unlike a plain in-process counter, which collides with a previous run's
    leftover rows if an earlier test errored before its cleanup ran)."""
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_landlord(session, monthly_cost="1000"):
    n = _uniq()
    user = User(
        email=f"mpesa-landlord{n}@test.sahilpay",
        phone=f"2547{next(_counter):08d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord",
        is_verified=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(user_id=user.id, company_name=f"MPesa Test Landlord {n}", currency="KES")
    session.add(landlord)
    session.flush()

    sub = Subscription(
        landlord_id=landlord.id, unit_count=5, subscription_cost=Decimal(monthly_cost),
        status=SubscriptionStatus.active.value, billing_cycle="monthly", amount_due=Decimal("0"),
    )
    session.add(sub)
    session.flush()
    session.commit()
    return user, landlord


def make_admin(session):
    n = _uniq()
    user = User(
        email=f"mpesa-admin{n}@test.sahilpay",
        phone=f"2547{next(_counter):08d}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin",
        # Admin routes require an active second factor (spec 3.4).
        totp_enabled=True,
        is_verified=True,
    )
    session.add(user)
    session.commit()
    return user


def make_affiliate_with_referral(session, landlord, rate="40.00", months=4):
    n = _uniq()
    aff_user = User(
        email=f"mpesa-affiliate{n}@test.sahilpay",
        phone=f"2547{next(_counter):08d}",
        password_hash=generate_password_hash("Testpass1"),
        role="affiliate",
        is_verified=True,
    )
    session.add(aff_user)
    session.flush()

    affiliate = svc.create_affiliate(aff_user, f"MPesa Test Affiliate {n}", aff_user.phone)
    affiliate.status = AffiliateStatus.active.value
    affiliate.mpesa_number = f"2547{next(_counter):08d}"
    affiliate.national_id = f"3{next(_counter):08d}"
    affiliate.commission_rate_override = Decimal(rate)
    affiliate.commission_months_override = months
    session.flush()

    referral = svc.attribute_referral(landlord, affiliate, attributed_by="registration")
    session.commit()
    return affiliate, referral


def pending_txn(session, landlord, kind="subscription", amount="1000.00", checkout_id=None, sms_count=None):
    ctx = {"billing_cycle": "monthly", "months": 1, "discount": "0", "package_id": None, "applied": False} \
        if kind == "subscription" else {"sms_count": sms_count or 100, "unit_price": "1.00", "applied": False}
    txn = BillingTransaction(
        landlord_id=landlord.id,
        type=BillingTransactionType.subscription.value if kind == "subscription" else BillingTransactionType.sms_purchase.value,
        amount=Decimal(amount),
        sms_count=sms_count,
        payment_reference=checkout_id,
        status=BillingTransactionStatus.pending.value,
        context_json=ctx,
    )
    session.add(txn)
    session.commit()
    return txn


def _auth_header(user, role=None):
    claims = {"role": role or user.role}
    token = create_access_token(identity=str(user.id), additional_claims=claims)
    return {"Authorization": f"Bearer {token}"}


def _stk_callback_payload(checkout_id, amount, result_code=0, receipt="NLJ7RT61SV"):
    items = [
        {"Name": "Amount", "Value": amount},
        {"Name": "MpesaReceiptNumber", "Value": receipt},
        {"Name": "TransactionDate", "Value": 20260715120000},
        {"Name": "PhoneNumber", "Value": 254712345678},
    ]
    return {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "1",
                "CheckoutRequestID": checkout_id,
                "ResultCode": result_code,
                "ResultDesc": "The service request is processed successfully." if result_code == 0 else "Cancelled",
                **({"CallbackMetadata": {"Item": items}} if result_code == 0 else {}),
            }
        }
    }


def _cleanup(session, *rows_by_table):
    """rows_by_table: list of (table_name, id) tuples, deleted in order given
    (children before parents). Routes under test write audit_logs and
    notifications rows the fixtures don't track directly — purge those for
    any landlord/user id being deleted so the FK doesn't block cleanup."""
    session.rollback()
    for table, row_id in rows_by_table:
        if row_id is None:
            continue
        if table == "landlords":
            session.execute(text("DELETE FROM audit_logs WHERE landlord_id = :id"), {"id": row_id})
            session.execute(text("DELETE FROM subscriptions WHERE landlord_id = :id"), {"id": row_id})
        if table == "users":
            session.execute(text("DELETE FROM notifications WHERE recipient_user_id = :id OR sender_user_id = :id"), {"id": row_id})
            session.execute(text("DELETE FROM audit_logs WHERE actor_user_id = :id"), {"id": row_id})
        session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
    session.commit()


# ---------------------------------------------------------------------------
# STK billing callback
# ---------------------------------------------------------------------------

class TestStkBillingCallback:
    def test_subscription_success_verifies_and_activates(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id)

        try:
            resp = client.post("/api/webhooks/daraja/billing-callback",
                                json=_stk_callback_payload(checkout_id, 1000))
            assert resp.status_code == 200
            assert resp.json["ResultCode"] == 0

            db_session.refresh(txn)
            assert txn.is_verified is True
            assert txn.status == BillingTransactionStatus.paid.value
            assert txn.payment_reference == "NLJ7RT61SV"
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_sms_purchase_success_credits_balance(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        starting_balance = landlord.sms_balance
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "sms_purchase", "100.00", checkout_id, sms_count=100)

        try:
            resp = client.post("/api/webhooks/daraja/billing-callback",
                                json=_stk_callback_payload(checkout_id, 100))
            assert resp.status_code == 200

            db_session.refresh(txn)
            db_session.refresh(landlord)
            assert txn.is_verified is True
            assert landlord.sms_balance == starting_balance + 100
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_failure_result_code_marks_failed_not_verified(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id)

        try:
            resp = client.post("/api/webhooks/daraja/billing-callback",
                                json=_stk_callback_payload(checkout_id, 1000, result_code=1032))
            assert resp.status_code == 200

            db_session.refresh(txn)
            assert txn.is_verified is False
            assert txn.status == BillingTransactionStatus.failed.value
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_duplicate_callback_is_idempotent_noop(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id)

        try:
            payload = _stk_callback_payload(checkout_id, 1000)
            r1 = client.post("/api/webhooks/daraja/billing-callback", json=payload)
            r2 = client.post("/api/webhooks/daraja/billing-callback", json=payload)
            assert r1.status_code == 200
            assert r2.status_code == 200  # still Daraja-happy, no crash on re-processing an already-verified txn
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_amount_mismatch_does_not_finalize(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id)

        try:
            resp = client.post("/api/webhooks/daraja/billing-callback",
                                json=_stk_callback_payload(checkout_id, 1))  # tenant sent KES 1 instead of 1000
            assert resp.status_code == 200

            db_session.refresh(txn)
            assert txn.is_verified is False
            assert txn.status == BillingTransactionStatus.pending.value
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_unknown_checkout_request_id_is_safe_noop(self, app, client, db_session):
        resp = client.post("/api/webhooks/daraja/billing-callback",
                            json=_stk_callback_payload("ws_CO_doesnotexist", 1000))
        assert resp.status_code == 200
        assert resp.json["ResultCode"] == 0

    def test_legacy_mpesa_path_still_mounted(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id)

        try:
            resp = client.post("/api/webhooks/mpesa/billing-callback",
                                json=_stk_callback_payload(checkout_id, 1000))
            assert resp.status_code == 200
            db_session.refresh(txn)
            assert txn.is_verified is True
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_log_entry_written_for_every_callback(self, app, client, db_session):
        before_count = db_session.query(DarajaCallbackLog).count()
        client.post("/api/webhooks/daraja/billing-callback",
                    json=_stk_callback_payload("ws_CO_logtest", 1000))
        after_count = db_session.query(DarajaCallbackLog).count()
        assert after_count == before_count + 1


# ---------------------------------------------------------------------------
# C2B confirmation
# ---------------------------------------------------------------------------

class TestC2bConfirmation:
    def _payload(self, trans_id, amount, bill_ref):
        return {
            "TransID": trans_id, "TransAmount": amount, "BillRefNumber": bill_ref,
            "MSISDN": "254712345678", "FirstName": "Test", "LastName": "Payer",
            "TransTime": "20260715120000",
        }

    def test_matched_subscription_ref_verifies(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        txn = pending_txn(db_session, landlord, "subscription", "1000.00")
        trans_id = f"NLJ{uuid.uuid4().hex[:8].upper()}"

        try:
            resp = client.post("/api/webhooks/daraja/c2b/confirmation",
                                json=self._payload(trans_id, 1000, f"SUB-{landlord.id}"))
            assert resp.status_code == 200

            db_session.refresh(txn)
            assert txn.is_verified is True

            c2b = PlatformC2BPayment.query.filter_by(trans_id=trans_id).first()
            assert c2b is not None
            assert c2b.status == "matched"
            assert c2b.landlord_id == landlord.id
            _cleanup(db_session, ("platform_c2b_payments", c2b.id))
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_unknown_bill_ref_is_unmatched(self, app, client, db_session):
        trans_id = f"NLJ{uuid.uuid4().hex[:8].upper()}"
        resp = client.post("/api/webhooks/daraja/c2b/confirmation",
                            json=self._payload(trans_id, 1000, "GARBAGE-REF"))
        assert resp.status_code == 200

        c2b = PlatformC2BPayment.query.filter_by(trans_id=trans_id).first()
        assert c2b is not None
        assert c2b.status == "unmatched"
        _cleanup(db_session, ("platform_c2b_payments", c2b.id))

    def test_wrong_amount_is_unmatched_not_activated(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        txn = pending_txn(db_session, landlord, "subscription", "1000.00")
        trans_id = f"NLJ{uuid.uuid4().hex[:8].upper()}"

        try:
            resp = client.post("/api/webhooks/daraja/c2b/confirmation",
                                json=self._payload(trans_id, 1, f"SUB-{landlord.id}"))
            assert resp.status_code == 200

            db_session.refresh(txn)
            assert txn.is_verified is False

            c2b = PlatformC2BPayment.query.filter_by(trans_id=trans_id).first()
            assert c2b.status == "unmatched"
            _cleanup(db_session, ("platform_c2b_payments", c2b.id))
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))

    def test_duplicate_trans_id_is_idempotent(self, app, client, db_session):
        trans_id = f"NLJ{uuid.uuid4().hex[:8].upper()}"
        payload = self._payload(trans_id, 1000, "SUB-999999")

        r1 = client.post("/api/webhooks/daraja/c2b/confirmation", json=payload)
        r2 = client.post("/api/webhooks/daraja/c2b/confirmation", json=payload)
        assert r1.status_code == 200
        assert r2.status_code == 200

        rows = PlatformC2BPayment.query.filter_by(trans_id=trans_id).all()
        assert len(rows) == 1
        _cleanup(db_session, ("platform_c2b_payments", rows[0].id))

    def test_sms_ref_matches_pending_sms_txn(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        starting_balance = landlord.sms_balance
        txn = pending_txn(db_session, landlord, "sms_purchase", "100.00", sms_count=100)
        trans_id = f"NLJ{uuid.uuid4().hex[:8].upper()}"

        try:
            resp = client.post("/api/webhooks/daraja/c2b/confirmation",
                                json=self._payload(trans_id, 100, f"SMS-{landlord.id}"))
            assert resp.status_code == 200

            db_session.refresh(txn)
            db_session.refresh(landlord)
            assert txn.is_verified is True
            assert landlord.sms_balance == starting_balance + 100

            c2b = PlatformC2BPayment.query.filter_by(trans_id=trans_id).first()
            _cleanup(db_session, ("platform_c2b_payments", c2b.id))
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id), ("users", user.id))


# ---------------------------------------------------------------------------
# Legacy self-reported endpoints — verified-only (D3)
# ---------------------------------------------------------------------------

class TestLegacyEndpointsDemoted:
    def test_pay_subscription_no_longer_activates(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        original_status = landlord.subscription.status

        try:
            resp = client.post(
                "/api/billing/pay-subscription",
                json={"billing_cycle": "monthly", "payment_reference": "ANYTHING-I-TYPE"},
                headers=_auth_header(user),
            )
            assert resp.status_code == 202

            txn_id = resp.json["transaction"]["id"]
            txn = db_session.get(BillingTransaction, txn_id)
            assert txn.is_verified is False
            assert txn.status == BillingTransactionStatus.pending.value

            db_session.refresh(landlord.subscription)
            assert landlord.subscription.status == original_status  # unchanged — not activated

            _cleanup(db_session, ("billing_transactions", txn_id))
        finally:
            _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))

    def test_buy_sms_no_longer_credits_balance(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        starting_balance = landlord.sms_balance

        try:
            resp = client.post(
                "/api/billing/buy-sms",
                json={"sms_count": 100, "payment_reference": "ANYTHING-I-TYPE"},
                headers=_auth_header(user),
            )
            assert resp.status_code == 202

            txn_id = resp.json["transaction"]["id"]
            txn = db_session.get(BillingTransaction, txn_id)
            assert txn.is_verified is False

            db_session.refresh(landlord)
            assert landlord.sms_balance == starting_balance  # unchanged

            _cleanup(db_session, ("billing_transactions", txn_id))
        finally:
            _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))

    def test_admin_verify_activates_legacy_subscription_txn(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        admin = make_admin(db_session)
        txn = pending_txn(db_session, landlord, "subscription", "1000.00", checkout_id="MANUAL-REF-1")

        try:
            resp = client.post(f"/api/admin/billing-transactions/{txn.id}/verify",
                                headers=_auth_header(admin))
            assert resp.status_code == 200

            db_session.refresh(txn)
            assert txn.is_verified is True
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id),
                     ("users", user.id), ("users", admin.id))

    def test_admin_verify_activates_legacy_sms_txn(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        admin = make_admin(db_session)
        starting_balance = landlord.sms_balance
        txn = pending_txn(db_session, landlord, "sms_purchase", "100.00", checkout_id="MANUAL-REF-2", sms_count=100)

        try:
            resp = client.post(f"/api/admin/billing-transactions/{txn.id}/verify",
                                headers=_auth_header(admin))
            assert resp.status_code == 200

            db_session.refresh(txn)
            db_session.refresh(landlord)
            assert txn.is_verified is True
            assert landlord.sms_balance == starting_balance + 100
        finally:
            _cleanup(db_session, ("billing_transactions", txn.id), ("landlords", landlord.id),
                     ("users", user.id), ("users", admin.id))


# ---------------------------------------------------------------------------
# Rent STK gate (D1)
# ---------------------------------------------------------------------------

class TestRentStkGate:
    def test_stk_push_returns_409(self, app, client, db_session):
        user, landlord = make_landlord(db_session)
        try:
            resp = client.post("/api/mpesa/stk-push",
                                json={"tenant_id": 1, "amount": 5000},
                                headers=_auth_header(user))
            assert resp.status_code == 409
        finally:
            _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


# ---------------------------------------------------------------------------
# B2C payout
# ---------------------------------------------------------------------------

class TestB2cPayout:
    def _make_withdrawal(self, session, affiliate, gross="1000.00"):
        cfg = svc.get_program_config()
        w = svc.request_withdrawal(affiliate, Decimal(gross))
        session.commit()
        return w

    def test_simulation_mode_pays_immediately(self, app, client, db_session):
        user, landlord = make_landlord(db_session, monthly_cost="2000")
        admin = make_admin(db_session)
        affiliate, referral = make_affiliate_with_referral(db_session, landlord)

        txn = pending_txn(db_session, landlord, "subscription", "2000.00", checkout_id="SIM1")
        from services import billing_service
        billing_service.finalize_subscription_payment(txn)
        db_session.commit()

        commission = AffiliateCommission.query.filter_by(billing_transaction_id=txn.id).first()
        assert commission is not None

        withdrawal = self._make_withdrawal(db_session, affiliate, gross=str(commission.amount))

        try:
            resp = client.post(f"/api/admin/affiliates/withdrawals/{withdrawal.id}/pay-b2c",
                                headers=_auth_header(admin))
            assert resp.status_code == 200
            assert resp.json.get("simulated") is True

            db_session.refresh(withdrawal)
            assert withdrawal.status == WithdrawalStatus.paid.value
            assert withdrawal.mpesa_reference is not None
            assert withdrawal.receipt_number is not None
            assert withdrawal.paid_amount == Decimal(int(withdrawal.net_amount))
        finally:
            _cleanup(
                db_session,
                ("affiliate_withdrawals", withdrawal.id),
                ("affiliate_commissions", commission.id),
                ("billing_transactions", txn.id),
                ("affiliate_referrals", referral.id),
                ("affiliates", affiliate.id),
                ("landlords", landlord.id),
                ("users", user.id), ("users", admin.id),
            )
            # affiliate's own user row cleaned via affiliate.user_id — fetch first
    def test_double_pay_lock_rejects_second_attempt_while_in_flight(self, app, client, db_session):
        user, landlord = make_landlord(db_session, monthly_cost="2000")
        admin = make_admin(db_session)
        affiliate, referral = make_affiliate_with_referral(db_session, landlord)

        txn = pending_txn(db_session, landlord, "subscription", "2000.00", checkout_id="SIM2")
        from services import billing_service
        billing_service.finalize_subscription_payment(txn)
        db_session.commit()
        commission = AffiliateCommission.query.filter_by(billing_transaction_id=txn.id).first()

        withdrawal = self._make_withdrawal(db_session, affiliate, gross=str(commission.amount))
        withdrawal.b2c_status = "sent"  # simulate an in-flight payout (real-mode path would set this)
        db_session.commit()

        try:
            resp = client.post(f"/api/admin/affiliates/withdrawals/{withdrawal.id}/pay-b2c",
                                headers=_auth_header(admin))
            assert resp.status_code == 409
        finally:
            _cleanup(
                db_session,
                ("affiliate_withdrawals", withdrawal.id),
                ("affiliate_commissions", commission.id),
                ("billing_transactions", txn.id),
                ("affiliate_referrals", referral.id),
                ("affiliates", affiliate.id),
                ("landlords", landlord.id),
                ("users", user.id), ("users", admin.id),
            )

    def test_missing_mpesa_number_rejected(self, app, client, db_session):
        user, landlord = make_landlord(db_session, monthly_cost="2000")
        admin = make_admin(db_session)
        affiliate, referral = make_affiliate_with_referral(db_session, landlord)
        affiliate.mpesa_number = None
        db_session.commit()

        txn = pending_txn(db_session, landlord, "subscription", "2000.00", checkout_id="SIM3")
        from services import billing_service
        billing_service.finalize_subscription_payment(txn)
        db_session.commit()
        commission = AffiliateCommission.query.filter_by(billing_transaction_id=txn.id).first()

        # request_withdrawal itself requires mpesa_number — set it, request, then null it
        affiliate.mpesa_number = "254733000111"
        db_session.commit()
        withdrawal = self._make_withdrawal(db_session, affiliate, gross=str(commission.amount))
        affiliate.mpesa_number = None
        db_session.commit()

        try:
            resp = client.post(f"/api/admin/affiliates/withdrawals/{withdrawal.id}/pay-b2c",
                                headers=_auth_header(admin))
            assert resp.status_code == 400
        finally:
            _cleanup(
                db_session,
                ("affiliate_withdrawals", withdrawal.id),
                ("affiliate_commissions", commission.id),
                ("billing_transactions", txn.id),
                ("affiliate_referrals", referral.id),
                ("affiliates", affiliate.id),
                ("landlords", landlord.id),
                ("users", user.id), ("users", admin.id),
            )


# ---------------------------------------------------------------------------
# Full affiliate chain (referral -> STK subscription -> commission ->
# withdrawal -> B2C pay -> balance math)
# ---------------------------------------------------------------------------

class TestFullAffiliateChain:
    def test_end_to_end_chain(self, app, client, db_session):
        user, landlord = make_landlord(db_session, monthly_cost="2000")
        admin = make_admin(db_session)
        affiliate, referral = make_affiliate_with_referral(db_session, landlord, rate="55.00", months=3)

        checkout_id = f"ws_CO_{uuid.uuid4().hex[:16]}"
        txn = pending_txn(db_session, landlord, "subscription", "2000.00", checkout_id)
        # stamp months_covered like the real STK flow would via context_json
        ctx = dict(txn.context_json)
        ctx["months"] = 1
        txn.context_json = ctx
        db_session.commit()

        try:
            resp = client.post("/api/webhooks/daraja/billing-callback",
                                json=_stk_callback_payload(checkout_id, 2000))
            assert resp.status_code == 200

            commission = AffiliateCommission.query.filter_by(billing_transaction_id=txn.id).first()
            assert commission is not None
            assert commission.rate_applied == Decimal("55.00")
            expected_commission = (Decimal("2000") * Decimal("0.55")).quantize(Decimal("0.01"))
            assert commission.amount == expected_commission

            balance_before = svc.get_balance(affiliate.id)
            assert balance_before == expected_commission

            withdrawal = svc.request_withdrawal(affiliate, expected_commission)
            db_session.commit()

            balance_after_request = svc.get_balance(affiliate.id)
            assert balance_after_request == Decimal("0.00")

            pay_resp = client.post(f"/api/admin/affiliates/withdrawals/{withdrawal.id}/pay-b2c",
                                    headers=_auth_header(admin))
            assert pay_resp.status_code == 200

            db_session.refresh(withdrawal)
            assert withdrawal.status == WithdrawalStatus.paid.value
        finally:
            w = AffiliateWithdrawal.query.filter_by(affiliate_id=affiliate.id).first()
            c = AffiliateCommission.query.filter_by(billing_transaction_id=txn.id).first()
            _cleanup(
                db_session,
                *([("affiliate_withdrawals", w.id)] if w else []),
                *([("affiliate_commissions", c.id)] if c else []),
                ("billing_transactions", txn.id),
                ("affiliate_referrals", referral.id),
                ("affiliates", affiliate.id),
                ("landlords", landlord.id),
                ("users", user.id), ("users", admin.id),
            )


# ---------------------------------------------------------------------------
# Simulation-mode regression — no outbound HTTP ever leaves daraja_service
# ---------------------------------------------------------------------------

class TestSimulationModeNeverCallsOut:
    def test_stk_simulation_makes_no_http_call(self, app, client, db_session, monkeypatch):
        import services.daraja_service as daraja_service

        def _boom(*args, **kwargs):
            raise AssertionError("daraja_service made a real HTTP call during simulation mode")

        monkeypatch.setattr(daraja_service.ext_requests, "get", _boom)
        monkeypatch.setattr(daraja_service.ext_requests, "post", _boom)

        user, landlord = make_landlord(db_session)
        try:
            resp = client.post("/api/billing/pay-subscription/stk",
                                json={"billing_cycle": "monthly", "phone": "254712345678"},
                                headers=_auth_header(user))
            assert resp.status_code == 201
            assert resp.json.get("simulated") is True

            txn_id = resp.json["transaction"]["id"]
            _cleanup(db_session, ("billing_transactions", txn_id))
        finally:
            _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))
