"""
"Continue with Google" for landlords and affiliates.

Google's ID-token verification is stubbed (services.google_auth.verify_id_token)
so the tests exercise our account logic, not Google's network. Covers: new
landlord signup, new affiliate signup (pending), logging an EXISTING password
account in by verified email (auto-link), the 2FA gate still applying, and the
refusals (unverified Google email, feature off, tenant email).
"""

import itertools
import uuid

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import User, Landlord, Affiliate, UserRole, AffiliateStatus
import services.google_auth as google_auth

_counter = itertools.count()


def _uniq():
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def google_on(app):
    """Enable the feature and stub Google verification for the test."""
    app.config["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
    yield


def _stub_google(monkeypatch, *, email, sub=None, verified=True, name="Jane Doe"):
    info = {
        "sub": sub or f"g-{_uniq()}", "email": email.lower(),
        "email_verified": verified, "name": name,
        "given_name": name.split()[0], "family_name": name.split()[-1],
    }
    monkeypatch.setattr(google_auth, "verify_id_token", lambda credential, audience: info)
    return info


def test_new_landlord_signup_creates_verified_account(app, client, google_on, db_session, monkeypatch):
    email = f"glandlord{_uniq()}@gmail.com"
    _stub_google(monkeypatch, email=email, name="Asha Mwangi")

    with app.app_context():
        resp = client.post("/api/auth/google", json={"credential": "x", "intent": "landlord"})
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["created"] is True
        assert body["needs_profile_completion"] is True
        assert body["role"] == "landlord"
        assert body["access_token"]

        user = User.query.filter_by(email=email).first()
        assert user is not None
        assert user.is_verified is True            # Google verified the address
        assert user.password_hash is None          # no password yet — allowed
        assert user.google_sub
        assert user.landlord_profile is not None
        assert user.landlord_profile.company_name == "Asha Mwangi"


def test_existing_password_account_links_and_logs_in(app, client, google_on, db_session, monkeypatch):
    email = f"existing{_uniq()}@gmail.com"
    user = User(
        email=email, password_hash=generate_password_hash("Password1"),
        role=UserRole.landlord.value, is_verified=True,
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(Landlord(user_id=user.id, company_name="Prior Co", currency="KES"))
    db.session.commit()

    _stub_google(monkeypatch, email=email)
    with app.app_context():
        resp = client.post("/api/auth/google", json={"credential": "x"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["created"] is False
        assert body["access_token"]

        refreshed = db.session.get(User, user.id)
        assert refreshed.google_sub                 # linked
        assert refreshed.password_hash is not None  # password untouched


def test_new_affiliate_signup_is_pending(app, client, google_on, db_session, monkeypatch):
    email = f"gaff{_uniq()}@gmail.com"
    _stub_google(monkeypatch, email=email, name="Ken Omondi")
    with app.app_context():
        resp = client.post("/api/auth/google",
                           json={"credential": "x", "intent": "affiliate", "phone": "254700111222"})
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["created"] is True
        assert body["role"] == "affiliate"
        assert body["needs_profile_completion"] is False   # phone was supplied

        user = User.query.filter_by(email=email).first()
        aff = Affiliate.query.filter_by(user_id=user.id).first()
        assert aff is not None
        assert aff.status == AffiliateStatus.pending.value


def test_2fa_account_still_challenged(app, client, google_on, db_session, monkeypatch):
    email = f"g2fa{_uniq()}@gmail.com"
    user = User(
        email=email, password_hash=generate_password_hash("Password1"),
        role=UserRole.landlord.value, is_verified=True, totp_enabled=True,
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(Landlord(user_id=user.id, company_name="2FA Co", currency="KES"))
    db.session.commit()

    _stub_google(monkeypatch, email=email)
    with app.app_context():
        resp = client.post("/api/auth/google", json={"credential": "x"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("requires_2fa") is True
        assert body.get("pre_auth_token")
        assert "access_token" not in body


def test_unverified_google_email_refused(app, client, google_on, db_session, monkeypatch):
    _stub_google(monkeypatch, email=f"unv{_uniq()}@gmail.com", verified=False)
    with app.app_context():
        resp = client.post("/api/auth/google", json={"credential": "x"})
        assert resp.status_code == 400
        assert "not verified" in resp.get_json()["error"].lower()


def test_feature_off_returns_clear_error(app, client, db_session, monkeypatch):
    app.config["GOOGLE_CLIENT_ID"] = None
    with app.app_context():
        resp = client.post("/api/auth/google", json={"credential": "x"})
        assert resp.status_code == 400
        assert "not enabled" in resp.get_json()["error"].lower()


def test_complete_profile_sets_company_and_type(app, client, google_on, db_session, monkeypatch):
    email = f"complete{_uniq()}@gmail.com"
    _stub_google(monkeypatch, email=email, name="Temp Name")
    with app.app_context():
        signup = client.post("/api/auth/google", json={"credential": "x", "intent": "landlord"}).get_json()
        token = signup["access_token"]

        resp = client.post(
            "/api/auth/complete-profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"company_name": "Riverside Apartments", "account_type": "property_management"},
        )
        assert resp.status_code == 200

        user = User.query.filter_by(email=email).first()
        assert user.landlord_profile.company_name == "Riverside Apartments"
        assert user.landlord_profile.account_type == "property_management"
