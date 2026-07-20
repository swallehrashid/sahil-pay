"""
routes/admin_affiliate_routes.py — Admin Affiliate Program Management
Blueprint: admin_affiliate_bp  |  Prefix: /api/admin/affiliates

Approval queue, per-affiliate drill-down (rate/duration overrides, referral
list, commission/withdrawal history), the attribution grace-window tool,
the withdrawal-processing queue, and global program settings incl. the kill
switch. Reports/analytics live in admin_affiliate_report_routes.py.
See AFFILIATE_PROGRAM_SPEC.md §8.3 / §9.
"""

from __future__ import annotations

import io
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request, jsonify, abort, send_file
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    Affiliate, AffiliateReferral, AffiliateCommission, AffiliateWithdrawal,
    Landlord, UserRole, AffiliateStatus, WithdrawalStatus,
)
from services import affiliate_service as svc
from services.audit_service import record_audit

admin_affiliate_bp = Blueprint("admin_affiliate", __name__, url_prefix="/api/admin/affiliates")


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _admin_actor_id() -> int:
    return int(get_jwt_identity())


# ---------------------------------------------------------------------------
# GET /api/admin/affiliates
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("", methods=["GET"])
@jwt_required()
def list_affiliates():
    """
    List affiliates with earnings/referral aggregates. Filters: ?status=
    Header envelope includes total_outstanding_liability (sum of ALL
    affiliate balances — what Sahil currently owes across the program).
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate list + program-wide liability figure.}
    """
    _require_admin()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Affiliate.query
    if v := request.args.get("status"):
        query = query.filter(Affiliate.status == v)

    paginated = query.order_by(Affiliate.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

    items = []
    total_liability = db.session.query(
        db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)
    ).filter(AffiliateCommission.status == "confirmed").scalar()
    total_held = db.session.query(
        db.func.coalesce(db.func.sum(AffiliateWithdrawal.gross_amount), 0)
    ).filter(AffiliateWithdrawal.status.in_(["requested", "processing", "paid"])).scalar()

    for a in paginated.items:
        d = a.to_dict()
        d["balance"] = str(svc.get_balance(a.id))
        d["referral_count"] = AffiliateReferral.query.filter_by(affiliate_id=a.id).count()
        items.append(d)

    liability = (Decimal(str(total_liability)) - Decimal(str(total_held))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return jsonify({
        "affiliates":    items,
        "total":         paginated.total,
        "pages":         paginated.pages,
        "current_page":  paginated.page,
        "total_outstanding_liability": str(liability),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/affiliates/<id>
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>", methods=["GET"])
@jwt_required()
def get_affiliate(affiliate_id):
    """
    Full drill-down: profile, referrals (with landlord links), commissions,
    withdrawals.
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate detail.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    referrals = AffiliateReferral.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateReferral.created_at.desc()
    ).all()
    referral_rows = []
    for r in referrals:
        d = r.to_dict()
        d["landlord_company_name"] = r.landlord.company_name if r.landlord else None
        referral_rows.append(d)

    commissions = AffiliateCommission.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateCommission.created_at.desc()
    ).limit(100).all()
    withdrawals = AffiliateWithdrawal.query.filter_by(affiliate_id=affiliate_id).order_by(
        AffiliateWithdrawal.created_at.desc()
    ).all()

    return jsonify({
        "affiliate":   affiliate.to_dict(),
        "summary":     svc.get_affiliate_summary(affiliate),
        "referrals":   referral_rows,
        "commissions": [c.to_dict() for c in commissions],
        "withdrawals": [w.to_dict() for w in withdrawals],
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/<id>/approve
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>/approve", methods=["POST"])
@jwt_required()
def approve_affiliate(affiliate_id):
    """
    Body: { mpesa_number?: str, national_id?: str }
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate approved, referral code active.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    data = request.get_json(silent=True) or {}
    before = affiliate.to_dict()
    svc.approve_affiliate(affiliate, _admin_actor_id(),
                          mpesa_number=data.get("mpesa_number"), national_id=data.get("national_id"))
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="approve_affiliate", entity_type="affiliate", entity_id=affiliate.id,
        description=f"Admin approved affiliate #{affiliate.id} ({affiliate.full_name}).",
        before_data=before, after_data=affiliate.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Affiliate approved.", "affiliate": affiliate.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/<id>/reject
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>/reject", methods=["POST"])
@jwt_required()
def reject_affiliate(affiliate_id):
    """
    Body: { reason?: str }
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate rejected.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    data = request.get_json(silent=True) or {}
    before = affiliate.to_dict()
    svc.reject_affiliate(affiliate, _admin_actor_id(), reason=data.get("reason"))
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="reject_affiliate", entity_type="affiliate", entity_id=affiliate.id,
        description=f"Admin rejected affiliate #{affiliate.id} ({affiliate.full_name}).",
        before_data=before, after_data=affiliate.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Affiliate rejected.", "affiliate": affiliate.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/<id>/suspend
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>/suspend", methods=["POST"])
@jwt_required()
def suspend_affiliate(affiliate_id):
    """
    Existing referrals KEEP accruing; withdrawals are blocked (D15).
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate suspended.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    before = affiliate.to_dict()
    svc.suspend_affiliate(affiliate, _admin_actor_id())
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="suspend_affiliate", entity_type="affiliate", entity_id=affiliate.id,
        description=f"Admin suspended affiliate #{affiliate.id} ({affiliate.full_name}).",
        before_data=before, after_data=affiliate.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Affiliate suspended.", "affiliate": affiliate.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/<id>/reactivate
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>/reactivate", methods=["POST"])
@jwt_required()
def reactivate_affiliate(affiliate_id):
    """
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate reactivated.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    before = affiliate.to_dict()
    svc.reactivate_affiliate(affiliate)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="reactivate_affiliate", entity_type="affiliate", entity_id=affiliate.id,
        description=f"Admin reactivated affiliate #{affiliate.id} ({affiliate.full_name}).",
        before_data=before, after_data=affiliate.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Affiliate reactivated.", "affiliate": affiliate.to_dict()}), 200


# ---------------------------------------------------------------------------
# PATCH /api/admin/affiliates/<id>
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/<int:affiliate_id>", methods=["PATCH"])
@jwt_required()
def update_affiliate(affiliate_id):
    """
    Rate/months overrides + notes. Affects FUTURE referrals only (D5) —
    referrals already attributed keep their snapshot.
    Body: { commission_rate_override?, commission_months_override?, notes? }
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Affiliate updated.}
      404: {description: Affiliate not found.}
    """
    _require_admin()
    affiliate = db.session.get(Affiliate, affiliate_id)
    if not affiliate:
        return jsonify({"error": "Affiliate not found."}), 404

    data = request.get_json(silent=True) or {}
    before = affiliate.to_dict()

    if "commission_rate_override" in data:
        v = data["commission_rate_override"]
        affiliate.commission_rate_override = v if v in (None, "") else v
    if "commission_months_override" in data:
        v = data["commission_months_override"]
        affiliate.commission_months_override = v if v in (None, "") else int(v)
    if "notes" in data:
        affiliate.notes = data["notes"]

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="update_affiliate", entity_type="affiliate", entity_id=affiliate.id,
        description=f"Admin updated affiliate #{affiliate.id} terms (future referrals only).",
        before_data=before, after_data=affiliate.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Affiliate updated.", "affiliate": affiliate.to_dict()}), 200


# ---------------------------------------------------------------------------
# PATCH /api/admin/affiliates/referrals/<id>
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/referrals/<int:referral_id>", methods=["PATCH"])
@jwt_required()
def update_referral(referral_id):
    """
    Edit a single referral's snapshotted rate/months. Applies to FUTURE
    accruals only (D5). Extending months_total past a completed referral's
    current months_used automatically reopens it (E14/backtest S16).
    Body: { rate?, months_total? }
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Referral updated.}
      404: {description: Referral not found.}
    """
    _require_admin()
    referral = db.session.get(AffiliateReferral, referral_id)
    if not referral:
        return jsonify({"error": "Referral not found."}), 404

    data = request.get_json(silent=True) or {}
    before = referral.to_dict()

    if "rate" in data:
        referral.rate = data["rate"]
    if "months_total" in data:
        referral.months_total = int(data["months_total"])
        if referral.months_used < referral.months_total and referral.status == "completed":
            from models import ReferralStatus
            referral.status = ReferralStatus.active.value

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=referral.landlord_id,
        action="update_affiliate_referral", entity_type="affiliate_referral", entity_id=referral.id,
        description=f"Admin edited referral #{referral.id} terms (future accruals only).",
        before_data=before, after_data=referral.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Referral updated.", "referral": referral.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/referrals/<id>/void
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/referrals/<int:referral_id>/void", methods=["POST"])
@jwt_required()
def void_referral(referral_id):
    """
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Referral voided.}
      404: {description: Referral not found.}
    """
    _require_admin()
    referral = db.session.get(AffiliateReferral, referral_id)
    if not referral:
        return jsonify({"error": "Referral not found."}), 404

    before = referral.to_dict()
    svc.void_referral(referral)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=referral.landlord_id,
        action="void_affiliate_referral", entity_type="affiliate_referral", entity_id=referral.id,
        description=f"Admin voided referral #{referral.id}.",
        before_data=before, after_data=referral.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Referral voided.", "referral": referral.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/affiliates/attribute
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/attribute", methods=["POST"])
@jwt_required()
def attribute():
    """
    Grace-window tool: attach a landlord to an affiliate after the fact
    ("the landlord forgot to enter my code"). Allowed only within
    attribution_grace_days of the landlord's registration (E23 — 409 if the
    landlord already has a referral; void it first).
    Body: { landlord_id: int, affiliate_id: int }
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      201: {description: Referral attributed.}
      400: {description: Validation / self-referral / program inactive.}
      404: {description: Landlord or affiliate not found.}
      409: {description: Landlord already has a referral, or outside the grace window.}
    """
    _require_admin()
    data = request.get_json(silent=True) or {}
    landlord_id  = data.get("landlord_id")
    affiliate_id = data.get("affiliate_id")

    landlord  = db.session.get(Landlord, landlord_id) if landlord_id else None
    affiliate = db.session.get(Affiliate, affiliate_id) if affiliate_id else None
    if not landlord or not affiliate:
        return jsonify({"error": "Landlord or affiliate not found."}), 404

    from datetime import datetime, timedelta
    cfg = svc.get_program_config()
    if landlord.created_at and datetime.utcnow() - landlord.created_at > timedelta(days=cfg.attribution_grace_days):
        return jsonify({"error": f"Outside the {cfg.attribution_grace_days}-day attribution grace window."}), 409

    try:
        referral = svc.attribute_referral(landlord, affiliate, attributed_by="admin_grace")
    except svc.AttributionError as e:
        code = 409 if "already has" in str(e) else 400
        return jsonify({"error": str(e)}), code

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=landlord.id,
        action="admin_attribute_affiliate", entity_type="affiliate_referral", entity_id=referral.id,
        description=(
            f"Admin attributed landlord #{landlord.id} ({landlord.company_name}) "
            f"to affiliate #{affiliate.id} ({affiliate.full_name}) via the grace-window tool."
        ),
        after_data=referral.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Referral attributed.", "referral": referral.to_dict()}), 201


# ---------------------------------------------------------------------------
# GET/PATCH /api/admin/affiliates/config
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/config", methods=["GET"])
@jwt_required()
def get_config():
    """
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Program settings.}
    """
    _require_admin()
    return jsonify({"config": svc.get_program_config().to_dict()}), 200


@admin_affiliate_bp.route("/config", methods=["PATCH"])
@jwt_required()
def update_config():
    """
    Body: any subset of { default_commission_rate, default_commission_months,
    min_withdrawal, wht_rate, fee_type, fee_value, attribution_grace_days,
    is_program_active }. Changing these NEVER touches existing referrals or
    withdrawals (D5/E24) — only future ones.
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Config updated.}
    """
    _require_admin()
    cfg = svc.get_program_config()
    data = request.get_json(silent=True) or {}
    before = cfg.to_dict()

    fields = (
        "default_commission_rate", "default_commission_months", "min_withdrawal",
        "wht_rate", "fee_type", "fee_value", "attribution_grace_days", "is_program_active",
    )
    for field in fields:
        if field in data:
            setattr(cfg, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="update_affiliate_config", entity_type="affiliate", entity_id=cfg.id,
        description="Admin updated affiliate program settings.",
        before_data=before, after_data=cfg.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Config updated.", "config": cfg.to_dict()}), 200


# ---------------------------------------------------------------------------
# Withdrawal queue
# ---------------------------------------------------------------------------
@admin_affiliate_bp.route("/withdrawals", methods=["GET"])
@jwt_required()
def list_withdrawals():
    """
    Filters: ?status=requested|processing|paid|rejected
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated withdrawal queue.}
    """
    _require_admin()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = AffiliateWithdrawal.query
    if v := request.args.get("status"):
        query = query.filter(AffiliateWithdrawal.status == v)

    paginated = query.order_by(AffiliateWithdrawal.created_at.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for w in paginated.items:
        d = w.to_dict()
        d["affiliate_name"] = w.affiliate.full_name if w.affiliate else None
        d["affiliate_mpesa_number"] = w.affiliate.mpesa_number if w.affiliate else None
        items.append(d)

    return jsonify({
        "withdrawals":  items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


@admin_affiliate_bp.route("/withdrawals/<int:withdrawal_id>/process", methods=["POST"])
@jwt_required()
def process_withdrawal(withdrawal_id):
    """Move a requested withdrawal into 'processing' (admin is working on it).
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Withdrawal marked processing.}
      404: {description: Withdrawal not found.}
    """
    _require_admin()
    withdrawal = db.session.get(AffiliateWithdrawal, withdrawal_id)
    if not withdrawal:
        return jsonify({"error": "Withdrawal not found."}), 404
    if withdrawal.status != WithdrawalStatus.requested.value:
        return jsonify({"error": "Only a requested withdrawal can be moved to processing."}), 400

    before = withdrawal.to_dict()
    svc.process_withdrawal(withdrawal, _admin_actor_id())
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="process_affiliate_withdrawal", entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
        description=f"Admin began processing withdrawal #{withdrawal.id} (KES {withdrawal.gross_amount}).",
        before_data=before, after_data=withdrawal.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Withdrawal marked processing.", "withdrawal": withdrawal.to_dict()}), 200


@admin_affiliate_bp.route("/withdrawals/<int:withdrawal_id>/pay", methods=["POST"])
@jwt_required()
def pay_withdrawal(withdrawal_id):
    """
    Body: { mpesa_reference: str }
    Assigns a sequential receipt number and marks the withdrawal paid.
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Withdrawal paid, receipt generated.}
      400: {description: mpesa_reference missing, or already terminal.}
      404: {description: Withdrawal not found.}
    """
    _require_admin()
    withdrawal = db.session.get(AffiliateWithdrawal, withdrawal_id)
    if not withdrawal:
        return jsonify({"error": "Withdrawal not found."}), 404
    if withdrawal.status not in (WithdrawalStatus.requested.value, WithdrawalStatus.processing.value):
        return jsonify({"error": "This withdrawal is already in a terminal state."}), 400

    data = request.get_json(silent=True) or {}
    mpesa_reference = (data.get("mpesa_reference") or "").strip()
    if not mpesa_reference:
        return jsonify({"error": "mpesa_reference is required."}), 400

    before = withdrawal.to_dict()
    svc.pay_withdrawal(withdrawal, _admin_actor_id(), mpesa_reference)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="pay_affiliate_withdrawal", entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
        description=(
            f"Admin paid withdrawal #{withdrawal.id}: KES {withdrawal.net_amount} net "
            f"(receipt {withdrawal.receipt_number}, M-Pesa ref {mpesa_reference})."
        ),
        before_data=before, after_data=withdrawal.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Withdrawal paid.", "withdrawal": withdrawal.to_dict()}), 200


@admin_affiliate_bp.route("/withdrawals/<int:withdrawal_id>/reject", methods=["POST"])
@jwt_required()
def reject_withdrawal(withdrawal_id):
    """
    Body: { reason: str }
    Releases the held funds — they return to the affiliate's available balance.
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Withdrawal rejected.}
      400: {description: reason missing, or already terminal.}
      404: {description: Withdrawal not found.}
    """
    _require_admin()
    withdrawal = db.session.get(AffiliateWithdrawal, withdrawal_id)
    if not withdrawal:
        return jsonify({"error": "Withdrawal not found."}), 404
    if withdrawal.status not in (WithdrawalStatus.requested.value, WithdrawalStatus.processing.value):
        return jsonify({"error": "This withdrawal is already in a terminal state."}), 400

    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "reason is required."}), 400

    before = withdrawal.to_dict()
    svc.reject_withdrawal(withdrawal, _admin_actor_id(), reason)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=None,
        action="reject_affiliate_withdrawal", entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
        description=f"Admin rejected withdrawal #{withdrawal.id}: {reason}",
        before_data=before, after_data=withdrawal.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Withdrawal rejected.", "withdrawal": withdrawal.to_dict()}), 200


@admin_affiliate_bp.route("/withdrawals/<int:withdrawal_id>/receipt", methods=["GET"])
@jwt_required()
def withdrawal_receipt(withdrawal_id):
    """
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: PDF receipt.}
      404: {description: Withdrawal not found or not yet paid.}
    """
    _require_admin()
    withdrawal = db.session.get(AffiliateWithdrawal, withdrawal_id)
    if not withdrawal or withdrawal.status != WithdrawalStatus.paid.value:
        return jsonify({"error": "Receipt not available — withdrawal not found or not yet paid."}), 404

    from services.pdf_service import generate_affiliate_receipt_pdf
    pdf_bytes = generate_affiliate_receipt_pdf(withdrawal)

    return send_file(
        io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True,
        download_name=f"{withdrawal.receipt_number}.pdf",
    )


# ---------------------------------------------------------------------------
# Reports & analytics
# ---------------------------------------------------------------------------

_REPORT_BUILDERS = {
    "payouts":              "generate_payouts_report",
    "earnings":              "generate_earnings_report",
    "referral-performance":  "generate_referral_performance_report",
}

_MIME = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@admin_affiliate_bp.route("/reports/<string:report>", methods=["GET"])
@jwt_required()
def download_report(report):
    """
    Downloadable admin report. ?fmt=pdf|csv|xlsx (default pdf), plus
    ?start_date=&end_date= for the date-filterable reports.
    report is one of: payouts | earnings | referral-performance | summary
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Report file.}
      404: {description: Unknown report name.}
    """
    _require_admin()
    fmt = (request.args.get("fmt") or "pdf").lower()
    if fmt not in _MIME:
        return jsonify({"error": "fmt must be one of: pdf, csv, xlsx."}), 400
    start_date = request.args.get("start_date")
    end_date   = request.args.get("end_date")

    from services import affiliate_report_service as reports

    if report == "summary":
        file_bytes = reports.generate_program_summary_report(fmt)
    elif report in _REPORT_BUILDERS:
        builder = getattr(reports, _REPORT_BUILDERS[report])
        file_bytes = builder(fmt, start_date, end_date)
    else:
        return jsonify({"error": f"Unknown report '{report}'."}), 404

    ext = {"pdf": "pdf", "csv": "csv", "xlsx": "xlsx"}[fmt]
    return send_file(
        io.BytesIO(file_bytes), mimetype=_MIME[fmt], as_attachment=True,
        download_name=f"affiliate-{report}.{ext}",
    )


@admin_affiliate_bp.route("/analytics", methods=["GET"])
@jwt_required()
def analytics():
    """
    Chart-ready data for the admin affiliate analytics page: monthly accrual
    vs payouts/fees/WHT time series, top-10 leaderboard, signup->approval->
    referral->conversion funnel counts.
    ---
    tags: [Admin, Affiliate]
    security:
      - Bearer: []
    responses:
      200: {description: Analytics payload.}
    """
    _require_admin()
    from services import affiliate_report_service as reports
    return jsonify(reports.get_analytics()), 200
