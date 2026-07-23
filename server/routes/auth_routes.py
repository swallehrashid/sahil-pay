"""
routes/auth_routes.py — Password-based Authentication
Blueprint: auth_bp  |  Prefix: /api/auth

Covers registration, login, token refresh/logout, email verification,
password reset, and team-member activation.  Tenants use otp_routes.py.

Guards used here:
  - Flask-Limiter on every public endpoint (rate limits declared in create_app)
  - @jwt_required() on protected helpers (/me, /logout, /refresh)

Every account creation / password change writes an audit_logs row
(entity_type = 'account').
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt,
)
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
from datetime import datetime, timedelta

from extensions import db, limiter
from models import (
    User, Landlord, SystemAdmin, TeamMember, Tenant,
    Subscription, LandlordSettings, AutomationSettings,
    AuditLog, UserRole, SubscriptionStatus, BillingCycle,
    ImpersonationRequest, ImpersonationStatus,
)
from services.audit_service import record_audit
from services.category_service import seed_default_categories
from services.email_service import send_verification_email, send_password_reset_email
from services.trial_service import apply_global_trial
from utils import active_impersonation

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------
@auth_bp.route("/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    """
    Landlord / PM self-signup.
    Creates: users row + landlords profile + subscription (trial) +
             landlord_settings + automation_settings.
    Sends verification email.
    ---
    tags: [Auth]
    parameters:
      - in: body
        schema:
          required: [email, password, company_name]
          properties:
            email:        {type: string}
            password:     {type: string, minLength: 8}
            company_name: {type: string}
            phone:        {type: string}
            account_type: {type: string, enum: [gated_community, property_management, landlord]}
            referral_code: {type: string, description: "Optional affiliate referral code — silently ignored if invalid/expired."}
    responses:
      201: {description: Account created. Verification email sent.}
      400: {description: Validation error or email already registered.}
    """
    data = request.get_json(silent=True) or {}

    email        = (data.get("email") or "").strip().lower()
    password     = data.get("password", "")
    company_name = (data.get("company_name") or "").strip()
    phone        = (data.get("phone") or "").strip() or None
    account_type = data.get("account_type", "landlord")
    referral_code = data.get("referral_code")

    # ── Validation ────────────────────────────────────────────────────────────
    if not email or not password or not company_name:
        return jsonify({"error": "email, password, and company_name are required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 400

    verification_token = secrets.token_urlsafe(32)

    # ── Create user base record ───────────────────────────────────────────────
    user = User(
        email=email,
        phone=phone,
        password_hash=generate_password_hash(password),
        role=UserRole.landlord.value,
        is_verified=False,
        verification_token=verification_token,
    )
    db.session.add(user)
    db.session.flush()  # get user.id before referencing it

    # ── Create landlord profile ───────────────────────────────────────────────
    landlord = Landlord(
        user_id=user.id,
        company_name=company_name,
        account_type=account_type,
        currency="KES",
        timezone="Africa/Nairobi",
        sms_balance=0,
        is_on_trial=True,
    )
    db.session.add(landlord)
    db.session.flush()

    # ── Apply global trial config ─────────────────────────────────────────────
    apply_global_trial(landlord)

    # ── Bootstrap subscription skeleton ──────────────────────────────────────
    subscription = Subscription(
        landlord_id=landlord.id,
        unit_count=0,
        subscription_cost=0,
        status=SubscriptionStatus.trial.value,
        billing_cycle=BillingCycle.monthly.value,
        discount_rate=0,
        amount_due=0,
    )
    db.session.add(subscription)

    # ── Bootstrap settings ────────────────────────────────────────────────────
    db.session.add(LandlordSettings(landlord_id=landlord.id))
    db.session.add(AutomationSettings(landlord_id=landlord.id))

    # ── Seed the protected default charge categories (rent, lease, utilities…) ──
    seed_default_categories(landlord.id)

    # ── Affiliate attribution (best-effort — an invalid/expired/unknown code
    # must NEVER block registration itself; AFFILIATE_PROGRAM_SPEC.md E3) ──────
    from services.affiliate_service import attribute_from_code
    attribute_from_code(landlord, referral_code)

    db.session.commit()

    # ── Send verification email (Celery task) ─────────────────────────────────
    send_verification_email.delay(email, verification_token)

    record_audit(
        actor_user_id=user.id,
        landlord_id=landlord.id,
        action="register",
        entity_type="account",
        entity_id=user.id,
        description=f"New landlord account created: {email}",
    )
    db.session.commit()

    return jsonify({
        "message": "Account created successfully. Please check your email to verify.",
        "user_id": user.id,
    }), 201


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------
@auth_bp.route("/login", methods=["POST"])
@limiter.limit("20 per minute")
def login():
    """
    Email + password login for admin, landlord/PM, and team member roles.
    Returns access token + refresh token.
    ---
    tags: [Auth]
    parameters:
      - in: body
        schema:
          required: [email, password]
          properties:
            email:    {type: string}
            password: {type: string}
    responses:
      200: {description: Tokens issued.}
      401: {description: Invalid credentials.}
      403: {description: Account inactive or unverified.}
    """
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password", "")
    remember_me = bool(data.get("remember_me"))

    user = User.query.filter_by(email=email).first()

    if not user or not user.password_hash or \
            not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid email or password."}), 401

    if not user.is_active:
        return jsonify({"error": "This account has been deactivated. Contact support."}), 403

    # Landlords / PMs / affiliates must confirm their email first (when enforcement
    # is enabled). 403 + needs_verification lets the frontend offer a "resend
    # verification" action.
    if (
        current_app.config.get("ENFORCE_EMAIL_VERIFICATION")
        and user.role in (UserRole.landlord.value, UserRole.property_manager.value, UserRole.affiliate.value)
        and not user.is_verified
    ):
        return jsonify({
            "error": "Please verify your email address before logging in. Check your inbox for the verification link.",
            "needs_verification": True,
        }), 403

    # Team members must have activated their account
    if user.role == UserRole.team_member.value:
        tm = user.team_member_profile
        if not tm or not tm.is_active:
            return jsonify({"error": "Account not yet activated. Check your email."}), 403

    additional_claims = {"role": user.role}

    # Attach landlord_id to token for all non-admin roles
    if user.role in (UserRole.landlord.value, UserRole.property_manager.value):
        lp = user.landlord_profile
        if lp:
            additional_claims["landlord_id"] = lp.id
    elif user.role == UserRole.team_member.value:
        tm = user.team_member_profile
        if tm:
            additional_claims["landlord_id"]    = tm.landlord_id
            additional_claims["team_member_id"] = tm.id
    elif user.role == UserRole.affiliate.value:
        af = user.affiliate_profile
        if af:
            additional_claims["affiliate_id"] = af.id
            additional_claims["affiliate_status"] = af.status

    # "Keep me logged in (24h)": issue a 24-hour access token so the session
    # survives across a working day without re-login. Unchecked keeps the short
    # default expiry (config JWT_ACCESS_TOKEN_EXPIRES) so shared/public devices
    # time out quickly. The refresh token lifetime is unchanged.
    from datetime import timedelta
    access_expires = timedelta(hours=24) if remember_me else None
    access_token  = create_access_token(
        identity=str(user.id), additional_claims=additional_claims,
        expires_delta=access_expires,
    )
    refresh_token = create_refresh_token(identity=str(user.id), additional_claims=additional_claims)

    return jsonify({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "role":          user.role,
        "must_change_password": user.must_change_password,
        "remember_me":   remember_me,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------
@auth_bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    """
    Exchange a valid refresh token for a new access token.
    ---
    tags: [Auth]
    security:
      - BearerRefresh: []
    responses:
      200: {description: New access token.}
    """
    identity = get_jwt_identity()
    claims   = get_jwt()
    # tenant_id MUST be carried across a refresh: tenant routes authorise off
    # this claim, so dropping it would silently break a tenant's session after
    # their access token rotates (the identity is "tenant:<id>", not a User id).
    additional_claims = {k: v for k, v in claims.items()
                         if k in ("role", "landlord_id", "team_member_id",
                                  "tenant_id", "affiliate_id", "affiliate_status")}
    new_token = create_access_token(identity=identity, additional_claims=additional_claims)
    return jsonify({"access_token": new_token}), 200


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """
    Revoke / blacklist the current access token.
    The client must also discard both tokens locally.
    Token blacklisting requires a TokenBlocklist table and the
    JWT_ACCESS_TOKEN_EXPIRES check in create_app().
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200: {description: Logged out.}
    """
    from services.token_service import blocklist_token
    jti = get_jwt()["jti"]
    blocklist_token(jti)
    return jsonify({"message": "Successfully logged out."}), 200


# ---------------------------------------------------------------------------
# GET /api/auth/verify-email/<token>
# ---------------------------------------------------------------------------
@auth_bp.route("/verify-email/<string:token>", methods=["GET"])
@limiter.limit("30 per hour")
def verify_email(token):
    """
    Confirm the verification token sent at registration.
    Sets is_verified = True, clears verification_token.
    ---
    tags: [Auth]
    parameters:
      - in: path
        name: token
        required: true
        type: string
    responses:
      200: {description: Email verified.}
      404: {description: Token invalid or expired.}
    """
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        return jsonify({"error": "Verification link is invalid or has already been used."}), 404

    user.is_verified       = True
    user.verification_token = None
    db.session.commit()

    record_audit(
        actor_user_id=user.id,
        landlord_id=getattr(user.landlord_profile, "id", None),
        action="verify_email",
        entity_type="account",
        entity_id=user.id,
        description=f"Email verified for {user.email}",
    )
    db.session.commit()

    return jsonify({"message": "Email verified successfully. You can now log in."}), 200


# ---------------------------------------------------------------------------
# POST /api/auth/forgot-password
# ---------------------------------------------------------------------------
@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    """
    Generate a password-reset token and email it to the user.
    Always returns 200 to prevent user enumeration.
    ---
    tags: [Auth]
    parameters:
      - in: body
        schema:
          required: [email]
          properties:
            email: {type: string}
    responses:
      200: {description: If that email exists, a reset link was sent.}
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    user = User.query.filter_by(email=email).first()
    if user:
        reset_token = secrets.token_urlsafe(32)
        user.verification_token = reset_token          # reuse column for reset token
        db.session.commit()
        send_password_reset_email.delay(email, reset_token)

    return jsonify({
        "message": "If that email is registered, you will receive a reset link shortly."
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/resend-verification
# ---------------------------------------------------------------------------
@auth_bp.route("/resend-verification", methods=["POST"])
@limiter.limit("5 per hour")
def resend_verification():
    """
    Re-issue the email-verification link for an unverified account.
    Always returns 200 to prevent account enumeration.
    ---
    tags: [Auth]
    parameters:
      - in: body
        schema:
          required: [email]
          properties:
            email: {type: string}
    responses:
      200: {description: If that email exists and is unverified, a new link was sent.}
    """
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    user = User.query.filter_by(email=email).first()
    if user and not user.is_verified:
        token = secrets.token_urlsafe(32)
        user.verification_token = token
        db.session.commit()
        send_verification_email.delay(email, token)

    return jsonify({
        "message": "If that email is registered and unverified, a new verification link has been sent."
    }), 200


# ---------------------------------------------------------------------------
# POST /api/auth/reset-password
# ---------------------------------------------------------------------------
@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    """
    Consume the reset token and set a new password.
    ---
    tags: [Auth]
    parameters:
      - in: body
        schema:
          required: [token, password]
          properties:
            token:    {type: string}
            password: {type: string, minLength: 8}
    responses:
      200: {description: Password updated.}
      400: {description: Invalid token or weak password.}
    """
    data     = request.get_json(silent=True) or {}
    token    = data.get("token", "")
    password = data.get("password", "")

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    user = User.query.filter_by(verification_token=token).first()
    if not user:
        return jsonify({"error": "Reset token is invalid or has already been used."}), 400

    user.password_hash        = generate_password_hash(password)
    user.verification_token   = None
    user.must_change_password = False     # they've just set their own password
    db.session.commit()

    record_audit(
        actor_user_id=user.id,
        landlord_id=getattr(user.landlord_profile, "id", None),
        action="reset_password",
        entity_type="account",
        entity_id=user.id,
        description=f"Password reset for {user.email}",
    )
    db.session.commit()

    return jsonify({"message": "Password reset successfully. You can now log in."}), 200


# ---------------------------------------------------------------------------
# POST /api/auth/team-activate/<token>
# ---------------------------------------------------------------------------
@auth_bp.route("/team-activate/<string:token>", methods=["POST"])
@limiter.limit("20 per hour")
def team_activate(token):
    """
    Team member sets their password using the activation token from their email.
    Sets TeamMember.is_active = True, clears activation_token on the team member row,
    sets is_verified = True on the user row.
    ---
    tags: [Auth]
    parameters:
      - in: path
        name: token
        required: true
        type: string
      - in: body
        schema:
          required: [password]
          properties:
            password: {type: string, minLength: 8}
    responses:
      200: {description: Account activated.}
      400: {description: Weak password.}
      404: {description: Invalid activation token.}
    """
    data     = request.get_json(silent=True) or {}
    password = data.get("password", "")

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    tm = TeamMember.query.filter_by(activation_token=token).first()
    if not tm:
        return jsonify({"error": "Activation link is invalid or has already been used."}), 404

    user = tm.user
    user.password_hash  = generate_password_hash(password)
    user.is_verified    = True
    tm.is_active        = True
    tm.activation_token = None
    db.session.commit()

    record_audit(
        actor_user_id=user.id,
        landlord_id=tm.landlord_id,
        action="activate_team_member",
        entity_type="team_member",
        entity_id=tm.id,
        description=f"Team member {tm.username} activated their account.",
    )

    if tm.landlord and tm.landlord.user_id:
        from services.notification_service import notify
        notify(
            recipient_user_id=tm.landlord.user_id,
            category="team_member_activated",
            template_key="team_member_activated",
            template_kwargs={"member_name": f"{tm.first_name or ''} {tm.last_name or ''}".strip() or tm.username},
            landlord_id=tm.landlord_id,
            link="/landlord/settings/team",
            entity_type="team_member",
            entity_id=tm.id,
        )

    db.session.commit()

    return jsonify({"message": "Account activated. You can now log in."}), 200


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    """
    Returns the current user's base record plus their role profile.
    Used by RTK Query on every app load to hydrate the session.
    ---
    tags: [Auth]
    security:
      - Bearer: []
    responses:
      200: {description: Current user + profile.}
      404: {description: User not found.}
    """
    user_id = get_jwt_identity()

    # Tenant tokens carry a namespaced identity ("tenant:<id>", see
    # otp_routes.py) — a tenant is NOT a User row, so int(user_id) here would
    # raise ValueError -> 500, the AuthProvider would treat that as isError and
    # wipe the token, and the tenant would be bounced straight back to the login
    # screen (the "it just loads / refreshes" symptom). Resolve the tenant
    # directly and hand back a flat record the frontend hydrates exactly like a
    # User: it MUST carry role="tenant" so ProtectedRoutes admits the tenant
    # portal, and tenant_id so the portal's own queries can scope themselves.
    identity_str = str(user_id) if user_id is not None else ""
    if identity_str.startswith("tenant:"):
        tid = identity_str.split(":", 1)[1]
        tenant = (
            db.session.get(Tenant, int(tid))
            if tid.isdigit() else None
        )
        if not tenant or tenant.is_deleted:
            return jsonify({"error": "Tenant not found."}), 404
        payload = tenant.to_dict()
        payload["role"] = UserRole.tenant.value
        payload["tenant_id"] = tenant.id
        payload["name"] = f"{tenant.first_name} {tenant.last_name}".strip()
        return jsonify(payload), 200

    user = db.session.get(User, int(user_id)) if identity_str.isdigit() else None
    if not user:
        return jsonify({"error": "User not found."}), 404

    payload = user.to_dict()

    if user.role in (UserRole.landlord.value, UserRole.property_manager.value):
        lp = user.landlord_profile
        if lp:
            payload["profile"] = lp.to_dict()
            # Drives the landlord-side ImpersonationBanner — "is someone currently
            # able to act as me right now" (any granted, non-expired grant), not
            # merely "is the admin's current request using it".
            active_grant = ImpersonationRequest.query.filter_by(
                landlord_id=lp.id, status=ImpersonationStatus.granted.value,
            ).filter(ImpersonationRequest.expires_at > datetime.utcnow()).first()
            if active_grant:
                payload["impersonating"] = {
                    "admin_email": active_grant.admin_user.email if active_grant.admin_user else None,
                    "since": active_grant.granted_at.isoformat() if active_grant.granted_at else None,
                }
    elif user.role == UserRole.system_admin.value:
        ap = user.admin_profile
        if ap:
            payload["profile"] = ap.to_dict()
        # Drives the admin-side "you are operating X's account" banner — only set
        # when THIS request actually carried a valid X-Impersonate-Landlord header
        # against a granted, non-expired request (same check every landlord-scoped
        # route relies on via current_landlord_id()).
        imp = active_impersonation()
        if imp:
            payload["impersonating"] = {
                "landlord_id": imp.landlord_id,
                "company_name": imp.landlord.company_name if imp.landlord else None,
            }
    elif user.role == UserRole.team_member.value:
        tm = user.team_member_profile
        if tm:
            payload["profile"] = tm.to_dict()
            # The frontend's permission matrix (can()/buildVisibleNav) reads a
            # { module: {can_view, can_edit} } map plus property scope. Ship it
            # here so the session hydrates fully gated — without this a team
            # member hydrates with permissions=null, which the client treats as
            # "unrestricted" and exposes every module.
            payload["permissions"] = {
                p.module: {"can_view": p.can_view, "can_edit": p.can_edit}
                for p in tm.permissions
            }
            payload["property_access"] = {
                "all": tm.property_access_all,
                "propertyIds": [pa.property_id for pa in tm.property_accesses],
            }
    elif user.role == UserRole.affiliate.value:
        af = user.affiliate_profile
        if af:
            payload["profile"] = af.to_dict()

    return jsonify(payload), 200