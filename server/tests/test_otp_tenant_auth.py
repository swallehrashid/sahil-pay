"""
Regression suite for tenant OTP authentication identity.

Guards the cross-account bug where an OTP login landed on the WRONG account:
verify_otp() minted the JWT identity as str(tenant.user_id or tenant.id), so an
OTP-only tenant with user_id=None got an identity of str(tenant.id) — a bare
integer that user_lookup_loader then resolved as a User.id, logging the tenant
into whatever unrelated User (often a landlord's team member) happened to share
that id number.

The fix namespaces the tenant identity as "tenant:<id>" so it can never collide
with a User.id, and user_lookup_loader returns None for it.

Fixture style follows test_copilot_landlord_inbox.py (service-layer factories +
HTTP test client).
"""

import hashlib
import uuid
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import decode_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant,
    OtpToken, OtpChannel,
)


def _uniq() -> str:
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_landlord(session):
    n = _uniq()
    user = User(
        email=f"otp-ll{n}@test.sahilpay", phone=f"25470{n}0",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True,
    )
    session.add(user)
    session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"OTP Landlord {n}", currency="KES")
    session.add(landlord)
    session.flush()
    session.add(LandlordSettings(landlord_id=landlord.id))
    session.commit()
    return landlord


def _make_tenant(session, landlord, *, phone=None, email=None, user_id=None):
    n = _uniq()
    prop = Property(landlord_id=landlord.id, name=f"P{n}", number_of_units=1, city="Nairobi")
    session.add(prop)
    session.flush()
    unit = Unit(property_id=prop.id, name=f"U{n}", rent_amount=10000)
    session.add(unit)
    session.flush()
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Otp", last_name=f"Tenant{n}",
        phone=phone or f"+25471{n}", email=email,
        user_id=user_id,
    )
    session.add(tenant)
    session.commit()
    return tenant


def _seed_otp(session, tenant, identifier, code, channel):
    OtpToken.query.filter_by(identifier=identifier, is_used=False).update({"is_used": True})
    otp = OtpToken(
        user_id=tenant.user_id, identifier=identifier,
        code=hashlib.sha256(code.encode()).hexdigest(),
        channel=channel,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
        is_used=False, attempts=0,
    )
    session.add(otp)
    session.commit()
    return otp


# ---------------------------------------------------------------------------

def test_otp_only_tenant_identity_is_namespaced_not_a_user_id(client, db_session):
    """The core regression: an OTP-only tenant (user_id=None) must get a
    namespaced identity that can never be read back as a User.id."""
    landlord = _make_landlord(db_session)
    tenant = _make_tenant(db_session, landlord, user_id=None)
    assert tenant.user_id is None

    code = "654321"
    _seed_otp(db_session, tenant, tenant.phone, code, OtpChannel.sms.value)

    resp = client.post("/api/otp/verify", json={"identifier": tenant.phone, "code": code})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["tenant_id"] == tenant.id
    assert body["role"] == "tenant"

    # The identity ("sub") must be "tenant:<id>", never a bare integer.
    with client.application.app_context():
        decoded = decode_token(body["access_token"])
    assert decoded["sub"] == f"tenant:{tenant.id}"
    assert not str(decoded["sub"]).isdigit()
    assert decoded["tenant_id"] == tenant.id


def test_tenant_token_never_resolves_to_a_colliding_user(client, db_session):
    """Reproduce the exact takeover: a User whose id equals the tenant's id must
    NOT be the account a tenant token loads. The loader returns a transient
    tenant sentinel (truthy, so no 401), never the persisted colliding User.

    Driven through the registered user_lookup_loader with a real verified
    token, so it exercises the exact code path an authenticated tenant request
    runs.
    """
    landlord = _make_landlord(db_session)
    tenant = _make_tenant(db_session, landlord, user_id=None)
    colliding = db.session.get(User, tenant.id)  # the account the bug leaked into

    code = "111222"
    _seed_otp(db_session, tenant, tenant.phone, code, OtpChannel.sms.value)
    verify = client.post("/api/otp/verify", json={"identifier": tenant.phone, "code": code})
    assert verify.status_code == 200
    token = verify.get_json()["access_token"]

    # The registered loader is what current_user resolves to on every tenant
    # request. Invoke it with this token's decoded claims.
    from flask_jwt_extended.internal_utils import get_jwt_manager
    with client.application.app_context():
        jwt_data = decode_token(token)
        loader = get_jwt_manager()._user_lookup_callback
        resolved = loader({}, jwt_data)

    # Truthy (no 401) but a transient tenant sentinel, never the colliding User.
    assert resolved is not None
    assert getattr(resolved, "_is_tenant_token", False) is True
    assert resolved.role == "tenant"
    assert resolved.email is None
    if colliding is not None:
        assert resolved.email != colliding.email, (
            f"tenant token leaked into User {colliding.email} "
            f"(collision with tenant.id={tenant.id})"
        )
        # And it must not be the same object the DB would hand back.
        assert resolved is not colliding


def test_tenant_with_linked_user_still_authenticates(client, db_session):
    """A tenant that DOES have a linked User still logs in and still gets a
    namespaced (non-User) identity — we never want a tenant to resolve to a
    User, linked or not, because the portal authorises off tenant_id."""
    landlord = _make_landlord(db_session)
    n = _uniq()
    tuser = User(
        email=f"otp-tenant{n}@test.sahilpay", phone=f"25472{n}0",
        password_hash=generate_password_hash("Testpass1"),
        role="tenant", is_verified=True,
    )
    db_session.add(tuser)
    db_session.flush()
    tenant = _make_tenant(db_session, landlord, user_id=tuser.id, email=tuser.email)

    code = "333444"
    _seed_otp(db_session, tenant, tenant.email, code, OtpChannel.email.value)
    resp = client.post("/api/otp/verify", json={"identifier": tenant.email, "code": code})
    assert resp.status_code == 200
    with client.application.app_context():
        decoded = decode_token(resp.get_json()["access_token"])
    assert decoded["sub"] == f"tenant:{tenant.id}"


def test_refresh_preserves_tenant_id_claim(client, db_session):
    """A tenant's session must survive an access-token refresh — the tenant_id
    claim (which tenant routes authorise off) must carry across."""
    landlord = _make_landlord(db_session)
    tenant = _make_tenant(db_session, landlord, user_id=None)
    code = "555666"
    _seed_otp(db_session, tenant, tenant.phone, code, OtpChannel.sms.value)
    verify = client.post("/api/otp/verify", json={"identifier": tenant.phone, "code": code})
    refresh_token = verify.get_json()["refresh_token"]

    resp = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
    assert resp.status_code == 200, resp.get_json()
    with client.application.app_context():
        decoded = decode_token(resp.get_json()["access_token"])
    assert decoded["tenant_id"] == tenant.id
    assert decoded["sub"] == f"tenant:{tenant.id}"
    assert decoded.get("role") == "tenant"
