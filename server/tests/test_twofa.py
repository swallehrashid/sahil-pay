"""
Phase 3.4 — two-factor authentication.

A stolen admin password must not be enough to take the platform. These tests
pin the parts that make that true: the secret is never stored in clear, a
password alone stops at a pre-auth token that opens nothing, backup codes work
exactly once, and an admin cannot reach the admin portal without enrolling.
"""

import uuid

import pyotp
import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import SystemAdmin, User
from services import twofa_service as tfa


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin(app, db_session):
    n = _uniq()
    user = User(
        email=f"tfa-admin-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", is_verified=True, is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(SystemAdmin(user_id=user.id, first_name="TFA", last_name="Admin"))
    db_session.commit()

    with app.app_context():
        token = create_access_token(
            identity=str(user.id), additional_claims={"role": "system_admin"}
        )
    return {"user": user, "token": token, "password": "Testpass1"}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# The secret at rest
# ---------------------------------------------------------------------------

def test_secret_is_encrypted_at_rest(app):
    """
    A leaked database dump must not hand over working second factors, so the
    stored value can never be the secret itself.
    """
    with app.app_context():
        secret = tfa.generate_secret()
        stored = tfa.encrypt_secret(secret)

        assert stored != secret, "the secret was stored in clear"
        assert secret not in stored
        assert tfa.decrypt_secret(stored) == secret


def test_undecryptable_secret_fails_closed(app):
    """A rotated key must lock 2FA users OUT, never let them straight in."""
    with app.app_context():
        assert tfa.decrypt_secret("not-a-real-fernet-token") is None
        assert tfa.verify_code(tfa.decrypt_secret("garbage"), "123456") is False


def test_codes_verify_and_reject(app):
    with app.app_context():
        secret = tfa.generate_secret()
        good = pyotp.TOTP(secret).now()

        assert tfa.verify_code(secret, good) is True
        assert tfa.verify_code(secret, "000000") is False
        assert tfa.verify_code(secret, None) is False
        assert tfa.verify_code(secret, "abcdef") is False
        assert tfa.verify_code(None, good) is False


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

def test_backup_codes_are_hashed_and_single_use(app):
    with app.app_context():
        codes, stored = tfa.generate_backup_codes()

        assert len(codes) == tfa.BACKUP_CODE_COUNT
        for code in codes:
            assert code not in stored, "a backup code was stored in clear"

        matched, remaining = tfa.consume_backup_code(stored, codes[0])
        assert matched is True
        assert tfa.backup_codes_remaining(remaining) == len(codes) - 1

        # The same code must not work twice — a code read over someone's
        # shoulder should not be a permanent second key.
        again, _ = tfa.consume_backup_code(remaining, codes[0])
        assert again is False


# ---------------------------------------------------------------------------
# Enrolment + login flow
# ---------------------------------------------------------------------------

def test_full_enrolment_and_login(client, app, admin):
    setup = client.post("/api/auth/2fa/setup", headers=_auth(admin["token"]))
    assert setup.status_code == 200
    secret = setup.get_json()["secret"]
    assert setup.get_json()["provisioning_uri"].startswith("otpauth://totp/")

    # Not active until a code proves the app is producing matching numbers.
    assert admin["user"].totp_enabled is False

    enable = client.post(
        "/api/auth/2fa/enable", headers=_auth(admin["token"]),
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert enable.status_code == 200, enable.get_data(as_text=True)
    backup_codes = enable.get_json()["backup_codes"]
    assert len(backup_codes) == tfa.BACKUP_CODE_COUNT

    db.session.refresh(admin["user"])
    assert admin["user"].totp_enabled is True

    # Password alone now stops at a pre-auth token.
    login = client.post("/api/auth/login", json={
        "email": admin["user"].email, "password": admin["password"],
    })
    assert login.status_code == 200
    body = login.get_json()
    assert body.get("requires_2fa") is True
    assert "access_token" not in body, "a password alone issued a real token"
    pre_auth = body["pre_auth_token"]

    # The pre-auth token opens nothing else.
    blocked = client.get("/api/admin/dashboard", headers=_auth(pre_auth))
    assert blocked.status_code in (403, 422), (
        "the pre-auth token reached an admin route — 2FA is decorative"
    )

    verified = client.post(
        "/api/auth/2fa/verify", headers=_auth(pre_auth),
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert verified.status_code == 200, verified.get_data(as_text=True)
    assert verified.get_json()["access_token"]


def test_wrong_code_is_refused(client, app, admin):
    setup = client.post("/api/auth/2fa/setup", headers=_auth(admin["token"]))
    secret = setup.get_json()["secret"]
    client.post("/api/auth/2fa/enable", headers=_auth(admin["token"]),
                json={"code": pyotp.TOTP(secret).now()})

    login = client.post("/api/auth/login", json={
        "email": admin["user"].email, "password": admin["password"],
    })
    pre_auth = login.get_json()["pre_auth_token"]

    bad = client.post("/api/auth/2fa/verify", headers=_auth(pre_auth),
                      json={"code": "000000"})
    assert bad.status_code == 401


def test_backup_code_signs_in_once(client, app, admin):
    setup = client.post("/api/auth/2fa/setup", headers=_auth(admin["token"]))
    secret = setup.get_json()["secret"]
    enable = client.post("/api/auth/2fa/enable", headers=_auth(admin["token"]),
                         json={"code": pyotp.TOTP(secret).now()})
    backup = enable.get_json()["backup_codes"][0]

    def sign_in_with(code):
        login = client.post("/api/auth/login", json={
            "email": admin["user"].email, "password": admin["password"],
        })
        return client.post("/api/auth/2fa/verify",
                           headers=_auth(login.get_json()["pre_auth_token"]),
                           json={"code": code})

    first = sign_in_with(backup)
    assert first.status_code == 200
    assert first.get_json()["used_backup_code"] is True

    # Losing a phone must not lose the account; a reused code must not work.
    second = sign_in_with(backup)
    assert second.status_code == 401, "a backup code worked twice"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_admin_portal_is_closed_until_enrolled(client, admin):
    """
    An admin can reach every landlord's money. Until the second factor is on,
    the admin portal stays shut — and says so in a way the UI can act on.
    """
    resp = client.get("/api/admin/dashboard", headers=_auth(admin["token"]))
    assert resp.status_code == 403
    assert (resp.get_json() or {}).get("code") == "2fa_required"


def test_admin_portal_opens_once_enrolled(client, admin):
    setup = client.post("/api/auth/2fa/setup", headers=_auth(admin["token"]))
    secret = setup.get_json()["secret"]
    client.post("/api/auth/2fa/enable", headers=_auth(admin["token"]),
                json={"code": pyotp.TOTP(secret).now()})

    resp = client.get("/api/admin/dashboard", headers=_auth(admin["token"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_admins_cannot_switch_2fa_off(client, admin):
    setup = client.post("/api/auth/2fa/setup", headers=_auth(admin["token"]))
    secret = setup.get_json()["secret"]
    client.post("/api/auth/2fa/enable", headers=_auth(admin["token"]),
                json={"code": pyotp.TOTP(secret).now()})

    resp = client.post("/api/auth/2fa/disable", headers=_auth(admin["token"]),
                       json={"password": admin["password"],
                             "code": pyotp.TOTP(secret).now()})
    assert resp.status_code == 403, "an admin disabled their own second factor"


def test_2fa_is_required_only_for_admins(app, db_session):
    n = _uniq()
    landlord_user = User(
        email=f"tfa-ll-{n}@test.sahilpay", role="landlord",
        password_hash=generate_password_hash("x"), is_active=True,
    )
    admin_user = User(
        email=f"tfa-adm2-{n}@test.sahilpay", role="system_admin",
        password_hash=generate_password_hash("x"), is_active=True,
    )
    assert tfa.is_required_for(admin_user) is True
    assert tfa.is_required_for(landlord_user) is False
