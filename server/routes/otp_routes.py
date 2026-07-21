"""
routes/otp_routes.py — Passwordless OTP Login (Tenants Only)
Blueprint: otp_bp  |  Prefix: /api/otp

Three endpoints: request → verify → (optional) resend.
All three are rate-limited aggressively because they hit SMS/email
and guard access to tenant financial data.

OTP flow:
  1. Tenant submits phone or email.
  2. We look up the Tenant row by that identifier.
  3. Generate a 6-digit code, hash it, store in otp_tokens.
  4. Dispatch via FluxSMS (SMS) or SendGrid (email).
  5. Tenant submits code → validate expiry, attempt count, is_used.
  6. Issue tenant JWT on success.
"""

import hashlib
import random
import string
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, create_refresh_token

from extensions import db, limiter
from models import User, Tenant, Landlord, OtpToken, UserRole, OtpChannel
from services.sms_service  import send_otp_sms
from services.email_service import send_otp_email

otp_bp = Blueprint("otp", __name__, url_prefix="/api/otp")

OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS   = 5
OTP_LENGTH         = 6
OTP_COOLDOWN_SECONDS = 60   # minimum gap before resend


def _generate_code() -> str:
    return "".join(random.choices(string.digits, k=OTP_LENGTH))


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _find_tenant_by_identifier(identifier: str):
    """
    Look up Tenant by phone or email (case-insensitive for email). Excludes
    tenants that belong to a demo shadow landlord (DEMO_MODE_SPEC.md §3.4) —
    this is a public, unauthenticated lookup, so a demo tenant (even with its
    obviously-fake seeded phone/email) must never be reachable here.
    """
    identifier = identifier.strip()
    tenant = (
        Tenant.query
        .join(Landlord, Landlord.id == Tenant.landlord_id)
        .filter(Tenant.phone == identifier, Tenant.is_deleted.is_(False), Landlord.is_demo.is_(False))
        .first()
    )
    if not tenant:
        tenant = (
            Tenant.query
            .join(Landlord, Landlord.id == Tenant.landlord_id)
            .filter(Tenant.email == identifier.lower(), Tenant.is_deleted.is_(False), Landlord.is_demo.is_(False))
            .first()
        )
    return tenant


def _detect_channel(identifier: str) -> str:
    """Heuristic: if it contains @ it's email, otherwise treat as phone."""
    return OtpChannel.email.value if "@" in identifier else OtpChannel.sms.value


