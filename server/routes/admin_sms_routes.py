"""
routes/admin_sms_routes.py — Admin SMS reselling: pricing, pool & analytics
Blueprint: admin_sms_bp  |  Prefix: /api/admin/sms

§9.3 — the admin controls the whole SMS reselling business here:
  * set the price per SMS for default users (shared SahilPay sender ID) and
    custom users (own connected sender ID), the fixed platform cost per SMS,
    and the master toggle allowing default users to send via the shared pool;
  * top up the shared SMS pool, sync it against the live FluxSMS balance, and
    view the top-up history;
  * connect or edit a landlord's own custom SMS sender on their behalf;
  * monitor everything — pool balance, who's buying/spending, revenue vs cost,
    gross margin, usage %, effective rate — via /overview;
  * generate & download the SMS analytics report through the same
    generate→preview→edit-columns→download engine as every other report.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, abort, Response
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import UserRole, SmsPricingConfig, SmsPoolTopUp, SmsLandlordCredit, Landlord, LandlordSettings
from services.audit_service import record_audit
from services.report_builder import document_to_json, parse_column_selection, render_document

admin_sms_bp = Blueprint("admin_sms", __name__, url_prefix="/api/admin/sms")


def _require_admin():
    """Admin gate — delegates to the ONE shared implementation, which also
    enforces two-factor authentication (decorators.require_system_admin)."""
    from decorators import require_system_admin

    require_system_admin()

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
# GET / PUT  /api/admin/sms/credit-ranges  — word→credit pricing tiers
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/credit-ranges", methods=["GET"])
@jwt_required()
def get_credit_ranges():
    """Return the admin-editable word→credit tiers (seeded on first use). ---
    tags: [Admin — SMS]
    responses: {200: {description: Credit ranges.}}"""
    _require_admin()
    from services.sms_billing import load_credit_ranges
    ranges = load_credit_ranges()
    db.session.commit()  # persist any first-use seeding
    return jsonify({"ranges": ranges}), 200


@admin_sms_bp.route("/credit-ranges", methods=["PUT"])
@jwt_required()
def update_credit_ranges():
    """
    Replace the whole set of word→credit tiers atomically. Body:
      { "ranges": [ { "min_words": int, "max_words": int|null, "credits": int }, ... ] }
    Validation: each min_words>=1, credits>=1, max_words>=min_words (or null for
    the single open-ended top tier), and NO overlaps between tiers.
    ---
    tags: [Admin — SMS]
    responses: {200: {description: Updated.}, 400: {description: Invalid ranges.}}
    """
    _require_admin()
    from models import SmsCreditRange

    data = request.get_json(silent=True) or {}
    items = data.get("ranges")
    if not isinstance(items, list) or not items:
        return jsonify({"error": "ranges must be a non-empty list."}), 400

    parsed = []
    open_ended = 0
    for it in items:
        try:
            mn = int(it["min_words"])
            cr = int(it["credits"])
            mx = it.get("max_words")
            mx = int(mx) if mx not in (None, "") else None
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "Each range needs integer min_words, credits, and max_words (or null)."}), 400
        if mn < 1 or cr < 1:
            return jsonify({"error": "min_words and credits must be at least 1."}), 400
        if mx is not None and mx < mn:
            return jsonify({"error": f"max_words ({mx}) cannot be less than min_words ({mn})."}), 400
        if mx is None:
            open_ended += 1
        parsed.append((mn, mx, cr))

    if open_ended > 1:
        return jsonify({"error": "Only one open-ended tier (no max) is allowed."}), 400

    # Overlap check — sort by min_words and ensure each starts after the prior ends.
    parsed.sort(key=lambda t: t[0])
    for i in range(1, len(parsed)):
        prev_mx = parsed[i - 1][1]
        if prev_mx is None or parsed[i][0] <= prev_mx:
            return jsonify({"error": "Ranges must not overlap and only the last tier may be open-ended."}), 400

    # Replace all rows.
    SmsCreditRange.query.delete()
    db.session.flush()
    for mn, mx, cr in parsed:
        db.session.add(SmsCreditRange(min_words=mn, max_words=mx, credits=cr))
    db.session.flush()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="update_sms_credit_ranges", entity_type="sms", entity_id=None,
        description=f"Updated SMS word→credit tiers ({len(parsed)} range(s)).",
        after_data={"ranges": [{"min_words": mn, "max_words": mx, "credits": cr} for mn, mx, cr in parsed]},
    )
    db.session.commit()
    return jsonify({"ranges": [r.to_dict() for r in SmsCreditRange.query.order_by(SmsCreditRange.min_words).all()]}), 200


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
# POST /api/admin/sms/landlords/<id>/credit — manually credit ONE landlord's
# SMS balance (used while automated M-Pesa billing is being finalised: the
# landlord pays the operator directly and the admin credits the equivalent
# number of SMS here). Signed so a mistake can be corrected with a negative
# value. Always writes an audited, reasoned ledger row.
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/landlords/<int:landlord_id>/credit", methods=["POST"])
@jwt_required()
def credit_landlord_sms(landlord_id):
    """
    Credit (or, with a negative value, correct) a single landlord's SMS balance.
    Body: { credits: int (non-zero), reason: str (required) }.
    ---
    tags: [Admin — SMS]
    responses:
      201: {description: Balance credited; ledger row returned.}
      400: {description: Invalid credits or missing reason.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    data = request.get_json(silent=True) or {}
    try:
        credits = int(data.get("credits", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "credits must be a whole number."}), 400
    if credits == 0:
        return jsonify({"error": "credits must be a non-zero whole number."}), 400

    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "A reason/reference for this credit is required."}), 400

    new_balance = (landlord.sms_balance or 0) + credits
    if new_balance < 0:
        return jsonify({
            "error": f"This would drop the balance below zero "
                     f"(current {landlord.sms_balance or 0}, change {credits})."
        }), 400

    landlord.sms_balance = new_balance
    row = SmsLandlordCredit(
        landlord_id=landlord.id,
        admin_user_id=_admin_id(),
        credits_added=credits,
        balance_after=new_balance,
        reason=reason,
    )
    db.session.add(row)
    db.session.flush()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=landlord.id,
        action="admin_credit_landlord_sms", entity_type="sms", entity_id=row.id,
        description=(
            f"ADMIN: {'Credited' if credits > 0 else 'Adjusted'} {credits:+,} SMS "
            f"for landlord {landlord.id} ({landlord.company_name}); new balance "
            f"{new_balance:,}. Reason: {reason}"
        ),
        after_data=row.to_dict(),
    )
    db.session.commit()
    return jsonify({"credit": row.to_dict(), "sms_balance": new_balance}), 201


