"""
routes/admin_sms_routes.py — Admin SMS reselling: pricing, pool & analytics
Blueprint: admin_sms_bp  |  Prefix: /api/admin/sms

§9.3 — the admin controls the whole SMS reselling business here:
  * set the price per SMS for default users (shared SahilPay sender ID) and
    custom users (own connected sender ID), the fixed platform cost per SMS,
    and the master toggle allowing default users to send via the shared pool;
  * top up the shared SMS pool and view the top-up history;
  * monitor everything — pool balance, who's buying/spending, revenue vs cost,
    gross margin, usage %, effective rate — via /overview;
  * generate & download the SMS analytics report through the same
    generate→preview→edit-columns→download engine as every other report.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, abort, Response
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import UserRole, SmsPricingConfig, SmsPoolTopUp
from services.audit_service import record_audit
from services.report_builder import document_to_json, parse_column_selection, render_document

admin_sms_bp = Blueprint("admin_sms", __name__, url_prefix="/api/admin/sms")


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _admin_id() -> int:
    return int(get_jwt_identity())


def _dec(value, field):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        abort(400, description=f"{field} must be a number.")
    if d < 0:
        abort(400, description=f"{field} cannot be negative.")
    return d


# ---------------------------------------------------------------------------
# GET / PUT  /api/admin/sms/pricing
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/pricing", methods=["GET"])
@jwt_required()
def get_pricing():
    """Return the SMS pricing config singleton. ---
    tags: [Admin — SMS]
    responses: {200: {description: SMS pricing config.}}"""
    _require_admin()
    return jsonify(SmsPricingConfig.get_singleton().to_dict()), 200


@admin_sms_bp.route("/pricing", methods=["PUT"])
@jwt_required()
def update_pricing():
    """
    Update SMS pricing / toggle. Body (all optional):
      { default_price_per_sms, custom_price_per_sms, platform_cost_per_sms,
        shared_sending_enabled }
    ---
    tags: [Admin — SMS]
    responses: {200: {description: Updated.}, 400: {description: Invalid value.}}
    """
    _require_admin()
    cfg = SmsPricingConfig.get_singleton()
    data = request.get_json(silent=True) or {}
    before = cfg.to_dict()

    if "default_price_per_sms" in data:
        cfg.default_price_per_sms = _dec(data["default_price_per_sms"], "default_price_per_sms")
    if "custom_price_per_sms" in data:
        cfg.custom_price_per_sms = _dec(data["custom_price_per_sms"], "custom_price_per_sms")
    if "platform_cost_per_sms" in data:
        cfg.platform_cost_per_sms = _dec(data["platform_cost_per_sms"], "platform_cost_per_sms")
    if "shared_sending_enabled" in data:
        cfg.shared_sending_enabled = bool(data["shared_sending_enabled"])

    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="update_sms_pricing", entity_type="sms", entity_id=cfg.id,
        description="Updated SMS reselling pricing/config.",
        before_data=before, after_data=cfg.to_dict(),
    )
    db.session.commit()
    return jsonify(cfg.to_dict()), 200


# ---------------------------------------------------------------------------
# POST /api/admin/sms/pool/top-up   |   GET /api/admin/sms/pool/history
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/pool/top-up", methods=["POST"])
@jwt_required()
def top_up_pool():
    """
    Add credits to the shared SMS pool. Body: { credits: int (>0), note?: str }.
    ---
    tags: [Admin — SMS]
    responses: {201: {description: Pool topped up.}, 400: {description: Invalid.}}
    """
    _require_admin()
    data = request.get_json(silent=True) or {}
    try:
        credits = int(data.get("credits", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "credits must be a whole number."}), 400
    if credits <= 0:
        return jsonify({"error": "credits must be greater than zero."}), 400

    cfg = SmsPricingConfig.get_singleton()
    cfg.pool_balance = (cfg.pool_balance or 0) + credits
    topup = SmsPoolTopUp(
        admin_user_id=_admin_id(),
        credits_added=credits,
        balance_after=cfg.pool_balance,
        note=(data.get("note") or "").strip() or None,
    )
    db.session.add(topup)
    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="top_up_sms_pool", entity_type="sms", entity_id=topup.id,
        description=f"Added {credits:,} SMS credits to the shared pool (balance {cfg.pool_balance:,}).",
        after_data=topup.to_dict(),
    )
    db.session.commit()
    return jsonify({"topup": topup.to_dict(), "pool_balance": cfg.pool_balance}), 201


@admin_sms_bp.route("/pool/history", methods=["GET"])
@jwt_required()
def pool_history():
    """Recent shared-pool top-ups (most recent first). ---
    tags: [Admin — SMS]
    responses: {200: {description: Top-up history.}}"""
    _require_admin()
    rows = SmsPoolTopUp.query.order_by(SmsPoolTopUp.created_at.desc()).limit(100).all()
    return jsonify({"topups": [t.to_dict() for t in rows]}), 200


# ---------------------------------------------------------------------------
# GET /api/admin/sms/overview   (monitoring dashboard payload)
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/overview", methods=["GET"])
@jwt_required()
def overview():
    """
    Platform-wide SMS monitoring: pool, revenue, cost, margin, per-landlord
    breakdown, and a monthly revenue-vs-cost series. ?months= (default 6).
    ---
    tags: [Admin — SMS]
    responses: {200: {description: SMS overview.}}
    """
    _require_admin()
    from services.sms_analytics_service import sms_overview
    months = request.args.get("months", 6, type=int)
    return jsonify(sms_overview(months=months)), 200


# ---------------------------------------------------------------------------
# GET /api/admin/sms/report  (preview JSON / PDF / Excel via report engine)
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/report", methods=["GET"])
@jwt_required()
def report():
    """
    The SMS reselling analytics report. ?format=json|pdf|excel (json=preview),
    ?columns=section.col,..., ?charts=revenue,cost,margin, ?months= (default 12).
    ---
    tags: [Admin — SMS]
    responses: {200: {description: SMS report (preview or file).}}
    """
    _require_admin()
    from services.sms_analytics_service import build_sms_report

    months = request.args.get("months", 12, type=int)
    doc = build_sms_report(months=months)

    fmt = (request.args.get("format") or "json").lower()
    selection = parse_column_selection(request.args.get("columns"))
    charts_raw = request.args.get("charts")
    chart_keys = [c.strip() for c in charts_raw.split(",") if c.strip()] if charts_raw else None

    if fmt == "json":
        return jsonify(document_to_json(doc, selection)), 200

    file_bytes = render_document(doc, fmt, selection, chart_keys)
    mime = "application/pdf" if fmt == "pdf" else \
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ext = "pdf" if fmt == "pdf" else "xlsx"
    return Response(
        file_bytes,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename=sms_analytics.{ext}"},
    ), 200
