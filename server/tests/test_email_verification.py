"""
Mandatory email verification, and the token collision that made it unsafe.

Verification existed but was switched off (ENFORCE_EMAIL_VERIFICATION defaulted
false outside production), covered only landlords / PMs / affiliates, and shared
one database column between two unrelated one-time tokens. Individually those
were untidy; together they meant turning enforcement on would have locked people
out, which is presumably why it stayed off.

What is pinned here:

  * the gate refuses an unverified account and says so in a way the frontend can
    act on (`needs_verification`), rather than looking like a bad password;
  * it covers team members, who receive a temp password by email and previously
    skipped verification entirely;
  * tenants are NEVER gated — they authenticate by phone OTP and many have no
    email address at all;
  * a password reset and a pending verification no longer destroy each other.
"""

import secrets
import uuid

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import User


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def enforced(app):
    """Enforcement on for the duration of one test, restored afterwards."""
    previous = app.config.get("ENFORCE_EMAIL_VERIFICATION")
    app.config["ENFORCE_EMAIL_VERIFICATION"] = True
    yield
    app.config["ENFORCE_EMAIL_VERIFICATION"] = previous


def _user(db_session, role="landlord", *, verified, password="Testpass1", **kw):
    n = _uniq()
    user = User(
        email=f"verify-{n}@test.sahilpay",
        phone=f"2547{n[:7]}",
        password_hash=generate_password_hash(password),
        role=role,
        is_verified=verified,
        is_active=True,
        **kw,
    )
    db_session.add(user)
    db_session.flush()
    return user


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_unverified_login_is_refused_with_an_actionable_code(client, db_session, enforced):
    """
    403 + needs_verification, NOT a generic 401. The frontend switches to a
    "resend link" panel on that flag; without it the person sees "invalid email
    or password" for a password that was in fact correct.
    """
    user = _user(db_session, verified=False)

    response = client.post("/api/auth/login",
                           json={"email": user.email, "password": "Testpass1"})

    assert response.status_code == 403
    assert response.get_json()["needs_verification"] is True


def test_verified_login_passes_the_gate(client, db_session, enforced):
    user = _user(db_session, verified=True)

    response = client.post("/api/auth/login",
                           json={"email": user.email, "password": "Testpass1"})

    assert response.status_code == 200


@pytest.mark.parametrize("role", ["landlord", "property_manager", "affiliate", "team_member"])
def test_every_password_role_is_gated(client, db_session, enforced, role):
    """Team members were the gap: created pre-verified, so never gated at all."""
    user = _user(db_session, role=role, verified=False)

    response = client.post("/api/auth/login",
                           json={"email": user.email, "password": "Testpass1"})

    assert response.status_code == 403
    assert response.get_json()["needs_verification"] is True


def test_tenants_are_never_gated_on_email(client, db_session, enforced):
    """
    Tenants sign in with a phone OTP, which already proves control of the
    number, and most have no email on file. Gating them would lock out the
    majority of the tenant base to prove something their login already proves.
    """
    tenant = _user(db_session, role="tenant", verified=False)

    response = client.post("/api/auth/login",
                           json={"email": tenant.email, "password": "Testpass1"})

    # Whatever else happens, it is not the verification gate turning them away.
    assert response.get_json().get("needs_verification") is not True


def test_gate_is_inert_when_enforcement_is_off(client, db_session, app):
    previous = app.config.get("ENFORCE_EMAIL_VERIFICATION")
    app.config["ENFORCE_EMAIL_VERIFICATION"] = False
    try:
        user = _user(db_session, verified=False)
        response = client.post("/api/auth/login",
                               json={"email": user.email, "password": "Testpass1"})
        assert response.status_code == 200
    finally:
        app.config["ENFORCE_EMAIL_VERIFICATION"] = previous


# ---------------------------------------------------------------------------
# Verifying
# ---------------------------------------------------------------------------

def test_clicking_the_link_verifies_and_unlocks_login(client, db_session, enforced):
    token = secrets.token_urlsafe(32)
    user = _user(db_session, verified=False, verification_token=token)
    db.session.commit()

    assert client.get(f"/api/auth/verify-email/{token}").status_code == 200
    assert client.post("/api/auth/login",
                       json={"email": user.email, "password": "Testpass1"}).status_code == 200


