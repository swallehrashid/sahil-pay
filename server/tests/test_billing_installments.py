"""
Billing: installments, the account lock, exemptions, and "never paid until
Safaricom says so".

  * a landlord chooses the amount; any verified amount reduces the balance;
  * a billing date that passes adds the period's charge (6,000 of 10,000 paid
    this month → 14,000 next month);
  * a balance older than the grace period locks the landlord portal, billing
    stays reachable, and paying it off (or an admin exemption) opens it;
  * an STK prompt — even in simulation — is PENDING until a callback confirms;
  * the receipt downloads only for a confirmed payment, as a real PDF.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from models import BillingTransaction, PlatformC2BPayment
from services import billing_service
from tests.test_daraja_webhooks import (  # noqa: F401
    client, make_landlord, make_admin, _auth_header, _stk_callback_payload, _cleanup,
)


def _stk(client, user, **body):
    body.setdefault("phone", "0712345678")
    return client.post("/api/billing/pay/stk", json=body, headers=_auth_header(user))


def test_an_stk_payment_stays_pending_until_the_callback_confirms_it(app, client, db_session):
    user, landlord = make_landlord(db_session, monthly_cost="10000")
    landlord.subscription.amount_due = Decimal("10000")
    db_session.commit()
    try:
        res = _stk(client, user, purpose="subscription", amount=6000)
        assert res.status_code == 200, res.get_data(as_text=True)
        txn = res.json["transaction"]
        assert txn["status"] == "pending" and txn["is_verified"] is False
        db_session.refresh(landlord.subscription)
        assert landlord.subscription.amount_due == Decimal("10000.00"), "nothing changes before confirmation"

        # Receipt is refused while pending.
        assert client.get(f"/api/billing/transactions/{txn['id']}/receipt",
                          headers=_auth_header(user)).status_code == 409

        # Safaricom confirms.
        client.post("/api/webhooks/daraja/billing-callback",
                    json=_stk_callback_payload(txn["payment_reference"], 6000, receipt="SJK4TEST01"))
        row = db_session.get(BillingTransaction, txn["id"])
        db_session.refresh(row)
        assert row.is_verified and row.status == "paid"
        db_session.refresh(landlord.subscription)
        assert landlord.subscription.amount_due == Decimal("4000.00")
        assert row.context_json["balance_before"] == "10000.00"
        assert row.context_json["balance_after"] == "4000.00"

        pdf = client.get(f"/api/billing/transactions/{txn['id']}/receipt", headers=_auth_header(user))
        assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-"
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


def test_a_cancelled_prompt_is_failed_and_changes_nothing(app, client, db_session):
    user, landlord = make_landlord(db_session)
    landlord.subscription.amount_due = Decimal("1000")
    db_session.commit()
    try:
        txn = _stk(client, user, purpose="subscription", amount=1000).json["transaction"]
        client.post("/api/webhooks/daraja/billing-callback",
                    json=_stk_callback_payload(txn["payment_reference"], 1000, result_code=1032))
        row = db_session.get(BillingTransaction, txn["id"])
        db_session.refresh(row)
        assert row.status == "failed" and not row.is_verified
        db_session.refresh(landlord.subscription)
        assert landlord.subscription.amount_due == Decimal("1000.00")
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


def test_an_unpaid_balance_carries_into_next_months_charge(app, db_session):
    user, landlord = make_landlord(db_session, monthly_cost="10000")
    sub = landlord.subscription
    today = date.today()
    sub.amount_due = Decimal("4000")               # 6,000 of 10,000 paid
    sub.balance_due_since = today - timedelta(days=2)
    sub.next_billing_date = today
    db_session.commit()
    try:
        assert billing_service.roll_forward(landlord, today) == 1
        assert sub.amount_due == Decimal("14000.00")
        assert sub.next_billing_date > today
        assert billing_service.roll_forward(landlord, today) == 0, "idempotent"
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


def test_the_portal_locks_after_grace_and_billing_stays_open(app, client, db_session):
    user, landlord = make_landlord(db_session)
    sub = landlord.subscription
    sub.amount_due = Decimal("1000")
    sub.balance_due_since = date.today() - timedelta(days=billing_service.grace_days() + 1)
    sub.next_billing_date = date.today() + timedelta(days=20)
    db_session.commit()
    try:
        locked = client.get("/api/properties", headers=_auth_header(user))
        assert locked.status_code == 402
        assert locked.json.get("code") == "subscription_locked"

        billing = client.get("/api/billing/", headers=_auth_header(user))
        assert billing.status_code == 200
        assert billing.json["access"]["locked"] is True

        # A partial payment does NOT open it…
        sub.amount_due = Decimal("400")
        db_session.commit()
        assert client.get("/api/properties", headers=_auth_header(user)).status_code == 402
        # …clearing the balance does.
        sub.amount_due = Decimal("0")
        billing_service._settle_status(sub, date.today())
        db_session.commit()
        assert client.get("/api/properties", headers=_auth_header(user)).status_code == 200
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


def test_an_admin_exemption_opens_a_locked_account(app, client, db_session):
    user, landlord = make_landlord(db_session)
    admin = make_admin(db_session)
    sub = landlord.subscription
    sub.amount_due = Decimal("4000")
    sub.balance_due_since = date.today() - timedelta(days=30)
    db_session.commit()
    try:
        assert client.get("/api/properties", headers=_auth_header(user)).status_code == 402
        until = (date.today() + timedelta(days=30)).isoformat()
        res = client.put(f"/api/admin/pricing/landlords/{landlord.id}/billing",
                         json={"access_override_until": until, "access_override_reason": "Paid 6,000 of 10,000"},
                         headers=_auth_header(admin))
        if res.status_code == 404:
            res = client.patch(f"/api/admin/pricing/landlords/{landlord.id}/billing",
                               json={"access_override_until": until, "access_override_reason": "Paid 6,000"},
                               headers=_auth_header(admin))
        assert res.status_code == 200, res.get_data(as_text=True)
        assert client.get("/api/properties", headers=_auth_header(user)).status_code == 200
        db_session.refresh(sub)
        assert sub.amount_due == Decimal("4000.00"), "the balance is kept, not forgiven"
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id), ("users", admin.id))


def test_a_paybill_code_we_have_not_seen_is_pending_not_confirmed(app, client, db_session):
    user, landlord = make_landlord(db_session)
    landlord.subscription.amount_due = Decimal("1000")
    db_session.commit()
    try:
        res = client.post("/api/billing/confirm-payment", json={"mpesa_code": "SJK9NOTSEEN"},
                          headers=_auth_header(user))
        assert res.status_code == 202
        assert res.json["transaction"]["status"] == "pending"
        db_session.refresh(landlord.subscription)
        assert landlord.subscription.amount_due == Decimal("1000.00")
    finally:
        _cleanup(db_session, ("landlords", landlord.id), ("users", user.id))


def test_a_paybill_payment_that_landed_confirms_by_code(app, client, db_session):
    user, landlord = make_landlord(db_session)
    landlord.subscription.amount_due = Decimal("1000")
    db_session.commit()
    code = f"SJK{uuid.uuid4().hex[:7].upper()}"
    try:
        # Safaricom reports it with a mistyped account number.
        client.post("/api/webhooks/daraja/c2b/confirmation", json={
            "TransID": code, "TransAmount": 500, "BillRefNumber": f"sub {landlord.id}",
            "MSISDN": "2547xxxx", "TransTime": "20260916120000"})
        assert PlatformC2BPayment.query.filter_by(trans_id=code).first().status == "unmatched"

        res = client.post("/api/billing/confirm-payment", json={"mpesa_code": code},
                          headers=_auth_header(user))
        assert res.status_code == 200, res.get_data(as_text=True)
        db_session.refresh(landlord.subscription)
        assert landlord.subscription.amount_due == Decimal("500.00")
    finally:
        c2b = PlatformC2BPayment.query.filter_by(trans_id=code).first()
        _cleanup(db_session, *([("platform_c2b_payments", c2b.id)] if c2b else []),
                 ("landlords", landlord.id), ("users", user.id))


def test_the_webhook_ignores_a_forged_forwarded_for_header(app, client, db_session):
    app.config["DARAJA_ALLOWED_IPS"] = "196.201.214.200"
    app.config["TRUST_PROXY"] = True
    app.config["TRUSTED_PROXY_HOPS"] = 1
    try:
        with app.test_request_context("/api/webhooks/daraja/billing-callback", method="POST",
                                      headers={"X-Forwarded-For": "196.201.214.200, 203.0.113.9"}):
            from routes.webhook_routes import _daraja_ip_allowed
            assert _daraja_ip_allowed() is False
        with app.test_request_context("/api/webhooks/daraja/billing-callback", method="POST",
                                      headers={"X-Forwarded-For": "203.0.113.9, 196.201.214.200"}):
            assert _daraja_ip_allowed() is True
    finally:
        app.config["DARAJA_ALLOWED_IPS"] = ""
        app.config["TRUST_PROXY"] = False
