"""Every SMS sent on a landlord's account comes off THAT account's SMS balance.

Only the tenant sign-in code is on Sahil Pay. Welcome messages, reminders and
alert texts are all the landlord's — whoever on the account triggered them.
"""

import random

import pytest

from models import AlertSetting, CommunicationLog, SmsPricingConfig
from services.alert_service import dispatch_alert
from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_team_member, _make_unit, _token,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def account(app, db_session):
    landlord, user = _make_landlord(db_session, "sms")
    landlord.sms_balance = 10
    cfg = SmsPricingConfig.get_singleton()
    cfg.pool_balance = 1_000_000
    prop = _make_property(db_session, landlord, "Sms")
    unit = _make_unit(db_session, prop, "S1")
    tm, tm_user = _make_team_member(db_session, landlord, property_ids=[prop.id],
                                    modules=["tenants", "messages"])
    db_session.flush()
    owner_h = _auth(_token(app, user, landlord_id=landlord.id))
    team_h = _auth(_token(app, tm_user, landlord_id=landlord.id, team_member_id=tm.id))
    return landlord, user, unit, owner_h, team_h, cfg


def _phone():
    return f"07{random.randint(10000000, 99999999)}"


def test_welcome_sent_by_a_team_member_is_charged_to_the_account(client, account, db_session):
    landlord, user, unit, owner_h, team_h, cfg = account
    pool_before = cfg.pool_balance
    r = client.post("/api/tenants/", headers=team_h, json={
        "unit_id": unit.id, "first_name": "Wema", "last_name": "Achieng",
        "phone": _phone(), "send_welcome_message": True,
    })
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["welcome_message"] == "sent"
    db_session.refresh(landlord)
    spent = 10 - landlord.sms_balance
    assert spent >= 1
    assert cfg.pool_balance == pool_before - spent
    log = CommunicationLog.query.filter_by(landlord_id=landlord.id, message_type="sms").one()
    assert log.status == "delivered" and log.sms_charge > 0


def test_reminder_is_charged_to_the_account(client, account, db_session):
    landlord, user, unit, owner_h, team_h, cfg = account
    t = client.post("/api/tenants/", headers=owner_h, json={
        "unit_id": unit.id, "first_name": "Baraka", "last_name": "M", "phone": _phone(),
    }).get_json()
    tenant_id = t.get("id") or t["tenant"]["id"]
    before = landlord.sms_balance
    r = client.post(f"/api/tenants/{tenant_id}/reminder", headers=team_h, json={"channels": ["sms"]})
    assert r.status_code == 200, r.get_json()
    db_session.refresh(landlord)
    assert landlord.sms_balance < before


def test_no_credits_means_no_welcome_sms(client, account, db_session):
    landlord, user, unit, owner_h, team_h, cfg = account
    landlord.sms_balance = 0
    db_session.flush()
    pool_before = cfg.pool_balance
    client.post("/api/tenants/", headers=owner_h, json={
        "unit_id": unit.id, "first_name": "Imani", "last_name": "K",
        "phone": _phone(), "send_welcome_message": True,
    })
    log = CommunicationLog.query.filter_by(landlord_id=landlord.id, message_type="sms").one()
    assert log.status == "failed" and "Insufficient SMS balance" in log.failure_reason
    assert cfg.pool_balance == pool_before


def test_alert_sms_to_the_landlord_is_charged_to_the_account(account, db_session):
    landlord, user, *_ , cfg = account
    user.phone = "254712000111"
    db_session.add(AlertSetting(landlord_id=landlord.id, alert_type="payment_received",
                                is_enabled=True, channel="sms"))
    db_session.flush()
    assert dispatch_alert(landlord.id, "payment_received", title="Paid", body="KES 5,000") == "sms"
    db_session.refresh(landlord)
    assert landlord.sms_balance < 10


def test_alert_with_no_credits_is_not_sent_free(account, db_session):
    landlord, user, *_ , cfg = account
    landlord.sms_balance = 0
    user.phone = "254712000111"
    db_session.add(AlertSetting(landlord_id=landlord.id, alert_type="payment_received",
                                is_enabled=True, channel="sms"))
    db_session.flush()
    pool_before = cfg.pool_balance
    delivered = dispatch_alert(landlord.id, "payment_received", title="Paid", body="KES 5,000")
    assert delivered in ("email", "dashboard")
    assert cfg.pool_balance == pool_before
    assert landlord.sms_balance == 0


def test_message_accepted_without_an_id_is_still_charged(app, account, db_session, monkeypatch):
    """FluxSMS bills Sahil Pay for a message it accepted even when it returns no id
    (a scheduled send). Treating that as a failure sent it free on Sahil's pool."""
    from models import Tenant
    from services import sms_service
    from services.communication_service import dispatch_message

    landlord, user, unit, *_ , cfg = account
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="A", last_name="B",
                    phone="254712000222")
    db_session.add(tenant)
    db_session.flush()
    monkeypatch.setitem(app.config, "COMMS_SIMULATION_MODE", False)
    monkeypatch.setattr(sms_service, "send_sms", lambda *a, **k: sms_service.ACCEPTED_NO_ID)
    pool_before = cfg.pool_balance

    log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Welcome")
    assert log.status == "pending" and log.provider_message_id is None
    assert landlord.sms_balance < 10
    assert cfg.pool_balance < pool_before


def test_a_route_that_forgets_to_commit_still_keeps_the_charge(app, account, db_session):
    """The reminder route used to send the SMS and then never commit, so the
    charge and the log were rolled back: a free SMS on Sahil Pay's pool. The
    end-of-request hook now persists any charge made during a successful request."""
    from flask import Response

    from models import Landlord, Tenant
    from services.communication_service import dispatch_message

    landlord, user, unit, *_ , cfg = account
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="C", last_name="D",
                    phone="254712000333")
    db_session.add(tenant)
    db_session.commit()
    lid, tid = landlord.id, tenant.id

    with app.test_request_context("/api/anything", method="POST"):
        dispatch_message(landlord_id=lid, tenant=db_session.get(Tenant, tid), channel="sms", content="Hi")
        app.process_response(Response(status=200))   # runs after_request hooks; no route commit
    db_session.rollback()

    assert db_session.get(Landlord, lid).sms_balance < 10
    assert CommunicationLog.query.filter_by(landlord_id=lid, tenant_id=tid).count() == 1