@admin_sms_bp.route("/landlords/<int:landlord_id>/credit", methods=["GET"])
@jwt_required()
def landlord_credit_history(landlord_id):
    """One landlord's manual SMS-credit history (most recent first). ---
    tags: [Admin — SMS]
    responses: {200: {description: Credit history + current balance.}}"""
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404
    rows = (
        SmsLandlordCredit.query.filter_by(landlord_id=landlord_id)
        .order_by(SmsLandlordCredit.created_at.desc()).limit(100).all()
    )
    return jsonify({
        "credits": [r.to_dict() for r in rows],
        "sms_balance": landlord.sms_balance or 0,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/sms/pool/sync — reconcile pool_balance against the real
# FluxSMS platform balance.
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/pool/sync", methods=["POST"])
@jwt_required()
def sync_pool():
    """
    Sync SmsPricingConfig.pool_balance to the platform's real FluxSMS
    balance (a live /check_sms_balance call), recording the delta as a
    SmsPoolTopUp ledger entry so the sync is auditable like any other
    pool change.
    ---
    tags: [Admin — SMS]
    responses:
      200: {description: Pool synced.}
      502: {description: Could not reach the SMS provider.}
    """
    _require_admin()
    from services.sms_service import check_sms_balance

    live_balance = check_sms_balance()
    if live_balance is None:
        return jsonify({"error": "Could not reach the SMS provider to check the balance."}), 502

    cfg = SmsPricingConfig.get_singleton()
    before = cfg.pool_balance
    delta = live_balance - before
    cfg.pool_balance = live_balance

    topup = SmsPoolTopUp(
        admin_user_id=_admin_id(),
        credits_added=delta,
        balance_after=cfg.pool_balance,
        note="Synced from provider",
    )
    db.session.add(topup)
    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="sync_sms_pool", entity_type="sms", entity_id=topup.id,
        description=f"Synced SMS pool from provider ({before:,} → {cfg.pool_balance:,}).",
        after_data=topup.to_dict(),
    )
    db.session.commit()
    return jsonify({"topup": topup.to_dict(), "pool_balance": cfg.pool_balance}), 200


# ---------------------------------------------------------------------------
# GET / PUT  /api/admin/sms/landlords/<id>/provider — admin connects/edits a
# landlord's custom SMS sender on their behalf.
# ---------------------------------------------------------------------------
@admin_sms_bp.route("/landlords/<int:landlord_id>/provider", methods=["GET"])
@jwt_required()
def get_landlord_provider(landlord_id):
    """The landlord's current custom SMS provider config (api key masked). ---
    tags: [Admin — SMS]
    responses: {200: {description: Provider config.}, 404: {description: Landlord not found.}}"""
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404
    ls = landlord.landlord_settings
    return jsonify(ls.to_dict() if ls else {}), 200


@admin_sms_bp.route("/landlords/<int:landlord_id>/provider", methods=["PUT"])
@jwt_required()
def update_landlord_provider(landlord_id):
    """
    Connect or edit a landlord's custom SMS sender on their behalf. Body:
      { sms_api_key?, sms_sender_id?, connected?: bool }
    When connected=true is requested, the key is validated live against the
    SMS provider first (same check the landlord's own self-service connect
    performs) — rejected with 400 if the provider doesn't accept it.
    ---
    tags: [Admin — SMS]
    responses:
      200: {description: Updated.}
      400: {description: Invalid credentials.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    ls = landlord.landlord_settings
    if ls is None:
        ls = LandlordSettings(landlord_id=landlord_id)
        db.session.add(ls)
        db.session.flush()

    before = ls.to_dict()
    data = request.get_json(silent=True) or {}

    if "sms_api_key" in data:
        ls.sms_api_key = (data["sms_api_key"] or "").strip() or None
    if "sms_sender_id" in data:
        ls.sms_sender_id = (data["sms_sender_id"] or "").strip() or None

    if data.get("connected") is True:
        if not ls.sms_api_key or not ls.sms_sender_id:
            return jsonify({"error": "sms_api_key and sms_sender_id are required to connect."}), 400
        from services.sms_service import check_sms_balance
        if check_sms_balance(api_key=ls.sms_api_key) is None:
            return jsonify({"error": "The API key was rejected by the SMS provider."}), 400
        ls.sms_connected = True
    elif data.get("connected") is False:
        ls.sms_connected = False

    db.session.commit()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=landlord_id,
        action="admin_update_sms_provider", entity_type="settings", entity_id=landlord_id,
        description=f"Admin updated landlord #{landlord_id}'s SMS provider settings.",
        before_data=before, after_data=ls.to_dict(),
    )
    db.session.commit()
    return jsonify(ls.to_dict()), 200


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
