"""
routes/affiliate_routes.py — Affiliate Self-Registration + Portal
Blueprint: affiliate_bp  |  Prefix: /api/affiliate

Public:
  POST /register — self-signup, creates a PENDING affiliate (admin must
                    approve before the referral code activates).
Authenticated (role=affiliate):
  GET  /dashboard          — balance, projected earnings, referral counts.
  GET  /referrals          — landlords this affiliate referred (no PII leak).
  GET  /commissions        — commission ledger.
  GET  /withdrawals        — withdrawal history.
  POST /withdrawals        — request a withdrawal.
  GET  /withdrawals/<id>/receipt — KRA-compliant PDF receipt (own only).
  GET  /profile / PATCH /profile — payout details.

Login is unified — POST /api/auth/login already handles every role; this
blueprint only owns registration + the portal surface. See
AFFILIATE_PROGRAM_SPEC.md §8.1/§8.2.
"""

from __future__ import annotations

import io
import secrets

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash

from extensions import db, limiter
from models import User, Affiliate, AffiliateReferral, AffiliateCommission, AffiliateWithdrawal, UserRole, ReferralStatus
from decorators import require_affiliate, get_current_affiliate_id
from services import affiliate_service as svc
from services.audit_service import record_audit
from services.email_service import send_verification_email

affiliate_bp = Blueprint("affiliate", __name__, url_prefix="/api/affiliate")


