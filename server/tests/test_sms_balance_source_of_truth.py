"""
SMS balance = confirmed payments - usage, the source of truth.

Covers the production bug (a landlord who bought 1,000 credits read 2,000) and
its two defences:

  1. SOURCE: crediting is idempotent on the M-Pesa receipt, so one payment
     confirmed twice — the STK callback AND the C2B confirmation of the same
     money — credits exactly once.
  2. REPAIR: services/sms_credit_ledger.reconcile_sms_balance rebuilds a balance
     from confirmed purchases (deduped by receipt) + genuine manual credits -
     credits used, healing any historical drift. The deploy migration runs the
     same computation for every landlord.
"""

import itertools
import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, CommunicationLog,
    BillingTransaction, BillingTransactionType, BillingTransactionStatus,
    SmsLandlordCredit,
)
from services.sms_credit_ledger import (
    compute_truth, reconcile_sms_balance, RECON_REASON_PREFIX,
)

_counter = itertools.count()


def _uniq() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


def make_landlord(session, *, sms_balance=0, price_override=None, is_demo=False):
    n = _uniq()
    user = User(
        email=f"sot-landlord{n}@test.sahilpay",
        phone=f"2547{next(_counter):08d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord",
        is_verified=True,
    )
    session.add(user)
    session.flush()
    landlord = Landlord(
        user_id=user.id, company_name=f"SoT Landlord {n}", currency="KES",
        sms_balance=sms_balance, is_demo=is_demo,
    )
    if price_override is not None:
        landlord.sms_price_override = Decimal(str(price_override))
    session.add(landlord)
    session.flush()
    session.commit()
    return user, landlord


def make_admin(session):
    n = _uniq()
    user = User(
        email=f"sot-admin{n}@test.sahilpay",
        phone=f"2547{next(_counter):08d}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", totp_enabled=True, is_verified=True,
    )
    session.add(user)
    session.commit()
    return user


def _confirmed_purchase(session, landlord, *, credits, amount, receipt,
                        verified=True, reversed_=False):
    txn = BillingTransaction(
        landlord_id=landlord.id,
        type=BillingTransactionType.sms_purchase.value,
        amount=Decimal(str(amount)),
        sms_count=credits,
        payment_reference=receipt,
        status=BillingTransactionStatus.paid.value if verified else BillingTransactionStatus.pending.value,
        context_json={"sms_count": credits, "applied": verified},
        is_verified=verified,
        is_reversed=reversed_,
    )
    session.add(txn)
    session.flush()
    return txn


def _usage(session, landlord, *, credits, status="delivered"):
    log = CommunicationLog(
        landlord_id=landlord.id, message_type="sms", content="hi",
        sms_credits=credits, status=status,
    )
    session.add(log)
    session.flush()
    return log


# ---------------------------------------------------------------------------
# compute_truth — the derivation
# ---------------------------------------------------------------------------

def test_truth_is_purchases_minus_usage(db_session):
    _, landlord = make_landlord(db_session)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="RCPT-A")
    _usage(db_session, landlord, credits=30)
    _usage(db_session, landlord, credits=12)

    truth = compute_truth(landlord.id)
    assert truth["purchased"] == 1000
    assert truth["used"] == 42
    assert truth["target"] == 958


def test_duplicate_receipt_counts_once(db_session):
    """The production bug: two confirmed purchase rows, same M-Pesa receipt."""
    _, landlord = make_landlord(db_session)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="QFG12ABC3D")
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="QFG12ABC3D")

    truth = compute_truth(landlord.id)
    assert truth["purchased"] == 1000, "one payment must grant its credits once"
    assert truth["target"] == 1000


def test_unconfirmed_and_reversed_purchases_excluded(db_session):
    _, landlord = make_landlord(db_session)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="GOOD")
    _confirmed_purchase(db_session, landlord, credits=500, amount=250, receipt="PENDING", verified=False)
    _confirmed_purchase(db_session, landlord, credits=400, amount=200, receipt="CHARGEBACK", reversed_=True)

    truth = compute_truth(landlord.id)
    assert truth["purchased"] == 1000


def test_failed_sends_are_not_usage(db_session):
    _, landlord = make_landlord(db_session)
    _confirmed_purchase(db_session, landlord, credits=100, amount=50, receipt="R")
    _usage(db_session, landlord, credits=0, status="failed")   # failed → recorded 0
    _usage(db_session, landlord, credits=5, status="delivered")

    assert compute_truth(landlord.id)["used"] == 5


def test_manual_credits_count_but_recon_rows_do_not(db_session):
    _, landlord = make_landlord(db_session)
    db_session.add(SmsLandlordCredit(
        landlord_id=landlord.id, credits_added=200, balance_after=200,
        reason="M-Pesa 100 KES paid to operator, code ABC",
    ))
    db_session.add(SmsLandlordCredit(
        landlord_id=landlord.id, credits_added=-50, balance_after=150,
        reason=f"{RECON_REASON_PREFIX} earlier correction",
    ))
    db_session.flush()

    assert compute_truth(landlord.id)["manual"] == 200