def test_a_link_cannot_be_replayed(client, db_session):
    token = secrets.token_urlsafe(32)
    _user(db_session, verified=False, verification_token=token)
    db.session.commit()

    assert client.get(f"/api/auth/verify-email/{token}").status_code == 200
    assert client.get(f"/api/auth/verify-email/{token}").status_code == 404


# ---------------------------------------------------------------------------
# The token collision
# ---------------------------------------------------------------------------
# Both flows used to write users.verification_token. Requesting a password reset
# therefore overwrote a pending verification link, and clicking a *reset* link on
# the verify-email endpoint marked the address verified AND consumed the token,
# so the reset that followed failed as "already used". Optional verification made
# that survivable; a mandatory gate turns it into a lockout.

def test_a_reset_request_does_not_consume_a_pending_verification(client, db_session):
    token = secrets.token_urlsafe(32)
    user = _user(db_session, verified=False, verification_token=token)
    db.session.commit()

    client.post("/api/auth/forgot-password", json={"email": user.email})
    db.session.refresh(user)

    assert user.verification_token == token, "reset request clobbered the verification link"
    assert user.password_reset_token
    assert user.password_reset_token != token

    # ...and the original link still works.
    assert client.get(f"/api/auth/verify-email/{token}").status_code == 200


def test_a_reset_token_cannot_be_used_to_verify_an_address(client, db_session):
    """
    The reset token must not be interchangeable with a verification token —
    otherwise anyone who can trigger a reset can satisfy the verification gate
    without ever reading the mailbox... and burns the real token doing it.
    """
    user = _user(db_session, verified=False)
    db.session.commit()

    client.post("/api/auth/forgot-password", json={"email": user.email})
    db.session.refresh(user)

    response = client.get(f"/api/auth/verify-email/{user.password_reset_token}")

    assert response.status_code == 404
    db.session.refresh(user)
    assert user.is_verified is False


def test_completing_a_reset_also_satisfies_verification(client, db_session, enforced):
    """
    Setting a new password from a link proves control of the mailbox just as
    well as clicking a verification link does. Without this, someone who reset
    their password would still be refused at the gate with nothing left to click.
    """
    user = _user(db_session, verified=False)
    db.session.commit()
    client.post("/api/auth/forgot-password", json={"email": user.email})
    db.session.refresh(user)

    response = client.post("/api/auth/reset-password",
                           json={"token": user.password_reset_token,
                                 "password": "BrandNewPass1"})
    assert response.status_code == 200

    db.session.refresh(user)
    assert user.is_verified is True
    assert user.password_reset_token is None
    assert client.post("/api/auth/login",
                       json={"email": user.email, "password": "BrandNewPass1"}).status_code == 200


# ---------------------------------------------------------------------------
# Team member invitations
# ---------------------------------------------------------------------------

def test_a_new_team_member_starts_unverified_with_a_token(client, db_session, app):
    """
    Team members used to be created is_verified=True, so the landlord typing a
    colleague's address wrong mailed working credentials to a stranger and left
    the real colleague locked out with no signal either way.
    """
    import routes.team_routes as team_routes
    from models import Landlord, LandlordSettings

    captured = {}
    original = team_routes.send_team_credentials_email.delay
    team_routes.send_team_credentials_email.delay = (
        lambda email, username, temp_password, **kw: captured.update(
            email=email, temp_password=temp_password, **kw)
    )
    try:
        n = _uniq()
        owner = _user(db_session, role="landlord", verified=True)
        landlord = Landlord(user_id=owner.id, company_name=f"TM {n}", currency="KES")
        db_session.add(landlord)
        db_session.flush()
        db_session.add(LandlordSettings(landlord_id=landlord.id))
        db_session.flush()
        db.session.commit()

        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(owner.id),
                                    additional_claims={"role": "landlord",
                                                       "landlord_id": landlord.id})

        member_email = f"tm-{n}@test.sahilpay"
        response = client.post(
            "/api/team/",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": member_email, "username": f"tm{n}", "preset": "caretaker"},
        )
        assert response.status_code == 201

        created = User.query.filter_by(email=member_email).first()
        assert created.is_verified is False
        assert created.verification_token
        # The invitation must carry the token, or the member has no way to verify.
        assert captured["verification_token"] == created.verification_token
    finally:
        team_routes.send_team_credentials_email.delay = original