# ---------------------------------------------------------------------------
# POST /api/affiliate/register
# ---------------------------------------------------------------------------
@affiliate_bp.route("/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    """
    Public affiliate self-signup. Creates a PENDING affiliate — the referral
    code only activates once an admin approves (POST
    /api/admin/affiliates/<id>/approve).
    Body: { full_name, email, password, phone }
    ---
    tags: [Affiliate]
    responses:
      201: {description: Affiliate account created, pending admin approval.}
      400: {description: Validation error or email already registered.}
      403: {description: The affiliate program is not currently active.}
    """
    cfg = svc.get_program_config()
    if not cfg.is_program_active:
        return jsonify({"error": "The affiliate program is not currently accepting new signups."}), 403

    data      = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    email     = (data.get("email") or "").strip().lower()
    password  = data.get("password", "")
    phone     = (data.get("phone") or "").strip()

    if not full_name or not email or not password or not phone:
        return jsonify({"error": "full_name, email, password, and phone are required."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "An account with this email already exists."}), 400

    verification_token = secrets.token_urlsafe(32)
    user = User(
        email=email, phone=phone, password_hash=generate_password_hash(password),
        role=UserRole.affiliate.value, is_verified=False, verification_token=verification_token,
    )
    db.session.add(user)
    db.session.flush()

    affiliate = svc.create_affiliate(user, full_name, phone)
    db.session.commit()

    send_verification_email.delay(email, verification_token)

    record_audit(
        actor_user_id=user.id,
        landlord_id=None,
        action="affiliate_register",
        entity_type="affiliate",
        entity_id=affiliate.id,
        description=f"New affiliate account created: {email} (pending approval).",
        after_data=affiliate.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message": "Account created. Please check your email to verify, then wait for admin approval.",
        "user_id": user.id,
    }), 201


# ---------------------------------------------------------------------------
# GET /api/affiliate/dashboard
# ---------------------------------------------------------------------------
@affiliate_bp.route("/dashboard", methods=["GET"])
@jwt_required()
@require_affiliate()
def dashboard():
    """
    Balance, lifetime earnings, projected monthly earnings, and referral
    counts (total / active-paying / completed / not-yet-paying).
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Dashboard summary.}
    """
    affiliate_id = get_current_affiliate_id()
    affiliate = db.session.get(Affiliate, affiliate_id)
    summary = svc.get_affiliate_summary(affiliate)
    return jsonify({"affiliate": affiliate.to_dict(), "summary": summary}), 200


# ---------------------------------------------------------------------------
# GET /api/affiliate/referrals
# ---------------------------------------------------------------------------
@affiliate_bp.route("/referrals", methods=["GET"])
@jwt_required()
@require_affiliate()
def list_referrals():
    """
    Landlords referred by this affiliate. Deliberately excludes landlord
    contact details (email/phone) — company name + package/status only
    (AFFILIATE_PROGRAM_SPEC.md §8.2 access-control note).
    Filters: ?page=, ?per_page=
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated referral list.}
    """
    affiliate_id = get_current_affiliate_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    paginated = AffiliateReferral.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateReferral.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for r in paginated.items:
        landlord = r.landlord
        sub = landlord.subscription if landlord else None
        d = r.to_dict()
        d["landlord_company_name"] = landlord.company_name if landlord else None

        # Once the commission window is over (completed/void), the affiliate no
        # longer earns from this landlord and must not see their current plan —
        # only referral history (months, earned so far) survives.
        window_active = r.status == ReferralStatus.active.value
        if window_active:
            d["package_name"] = landlord.package.name if landlord and landlord.package else None
            d["subscription_status"] = sub.status if sub else None
            d["monthly_value"] = str(sub.subscription_cost) if sub and sub.subscription_cost else None
        else:
            d["package_name"] = None
            d["subscription_status"] = None
            d["monthly_value"] = None

        earned = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
            AffiliateCommission.referral_id == r.id,
            AffiliateCommission.status == "confirmed",
        ).scalar()
        d["earned_so_far"] = str(earned)
        items.append(d)

    return jsonify({
        "referrals":    items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/affiliate/commissions
# ---------------------------------------------------------------------------
@affiliate_bp.route("/commissions", methods=["GET"])
@jwt_required()
@require_affiliate()
def list_commissions():
    """
    Commission ledger — one row per verified subscription payment that
    earned (or lost, on reversal) a commission.
    Filters: ?page=, ?per_page=
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated commission ledger.}
    """
    affiliate_id = get_current_affiliate_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    paginated = AffiliateCommission.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateCommission.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for c in paginated.items:
        d = c.to_dict()
        d["landlord_company_name"] = c.referral.landlord.company_name if c.referral and c.referral.landlord else None
        items.append(d)

    return jsonify({
        "commissions":  items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/affiliate/withdrawals
# ---------------------------------------------------------------------------
@affiliate_bp.route("/withdrawals", methods=["GET"])
@jwt_required()
@require_affiliate()
def list_withdrawals():
    """
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated withdrawal history + current balance.}
    """
    affiliate_id = get_current_affiliate_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    paginated = AffiliateWithdrawal.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateWithdrawal.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    # Withdrawal config the client needs to render a live gross->WHT->fee->net
    # preview WITHOUT hardcoding rates — never trust a client-computed figure,
    # but the client is allowed to preview what the server will compute.
    cfg = svc.get_program_config()

    return jsonify({
        "withdrawals":  [w.to_dict() for w in paginated.items],
        "balance":      str(svc.get_balance(affiliate_id)),
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
        "config": {
            "min_withdrawal": str(cfg.min_withdrawal),
            "wht_rate":       str(cfg.wht_rate),
            "fee_type":       cfg.fee_type,
            "fee_value":      str(cfg.fee_value),
        },
    }), 200


# ---------------------------------------------------------------------------
# POST /api/affiliate/withdrawals
# ---------------------------------------------------------------------------
@affiliate_bp.route("/withdrawals", methods=["POST"])
@jwt_required()
@require_affiliate()
def request_withdrawal():
    """
    Request a withdrawal. Guards (checked in this order — D13): another
    withdrawal already open, below minimum, exceeds available balance.
    Body: { amount: number }
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      201: {description: Withdrawal requested.}
      400: {description: Guard failed (see error message).}
    """
    affiliate_id = get_current_affiliate_id()
    affiliate = db.session.get(Affiliate, affiliate_id)
    data   = request.get_json(silent=True) or {}
    amount = data.get("amount")

    if amount is None:
        return jsonify({"error": "amount is required."}), 400

    try:
        withdrawal = svc.request_withdrawal(affiliate, amount)
    except svc.WithdrawalError as e:
        return jsonify({"error": str(e)}), 400

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=None,
        action="affiliate_request_withdrawal",
        entity_type="affiliate_withdrawal",
        entity_id=withdrawal.id,
        description=f"Affiliate #{affiliate_id} requested a withdrawal of KES {withdrawal.gross_amount}.",
        after_data=withdrawal.to_dict(),
    )
    db.session.commit()

    return jsonify({"message": "Withdrawal requested.", "withdrawal": withdrawal.to_dict()}), 201


# ---------------------------------------------------------------------------
# GET /api/affiliate/withdrawals/<id>/receipt
# ---------------------------------------------------------------------------
@affiliate_bp.route("/withdrawals/<int:withdrawal_id>/receipt", methods=["GET"])
@jwt_required()
@require_affiliate()
def withdrawal_receipt(withdrawal_id):
    """
    KRA-compliant PDF receipt for a PAID withdrawal — gross / WHT / platform
    fee / net breakdown, regenerated deterministically from the withdrawal's
    own snapshotted figures.
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: PDF receipt.}
      404: {description: Withdrawal not found or not yet paid.}
    """
    affiliate_id = get_current_affiliate_id()
    withdrawal = AffiliateWithdrawal.query.filter_by(id=withdrawal_id, affiliate_id=affiliate_id).first()
    if not withdrawal or withdrawal.status != "paid":
        return jsonify({"error": "Receipt not available — withdrawal not found or not yet paid."}), 404

    from services.pdf_service import generate_affiliate_receipt_pdf
    pdf_bytes = generate_affiliate_receipt_pdf(withdrawal)

    return send_file(
        io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
        download_name=f"{withdrawal.receipt_number}.pdf",
    )


# ---------------------------------------------------------------------------
# GET/PATCH /api/affiliate/profile
# ---------------------------------------------------------------------------
@affiliate_bp.route("/profile", methods=["GET"])
@jwt_required()
@require_affiliate()
def get_profile():
    """
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate profile.}
    """
    affiliate_id = get_current_affiliate_id()
    affiliate = db.session.get(Affiliate, affiliate_id)
    return jsonify({"affiliate": affiliate.to_dict()}), 200


@affiliate_bp.route("/profile", methods=["PATCH"])
@jwt_required()
@require_affiliate()
def update_profile():
    """
    Update payout details. Changing mpesa_number is audited (payout-fraud
    guard — AFFILIATE_PROGRAM_SPEC.md §11.1).
    Body: { full_name?, phone?, mpesa_number?, national_id?, kra_pin? }
    ---
    tags: [Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Profile updated.}
    """
    affiliate_id = get_current_affiliate_id()
    affiliate = db.session.get(Affiliate, affiliate_id)
    data = request.get_json(silent=True) or {}

    before = affiliate.to_dict()
    mpesa_changed = "mpesa_number" in data and data["mpesa_number"] != affiliate.mpesa_number

    for field in ("full_name", "phone", "mpesa_number", "national_id", "kra_pin"):
        if field in data:
            setattr(affiliate, field, (data[field] or "").strip() or None)

    db.session.commit()

    if mpesa_changed:
        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=None,
            action="affiliate_change_payout_number",
            entity_type="affiliate",
            entity_id=affiliate.id,
            description=f"Affiliate #{affiliate.id} changed their M-Pesa payout number.",
            before_data=before,
            after_data=affiliate.to_dict(),
        )
        db.session.commit()

    return jsonify({"message": "Profile updated.", "affiliate": affiliate.to_dict()}), 200