# ---------------------------------------------------------------------------
# reconcile_sms_balance — the repair
# ---------------------------------------------------------------------------

def test_reconcile_corrects_double_credit_and_writes_ledger(db_session):
    _, landlord = make_landlord(db_session, sms_balance=2000)   # inflated by the bug
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="DUP")
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="DUP")

    result = reconcile_sms_balance(landlord, apply=True)
    assert landlord.sms_balance == 1000
    assert result["before"] == 2000 and result["after"] == 1000 and result["delta"] == -1000

    recon = (SmsLandlordCredit.query
             .filter_by(landlord_id=landlord.id)
             .filter(SmsLandlordCredit.reason.like(RECON_REASON_PREFIX + "%")).all())
    assert len(recon) == 1
    assert recon[0].credits_added == -1000 and recon[0].balance_after == 1000


def test_reconcile_is_idempotent_and_spares_clean_accounts(db_session):
    _, landlord = make_landlord(db_session, sms_balance=958)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="R")
    _usage(db_session, landlord, credits=42)

    first = reconcile_sms_balance(landlord, apply=True)
    assert first["changed"] is False and landlord.sms_balance == 958

    second = reconcile_sms_balance(landlord, apply=True)
    assert second["changed"] is False
    assert SmsLandlordCredit.query.filter_by(landlord_id=landlord.id).count() == 0


def test_reconcile_also_fixes_undercredit(db_session):
    """Truth corrects a balance that was too LOW, not only too high."""
    _, landlord = make_landlord(db_session, sms_balance=0)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="R")

    reconcile_sms_balance(landlord, apply=True)
    assert landlord.sms_balance == 1000


# ---------------------------------------------------------------------------
# Source-side idempotency — one payment, two callbacks, credited once
# ---------------------------------------------------------------------------

def _stk_payload(checkout_id, amount, receipt):
    return {
        "Body": {"stkCallback": {
            "CheckoutRequestID": checkout_id, "ResultCode": 0, "ResultDesc": "ok",
            "CallbackMetadata": {"Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
                {"Name": "PhoneNumber", "Value": 254700000000},
            ]},
        }}
    }


def _c2b_payload(trans_id, amount, bill_ref):
    return {
        "TransID": trans_id, "TransAmount": amount, "BillRefNumber": bill_ref,
        "MSISDN": "254700000000", "FirstName": "Test", "TransTime": "20261015120000",
    }


def test_stk_then_c2b_same_receipt_credits_once(app, client, db_session):
    """
    End-to-end: a landlord buys 1,000 credits (KES 500 @ 0.50). The STK callback
    confirms it, then the C2B confirmation of the SAME M-Pesa money arrives. The
    balance must land on 1,000, never 2,000.
    """
    _, landlord = make_landlord(db_session, sms_balance=0, price_override="0.50")
    checkout_id = f"ws_CO_{_uniq()}"
    receipt = f"QFG{_uniq()}"

    # Pending purchase created by POST /api/billing/buy-sms/stk.
    txn = BillingTransaction(
        landlord_id=landlord.id, type=BillingTransactionType.sms_purchase.value,
        amount=Decimal("500"), sms_count=1000, payment_reference=checkout_id,
        status=BillingTransactionStatus.pending.value,
        context_json={"sms_count": 1000, "unit_price": "0.50", "applied": False},
    )
    db_session.add(txn)
    db_session.commit()

    with app.app_context():
        r1 = client.post("/api/webhooks/daraja/billing-callback",
                         json=_stk_payload(checkout_id, 500, receipt))
        assert r1.status_code == 200
        after_stk = db.session.get(Landlord, landlord.id).sms_balance
        assert after_stk == 1000

        r2 = client.post("/api/webhooks/daraja/c2b/confirmation",
                         json=_c2b_payload(receipt, 500, f"SMS-{landlord.id}"))
        assert r2.status_code == 200
        after_c2b = db.session.get(Landlord, landlord.id).sms_balance
        assert after_c2b == 1000, f"double-credit regression: balance is {after_c2b}, expected 1000"


# ---------------------------------------------------------------------------
# Admin resync endpoint
# ---------------------------------------------------------------------------

def test_admin_resync_endpoint_corrects_balance(app, client, db_session):
    admin = make_admin(db_session)
    _, landlord = make_landlord(db_session, sms_balance=2000)
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="DUP")
    _confirmed_purchase(db_session, landlord, credits=1000, amount=500, receipt="DUP")
    db_session.commit()

    headers = {"Authorization": f"Bearer {create_access_token(identity=str(admin.id), additional_claims={'role': 'system_admin'})}"}
    with app.app_context():
        preview = client.get(f"/api/admin/sms/landlords/{landlord.id}/balance-truth", headers=headers)
        assert preview.status_code == 200
        assert preview.get_json()["truth"]["target"] == 1000
        assert preview.get_json()["in_sync"] is False

        resp = client.post(f"/api/admin/sms/landlords/{landlord.id}/resync", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["sms_balance"] == 1000
        assert db.session.get(Landlord, landlord.id).sms_balance == 1000
