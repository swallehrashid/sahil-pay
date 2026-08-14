"""
routes/twofa_routes.py — Two-Factor Authentication
Blueprint: twofa_bp  |  Prefix: /api/auth/2fa

Enrolment and management of the second factor. The login half lives in
auth_routes.py, which issues a short-lived pre-auth token when an account has
2FA on and exchanges it for real tokens here.

Flow:
  1. POST /setup    → a new secret + otpauth:// URI to scan. Not yet active.
  2. POST /enable   → user types the first code from their app; verified, 2FA
                      turns on, backup codes are returned ONCE.
  3. POST /verify   → at login: pre-auth token + code (or backup code) → real
                      access/refresh tokens.
  4. POST /disable  → password + current code required.
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token, get_jwt, get_jwt_identity,
    jwt_required,
)
from werkzeug.security import check_password_hash

from extensions import db, limiter
from models import User
from services import twofa_service as tfa
from services.audit_service import record_audit

twofa_bp = Blueprint("twofa", __name__, url_prefix="/api/auth/2fa")

# A pre-auth token proves ONLY "this password was correct". It is deliberately
# short-lived and is accepted at exactly one endpoint (/verify) — if it were
# accepted anywhere else, having the password would be enough again and the
# second factor would be decorative.
PRE_AUTH_CLAIM = "pre_2fa"
PRE_AUTH_MINUTES = 5


def issue_pre_auth_token(user) -> str:
    return create_access_token(
        identity=str(user.id),
        additional_claims={PRE_AUTH_CLAIM: True, "role": user.role},
        expires_delta=timedelta(minutes=PRE_AUTH_MINUTES),
    )


def _current_user():
    return db.session.get(User, int(get_jwt_identity()))


def _reject_pre_auth():
    """A half-authenticated token must not manage 2FA settings."""
    if get_jwt().get(PRE_AUTH_CLAIM):
        return jsonify({"error": "Complete two-factor sign-in first."}), 403
    return None


# ---------------------------------------------------------------------------
# POST /api/auth/2fa/setup
# ---------------------------------------------------------------------------
@twofa_bp.route("/setup", methods=["POST"])
@jwt_required()
@limiter.limit("10 per hour")
def setup():
    """
    Begin enrolment: mint a secret and return the otpauth:// URI to scan.

    The secret is stored (encrypted) but 2FA is NOT switched on until /enable
    proves the user's app is producing matching codes — otherwise a mis-scan
    would lock them out of their own account.
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200: {description: Provisioning URI + secret.}
    """
    if (blocked := _reject_pre_auth()):
        return blocked

    user = _current_user()
    if not user:
        return jsonify({"error": "User not found."}), 404
    if user.totp_enabled:
        return jsonify({"error": "Two-factor authentication is already on."}), 400

    secret = tfa.generate_secret()
    user.totp_secret = tfa.encrypt_secret(secret)
    user.totp_confirmed_at = None
    db.session.commit()

    label = user.email or user.phone or f"user-{user.id}"
    return jsonify({
        "provisioning_uri": tfa.provisioning_uri(secret, label),
        # Shown so someone whose camera can't scan can type it in by hand.
        "secret": secret,
        "issuer": tfa.ISSUER,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/2fa/enable
# ---------------------------------------------------------------------------
@twofa_bp.route("/enable", methods=["POST"])
@jwt_required()
@limiter.limit("10 per hour")
def enable():
    """
    Finish enrolment: verify the first code, switch 2FA on, return backup codes.
    Body: { code }
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200: {description: Enabled. Backup codes returned ONCE.}
      400: {description: Wrong code, or setup not started.}
    """
    if (blocked := _reject_pre_auth()):
        return blocked

    user = _current_user()
    if not user:
        return jsonify({"error": "User not found."}), 404

    secret = tfa.decrypt_secret(user.totp_secret)
    if not secret:
        return jsonify({"error": "Start setup first."}), 400

    if not tfa.verify_code(secret, (request.get_json(silent=True) or {}).get("code")):
        return jsonify({"error": "That code isn't right. Check your app and try again."}), 400

    codes, hashed = tfa.generate_backup_codes()
    user.totp_enabled = True
    user.totp_backup_codes = hashed
    user.totp_confirmed_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=user.id, landlord_id=None,
        action="enable_2fa", entity_type="user", entity_id=user.id,
        description="Two-factor authentication enabled.",
    )
    db.session.commit()

    return jsonify({
        "message": "Two-factor authentication is on.",
        # The ONLY time these are readable — only hashes are stored.
        "backup_codes": codes,
        "warning": "Save these now. Each works once, and they cannot be shown again.",
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/2fa/verify  — the login step
# ---------------------------------------------------------------------------
@twofa_bp.route("/verify", methods=["POST"])
@jwt_required()
@limiter.limit("10 per minute; 40 per hour")
def verify():
    """
    Exchange a pre-auth token plus a code for real tokens.
    Body: { code }  — a 6-digit TOTP code, or one backup code.
    ---
    tags: [Auth]
    responses:
      200: {description: Signed in.}
      401: {description: Wrong code.}
    """
    claims = get_jwt()
    if not claims.get(PRE_AUTH_CLAIM):
        return jsonify({"error": "This step is only for completing sign-in."}), 400

    user = _current_user()
    if not user or not user.is_active:
        return jsonify({"error": "Account not found or deactivated."}), 401

    code = (request.get_json(silent=True) or {}).get("code")
    secret = tfa.decrypt_secret(user.totp_secret)

    used_backup = False
    if not tfa.verify_code(secret, code):
        matched, remaining = tfa.consume_backup_code(user.totp_backup_codes, code)
        if not matched:
            return jsonify({"error": "That code isn't right."}), 401
        user.totp_backup_codes = remaining
        used_backup = True
        db.session.commit()

    # Rebuild the full claim set the ordinary login would have issued.
    from routes.auth_routes import build_login_claims

    additional_claims = build_login_claims(user)
    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=str(user.id), additional_claims=additional_claims)

    if used_backup:
        record_audit(
            actor_user_id=user.id, landlord_id=additional_claims.get("landlord_id"),
            action="login_backup_code", entity_type="user", entity_id=user.id,
            description=(
                "Signed in with a two-factor BACKUP code. "
                f"{tfa.backup_codes_remaining(user.totp_backup_codes)} remaining."
            ),
        )
        db.session.commit()

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "role": user.role,
        "used_backup_code": used_backup,
        "backup_codes_remaining": tfa.backup_codes_remaining(user.totp_backup_codes),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/2fa/disable
# ---------------------------------------------------------------------------
@twofa_bp.route("/disable", methods=["POST"])
@jwt_required()
@limiter.limit("10 per hour")
def disable():
    """
    Turn 2FA off. Requires the password AND a current code — a hijacked session
    must not be able to quietly remove the second factor.
    Body: { password, code }
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200: {description: Disabled.}
      400: {description: Wrong password or code.}
      403: {description: Required for this role.}
    """
    if (blocked := _reject_pre_auth()):
        return blocked

    user = _current_user()
    if not user:
        return jsonify({"error": "User not found."}), 404

    if tfa.is_required_for(user):
        return jsonify({
            "error": "Two-factor authentication is required for admin accounts "
                     "and cannot be switched off.",
        }), 403

    data = request.get_json(silent=True) or {}
    if not check_password_hash(user.password_hash or "", data.get("password") or ""):
        return jsonify({"error": "Password is incorrect."}), 400
    if not tfa.verify_code(tfa.decrypt_secret(user.totp_secret), data.get("code")):
        return jsonify({"error": "That code isn't right."}), 400

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_backup_codes = None
    user.totp_confirmed_at = None
    db.session.commit()

    record_audit(
        actor_user_id=user.id, landlord_id=None,
        action="disable_2fa", entity_type="user", entity_id=user.id,
        description="Two-factor authentication disabled.",
    )
    db.session.commit()

    return jsonify({"message": "Two-factor authentication is off."}), 200


# ---------------------------------------------------------------------------
# GET /api/auth/2fa/status
# ---------------------------------------------------------------------------
@twofa_bp.route("/status", methods=["GET"])
@jwt_required()
def status():
    """Whether 2FA is on, required, and how many backup codes are left."""
    if (blocked := _reject_pre_auth()):
        return blocked

    user = _current_user()
    if not user:
        return jsonify({"error": "User not found."}), 404

    return jsonify({
        "enabled":  user.totp_enabled,
        "required": tfa.is_required_for(user),
        "backup_codes_remaining": tfa.backup_codes_remaining(user.totp_backup_codes),
        "confirmed_at": user.totp_confirmed_at.isoformat() if user.totp_confirmed_at else None,
    }), 200