# ---------------------------------------------------------------------------
# POST /api/otp/request
# ---------------------------------------------------------------------------
@otp_bp.route("/request", methods=["POST"])
@limiter.limit("5 per minute; 30 per hour")
def request_otp():
    """
    Tenant submits their registered phone number or email address.
    A 6-digit OTP is generated, hashed, stored, and dispatched.
    ---
    tags: [OTP / Tenant Auth]
    parameters:
      - in: body
        schema:
          required: [identifier]
          properties:
            identifier:
              type: string
              description: Tenant's registered phone number or email address.
    responses:
      200:
        description: OTP sent (or silently ignored if identifier not found — no enumeration).
      429:
        description: Rate limit exceeded.
    """
    data       = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()

    if not identifier:
        return jsonify({"error": "identifier (phone or email) is required."}), 400

    tenant = _find_tenant_by_identifier(identifier)

    # Always respond 200 to prevent tenant enumeration
    if not tenant:
        return jsonify({"message": "If that identifier is registered, an OTP has been sent."}), 200

    channel = _detect_channel(identifier)

    # Invalidate any prior unused tokens for this identifier
    OtpToken.query.filter_by(identifier=identifier, is_used=False).update({"is_used": True})
    db.session.flush()

    code        = _generate_code()
    hashed_code = _hash_code(code)
    expires_at  = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    otp = OtpToken(
        user_id    = tenant.user_id,
        identifier = identifier,
        code       = hashed_code,
        channel    = channel,
        expires_at = expires_at,
        is_used    = False,
        attempts   = 0,
    )
    db.session.add(otp)
    db.session.commit()

    # Dispatch asynchronously via Celery
    if channel == OtpChannel.sms.value:
        send_otp_sms.delay(identifier, code, tenant.first_name)
    else:
        send_otp_email.delay(identifier, code, tenant.first_name)

    return jsonify({
        "message": "If that identifier is registered, an OTP has been sent.",
        "channel": channel,
        "expires_in_minutes": OTP_EXPIRY_MINUTES,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/otp/verify
# ---------------------------------------------------------------------------
@otp_bp.route("/verify", methods=["POST"])
@limiter.limit("10 per minute; 50 per hour")
def verify_otp():
    """
    Tenant submits the OTP code. On success, issues access + refresh tokens.
    Increments attempt counter on each wrong code.
    Marks token as is_used=True on success.
    ---
    tags: [OTP / Tenant Auth]
    parameters:
      - in: body
        schema:
          required: [identifier, code]
          properties:
            identifier: {type: string}
            code:       {type: string}
    responses:
      200: {description: OTP verified — tokens issued.}
      400: {description: Invalid or expired OTP.}
      429: {description: Too many attempts or rate limit.}
    """
    data       = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    code       = (data.get("code") or "").strip()

    if not identifier or not code:
        return jsonify({"error": "identifier and code are required."}), 400

    # Fetch the most recent unused, unexpired token for this identifier
    otp = (
        OtpToken.query
        .filter_by(identifier=identifier, is_used=False)
        .order_by(OtpToken.created_at.desc())
        .first()
    )

    if not otp:
        return jsonify({"error": "No active OTP found. Please request a new one."}), 400

    if datetime.utcnow() > otp.expires_at:
        otp.is_used = True
        db.session.commit()
        return jsonify({"error": "OTP has expired. Please request a new one."}), 400

    if otp.attempts >= OTP_MAX_ATTEMPTS:
        otp.is_used = True
        db.session.commit()
        return jsonify({"error": "Too many failed attempts. Please request a new OTP."}), 429

    # Verify hash
    if otp.code != _hash_code(code):
        otp.attempts += 1
        db.session.commit()
        remaining = OTP_MAX_ATTEMPTS - otp.attempts
        return jsonify({
            "error":     "Incorrect OTP.",
            "attempts_remaining": remaining,
        }), 400

    # ── Success ───────────────────────────────────────────────────────────────
    otp.is_used = True
    db.session.commit()

    tenant = _find_tenant_by_identifier(identifier)
    if not tenant:
        return jsonify({"error": "Tenant record not found."}), 404

    additional_claims = {
        "role":       UserRole.tenant.value,
        "tenant_id":  tenant.id,
        "landlord_id": tenant.landlord_id,
    }

    # SECURITY: the JWT identity ("sub") MUST be namespaced for tenants and
    # MUST NOT be a bare numeric id. It was previously
    # str(tenant.user_id or tenant.id): for an OTP-only tenant with no linked
    # User, that fell back to tenant.id — a small integer that user_lookup_loader
    # then resolved as a User.id, logging the tenant into whatever unrelated User
    # (often a landlord's team member) happened to share that id. Prefixing with
    # "tenant:" makes the identity non-numeric, so it can never collide with a
    # User.id, and user_lookup_loader returns None for it (correct — a tenant is
    # not a User; the portal authorises off the tenant_id claim, not current_user).
    identity = f"tenant:{tenant.id}"

    access_token  = create_access_token(
        identity=identity,
        additional_claims=additional_claims,
    )
    refresh_token = create_refresh_token(
        identity=identity,
        additional_claims=additional_claims,
    )

    return jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "role":          UserRole.tenant.value,
        "tenant_id":     tenant.id,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/otp/resend
# ---------------------------------------------------------------------------
@otp_bp.route("/resend", methods=["POST"])
@limiter.limit("3 per minute; 10 per hour")
def resend_otp():
    """
    Re-issue an OTP for the same identifier if the cooldown has passed.
    Invalidates the previous token and generates a fresh one.
    ---
    tags: [OTP / Tenant Auth]
    parameters:
      - in: body
        schema:
          required: [identifier]
          properties:
            identifier: {type: string}
    responses:
      200: {description: OTP resent or cooldown in effect.}
    """
    data       = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()

    if not identifier:
        return jsonify({"error": "identifier is required."}), 400

    tenant = _find_tenant_by_identifier(identifier)
    if not tenant:
        return jsonify({"message": "If that identifier is registered, an OTP has been sent."}), 200

    # Enforce cooldown: check the most recent token's created_at
    last_otp = (
        OtpToken.query
        .filter_by(identifier=identifier)
        .order_by(OtpToken.created_at.desc())
        .first()
    )

    if last_otp:
        seconds_since = (datetime.utcnow() - last_otp.created_at).total_seconds()
        if seconds_since < OTP_COOLDOWN_SECONDS:
            wait = int(OTP_COOLDOWN_SECONDS - seconds_since)
            return jsonify({
                "message": f"Please wait {wait} seconds before requesting another OTP."
            }), 429

    # Invalidate all prior unused tokens
    OtpToken.query.filter_by(identifier=identifier, is_used=False).update({"is_used": True})
    db.session.flush()

    channel     = _detect_channel(identifier)
    code        = _generate_code()
    hashed_code = _hash_code(code)
    expires_at  = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    otp = OtpToken(
        user_id    = tenant.user_id,
        identifier = identifier,
        code       = hashed_code,
        channel    = channel,
        expires_at = expires_at,
        is_used    = False,
        attempts   = 0,
    )
    db.session.add(otp)
    db.session.commit()

    if channel == OtpChannel.sms.value:
        send_otp_sms.delay(identifier, code, tenant.first_name)
    else:
        send_otp_email.delay(identifier, code, tenant.first_name)

    return jsonify({
        "message": "A new OTP has been sent.",
        "channel": channel,
        "expires_in_minutes": OTP_EXPIRY_MINUTES,
    }), 200