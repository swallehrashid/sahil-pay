"""
routes/admin_copilot_routes.py — Admin control of the Co-Pilot SMS forwarder
Blueprint: admin_copilot_bp  |  Prefix: /api/admin/copilot

Everything the admin needs to see and control across every landlord's
Co-pilot usage: the device fleet, the global ingest/audit log, the parser
template registry (the "onboard a new bank without touching code" workflow),
and APK release management. See COPILOT_PLATFORM_SPEC.md §7-8.

Every write here is recorded via record_audit(entity_type="copilot").
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    UserRole, Landlord, LandlordSettings, Payment, PaymentSource, PaymentStatus,
    CopilotDevice, CopilotDeviceStatus, CopilotMessage, CopilotParseStatus,
    CopilotMatchStatus, SmsParserTemplate, CopilotAppRelease,
)
from services.audit_service import record_audit
from services.copilot_service import test_template, retry_unparsed_message
from services.storage_service import upload_to_s3

admin_copilot_bp = Blueprint("admin_copilot", __name__, url_prefix="/api/admin/copilot")


def _require_admin():
    """Admin gate — delegates to the ONE shared implementation, which also
    enforces two-factor authentication (decorators.require_system_admin)."""
    from decorators import require_system_admin

    require_system_admin()

def _admin_id() -> int:
    return int(get_jwt_identity())


# ---------------------------------------------------------------------------
# GET /api/admin/copilot/overview
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/overview", methods=["GET"])
@jwt_required()
def overview():
    """Fleet-wide Co-pilot dashboard numbers. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Overview stats.}}"""
    _require_admin()

    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    cutoff_7d = now - timedelta(days=7)
    stale_cutoff = now - timedelta(hours=48)

    landlords_enabled = LandlordSettings.query.filter_by(copilot_enabled=True).count()

    devices_active = CopilotDevice.query.filter_by(status=CopilotDeviceStatus.active.value).count()
    devices_stale = (
        CopilotDevice.query
        .filter(CopilotDevice.status == CopilotDeviceStatus.active.value)
        .filter(db.or_(CopilotDevice.last_seen_at.is_(None), CopilotDevice.last_seen_at < stale_cutoff))
        .count()
    )

    messages_today = CopilotMessage.query.filter(CopilotMessage.created_at >= today_start).count()
    messages_7d = CopilotMessage.query.filter(CopilotMessage.created_at >= cutoff_7d).count()
    failed_7d = CopilotMessage.query.filter(
        CopilotMessage.created_at >= cutoff_7d,
        CopilotMessage.parse_status.in_([CopilotParseStatus.unparsed.value, CopilotParseStatus.rejected.value]),
    ).count()
    parse_failure_pct = round((failed_7d / messages_7d) * 100, 1) if messages_7d else 0.0

    unparsed_open = CopilotMessage.query.filter_by(parse_status=CopilotParseStatus.unparsed.value).count()
    unmatched_open = CopilotMessage.query.filter_by(match_status=CopilotMatchStatus.unmatched.value).count()

    payments_q = Payment.query.filter(
        Payment.source == PaymentSource.co_pilot.value,
        Payment.is_deleted.is_(False),
        Payment.created_at >= cutoff_7d,
    )
    payments_7d_count = payments_q.count()
    payments_7d_sum = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.source == PaymentSource.co_pilot.value,
        Payment.is_deleted.is_(False),
        Payment.created_at >= cutoff_7d,
    ).scalar()

    latest_messages = (
        CopilotMessage.query.order_by(CopilotMessage.created_at.desc()).limit(20).all()
    )

    return jsonify({
        "landlords_enabled": landlords_enabled,
        "devices_active":    devices_active,
        "devices_stale":     devices_stale,
        "messages_today":    messages_today,
        "messages_7d":       messages_7d,
        "parse_failure_pct": parse_failure_pct,
        "unparsed_open":     unparsed_open,
        "unmatched_open":    unmatched_open,
        "payments_7d": {
            "count": payments_7d_count,
            "sum":   round(float(payments_7d_sum), 2),
        },
        "latest_messages": [m.to_dict() for m in latest_messages],
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/copilot/devices
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/devices", methods=["GET"])
@jwt_required()
def list_devices():
    """
    All paired devices across every landlord.
    ?landlord_id=, ?status=, ?stale=true (no heartbeat in 48h)
    ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Device list.}}
    """
    _require_admin()
    query = CopilotDevice.query

    if v := request.args.get("landlord_id", type=int):
        query = query.filter(CopilotDevice.landlord_id == v)
    if v := request.args.get("status"):
        query = query.filter(CopilotDevice.status == v)
    if request.args.get("stale") == "true":
        stale_cutoff = datetime.utcnow() - timedelta(hours=48)
        query = query.filter(db.or_(CopilotDevice.last_seen_at.is_(None), CopilotDevice.last_seen_at < stale_cutoff))

    devices = query.order_by(CopilotDevice.last_seen_at.desc().nullslast()).all()
    landlord_names = {
        l.id: l.company_name
        for l in Landlord.query.filter(Landlord.id.in_([d.landlord_id for d in devices])).all()
    } if devices else {}

    items = []
    for d in devices:
        row = d.to_dict()
        row["landlord_name"] = landlord_names.get(d.landlord_id)
        items.append(row)

    return jsonify({"devices": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/copilot/devices/<id>/revoke
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/devices/<int:device_id>/revoke", methods=["POST"])
@jwt_required()
def revoke_device(device_id):
    """Admin kill switch for a single paired device. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Device revoked.}, 404: {description: Not found.}}"""
    _require_admin()
    device = db.session.get(CopilotDevice, device_id)
    if not device:
        return jsonify({"error": "Device not found."}), 404

    device.status = CopilotDeviceStatus.revoked.value
    device.revoked_at = datetime.utcnow()
    device.revoked_by = "admin"
    db.session.flush()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=device.landlord_id,
        action="admin_revoke_copilot_device", entity_type="copilot", entity_id=device.id,
        description=f"Admin revoked Co-pilot device \"{device.device_name}\".",
    )
    db.session.commit()
    return jsonify({"message": "Device revoked.", "device": device.to_dict()}), 200


# ---------------------------------------------------------------------------
# GET /api/admin/copilot/landlords
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/landlords", methods=["GET"])
@jwt_required()
def list_landlord_posture():
    """Per-landlord Co-pilot posture: enabled/auto_allocate/locked, device
    count, last message, open unmatched. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Landlord posture list.}}"""
    _require_admin()

    rows = (
        db.session.query(LandlordSettings, Landlord)
        .join(Landlord, Landlord.id == LandlordSettings.landlord_id)
        .filter(LandlordSettings.copilot_enabled.is_(True))
        .all()
    )

    items = []
    for ls, landlord in rows:
        device_count = CopilotDevice.query.filter_by(
            landlord_id=landlord.id, status=CopilotDeviceStatus.active.value
        ).count()
        last_msg = (
            CopilotMessage.query.filter_by(landlord_id=landlord.id)
            .order_by(CopilotMessage.created_at.desc()).first()
        )
        unmatched_open = CopilotMessage.query.filter_by(
            landlord_id=landlord.id, match_status=CopilotMatchStatus.unmatched.value
        ).count()
        items.append({
            "landlord_id":      landlord.id,
            "company_name":     landlord.company_name,
            "enabled":          ls.copilot_enabled,
            "auto_allocate":    ls.copilot_auto_allocate,
            "admin_locked":     ls.copilot_admin_locked,
            "consented_at":     ls.to_dict().get("copilot_consented_at"),
            "device_count":     device_count,
            "last_message_at":  last_msg.to_dict()["created_at"] if last_msg else None,
            "unmatched_open":   unmatched_open,
        })

    return jsonify({"landlords": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/copilot/landlords/<id>
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/landlords/<int:landlord_id>", methods=["PUT"])
@jwt_required()
def set_landlord_lock(landlord_id):
    """
    Platform-level Co-pilot kill switch for one landlord. Body: { admin_locked: bool }.
    Locking blocks ingestion immediately (services/copilot_service.py gate) —
    the landlord cannot re-enable Co-pilot while locked.
    ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Updated.}, 404: {description: Landlord not found.}}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord or not landlord.landlord_settings:
        return jsonify({"error": "Landlord not found."}), 404

    ls = landlord.landlord_settings
    data = request.get_json(silent=True) or {}
    if "admin_locked" not in data:
        return jsonify({"error": "admin_locked is required."}), 400

    before = ls.to_dict()
    ls.copilot_admin_locked = bool(data["admin_locked"])
    db.session.flush()

    verb = "locked" if ls.copilot_admin_locked else "unlocked"
    record_audit(
        actor_user_id=_admin_id(), landlord_id=landlord_id,
        action="admin_set_copilot_lock", entity_type="copilot", entity_id=landlord_id,
        description=f"Admin {verb} Co-pilot for {landlord.company_name}.",
        before_data=before, after_data=ls.to_dict(),
    )
    db.session.commit()
    return jsonify(ls.to_dict()), 200


# ---------------------------------------------------------------------------
# GET /api/admin/copilot/messages
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/messages", methods=["GET"])
@jwt_required()
def list_messages():
    """
    Global ingest log — the admin audit view (raw SMS text included).
    ?landlord_id=, ?sender_id=, ?parse_status=, ?match_status=,
    ?start_date=, ?end_date=, ?page=, ?per_page=
    ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Paginated ingest log.}}
    """
    _require_admin()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = CopilotMessage.query
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(CopilotMessage.landlord_id == v)
    if v := request.args.get("sender_id"):
        query = query.filter(db.func.upper(CopilotMessage.sender_id) == v.upper())
    if v := request.args.get("parse_status"):
        query = query.filter(CopilotMessage.parse_status == v)
    if v := request.args.get("match_status"):
        query = query.filter(CopilotMessage.match_status == v)
    if v := request.args.get("start_date"):
        query = query.filter(CopilotMessage.created_at >= v)
    if v := request.args.get("end_date"):
        query = query.filter(CopilotMessage.created_at <= v)

    paginated = query.order_by(CopilotMessage.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "messages":     [m.to_dict() for m in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET / POST /api/admin/copilot/templates
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    """List parser templates. ?sender_id=, ?is_active=. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Template list.}}"""
    _require_admin()
    query = SmsParserTemplate.query
    if v := request.args.get("sender_id"):
        query = query.filter(db.func.upper(SmsParserTemplate.sender_id) == v.upper())
    if v := request.args.get("is_active"):
        query = query.filter(SmsParserTemplate.is_active == (v == "true"))
    templates = query.order_by(SmsParserTemplate.sender_id.asc(), SmsParserTemplate.priority.asc()).all()
    return jsonify({"templates": [t.to_dict() for t in templates]}), 200


@admin_copilot_bp.route("/templates", methods=["POST"])
@jwt_required()
def create_template():
    """
    Create a parser template. Body: { name, sender_id, template_text,
    sample_text?, priority?, is_active? }. Validates + compiles template_text
    (and tests it against sample_text if given) before saving.
    ---
    tags: [Admin — Co-Pilot]
    responses: {201: {description: Template created.}, 400: {description: Invalid template.}}
    """
    _require_admin()
    from services.copilot_service import compile_template

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    sender_id = (data.get("sender_id") or "").strip().upper()
    template_text = (data.get("template_text") or "").strip()
    sample_text = (data.get("sample_text") or "").strip() or None

    if not name or not sender_id or not template_text:
        return jsonify({"error": "name, sender_id and template_text are required."}), 400

    try:
        compile_template(template_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if sample_text:
        result = test_template(template_text, sample_text)
        if not result["ok"]:
            return jsonify({"error": f"Template does not match its own sample: {result['error']}"}), 400

    template = SmsParserTemplate(
        name=name, sender_id=sender_id, template_text=template_text,
        sample_text=sample_text,
        is_active=bool(data.get("is_active", True)),
        priority=int(data.get("priority", 100)),
        created_by=_admin_id(),
    )
    db.session.add(template)
    db.session.flush()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="create_sms_parser_template", entity_type="copilot", entity_id=template.id,
        description=f"Parser template \"{name}\" created for sender {sender_id}.",
        after_data=template.to_dict(),
    )
    db.session.commit()
    return jsonify(template.to_dict()), 201


@admin_copilot_bp.route("/templates/<int:template_id>", methods=["PUT"])
@jwt_required()
def update_template(template_id):
    """Update a parser template — revalidates template_text. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Updated.}, 400: {description: Invalid template.}, 404: {description: Not found.}}"""
    _require_admin()
    from services.copilot_service import compile_template

    template = db.session.get(SmsParserTemplate, template_id)
    if not template:
        return jsonify({"error": "Template not found."}), 404

    data = request.get_json(silent=True) or {}
    before = template.to_dict()

    new_text = data.get("template_text", template.template_text)
    try:
        compile_template(new_text)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    sample_text = data.get("sample_text", template.sample_text)
    if sample_text:
        result = test_template(new_text, sample_text)
        if not result["ok"]:
            return jsonify({"error": f"Template does not match its own sample: {result['error']}"}), 400

    for field in ["name", "sender_id", "template_text", "sample_text", "is_active", "priority"]:
        if field in data:
            value = data[field]
            if field == "sender_id":
                value = (value or "").strip().upper()
            setattr(template, field, value)

    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="update_sms_parser_template", entity_type="copilot", entity_id=template.id,
        description=f"Parser template \"{template.name}\" updated.",
        before_data=before, after_data=template.to_dict(),
    )
    db.session.commit()
    return jsonify(template.to_dict()), 200


@admin_copilot_bp.route("/templates/<int:template_id>", methods=["DELETE"])
@jwt_required()
def delete_template(template_id):
    """
    Delete a parser template. If any CopilotMessage references it, it's
    soft-deleted (is_active=False) instead, to keep the ingest log's
    template_id links valid.
    ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Deleted or deactivated.}, 404: {description: Not found.}}
    """
    _require_admin()
    template = db.session.get(SmsParserTemplate, template_id)
    if not template:
        return jsonify({"error": "Template not found."}), 404

    in_use = CopilotMessage.query.filter_by(template_id=template.id).first() is not None
    name = template.name

    if in_use:
        template.is_active = False
        action, desc = "deactivate_sms_parser_template", f"Parser template \"{name}\" deactivated (in use by ingest history)."
    else:
        db.session.delete(template)
        action, desc = "delete_sms_parser_template", f"Parser template \"{name}\" deleted."

    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action=action, entity_type="copilot", entity_id=template_id,
        description=desc,
    )
    db.session.commit()
    return jsonify({"message": desc}), 200


@admin_copilot_bp.route("/templates/test", methods=["POST"])
@jwt_required()
def test_template_route():
    """Live test console: { template_text, sample_sms } -> extracted fields or error. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Test result.}}"""
    _require_admin()
    data = request.get_json(silent=True) or {}
    result = test_template(data.get("template_text") or "", data.get("sample_sms") or "")
    return jsonify(result), 200


# ---------------------------------------------------------------------------
# GET /api/admin/copilot/unparsed
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/unparsed", methods=["GET"])
@jwt_required()
def unparsed_queue():
    """Unparsed messages grouped by sender — "which bank needs a template?" ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Grouped unparsed queue.}}"""
    _require_admin()

    rows = (
        CopilotMessage.query
        .filter_by(parse_status=CopilotParseStatus.unparsed.value)
        .order_by(CopilotMessage.created_at.desc())
        .all()
    )
    grouped: dict[str, dict] = {}
    for m in rows:
        g = grouped.setdefault(m.sender_id, {"sender_id": m.sender_id, "count": 0, "examples": []})
        g["count"] += 1
        if len(g["examples"]) < 5:
            g["examples"].append(m.to_dict())

    return jsonify({"senders": sorted(grouped.values(), key=lambda g: -g["count"])}), 200


@admin_copilot_bp.route("/unparsed/<int:message_id>/retry", methods=["POST"])
@jwt_required()
def retry_one(message_id):
    """Re-run the pipeline on one unparsed/rejected/duplicate message after
    adding or fixing a template. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Retry result.}, 404: {description: Not found.}}"""
    _require_admin()
    message = db.session.get(CopilotMessage, message_id)
    if not message:
        return jsonify({"error": "Message not found."}), 404

    retry_unparsed_message(message)
    db.session.flush()
    record_audit(
        actor_user_id=_admin_id(), landlord_id=message.landlord_id,
        action="retry_copilot_message", entity_type="copilot", entity_id=message.id,
        description=f"Admin retried Co-pilot message #{message.id} — now {message.parse_status}.",
    )
    db.session.commit()
    return jsonify(message.to_dict()), 200


@admin_copilot_bp.route("/unparsed/retry-all", methods=["POST"])
@jwt_required()
def retry_all():
    """Drain the unparsed queue for one sender (or all senders). ?sender_id=. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Retry summary.}}"""
    _require_admin()
    sender_id = request.args.get("sender_id")

    query = CopilotMessage.query.filter_by(parse_status=CopilotParseStatus.unparsed.value)
    if sender_id:
        query = query.filter(db.func.upper(CopilotMessage.sender_id) == sender_id.upper())
    messages = query.all()

    now_parsed = 0
    for message in messages:
        try:
            retry_unparsed_message(message)
            db.session.commit()
            if message.parse_status != CopilotParseStatus.unparsed.value:
                now_parsed += 1
        except Exception:
            db.session.rollback()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="retry_all_copilot_messages", entity_type="copilot", entity_id=None,
        description=f"Admin retried {len(messages)} unparsed message(s)"
                    + (f" for sender {sender_id}" if sender_id else "")
                    + f" — {now_parsed} now resolved.",
    )
    db.session.commit()
    return jsonify({
        "retried": len(messages),
        "now_resolved": now_parsed,
        "still_unparsed": len(messages) - now_parsed,
    }), 200


# ---------------------------------------------------------------------------
# GET / POST /api/admin/copilot/releases
# ---------------------------------------------------------------------------
@admin_copilot_bp.route("/releases", methods=["GET"])
@jwt_required()
def list_releases():
    """List uploaded Co-pilot APK releases, newest version first. ---
    tags: [Admin — Co-Pilot]
    responses: {200: {description: Release list.}}"""
    _require_admin()
    releases = CopilotAppRelease.query.order_by(CopilotAppRelease.version_code.desc()).all()
    return jsonify({"releases": [r.to_dict() for r in releases]}), 200


@admin_copilot_bp.route("/releases", methods=["POST"])
@jwt_required()
def create_release():
    """
    Upload a new Co-pilot APK. Multipart form: file, version_name,
    version_code, release_notes?, is_latest?, min_supported_version_code?
    Setting is_latest clears the flag on every other release.
    ---
    tags: [Admin — Co-Pilot]
    responses: {201: {description: Release created.}, 400: {description: Invalid input.}}
    """
    _require_admin()
    file = request.files.get("file")
    data = request.form

    version_name = (data.get("version_name") or "").strip()
    try:
        version_code = int(data.get("version_code", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "version_code must be a whole number."}), 400

    if not file or not version_name:
        return jsonify({"error": "file and version_name are required."}), 400
    if CopilotAppRelease.query.filter_by(version_code=version_code).first():
        return jsonify({"error": f"version_code {version_code} already exists."}), 400

    apk_path = upload_to_s3(file, folder="copilot/apks", content_type="application/vnd.android.package-archive")

    is_latest = str(data.get("is_latest", "")).lower() == "true"
    if is_latest:
        CopilotAppRelease.query.filter_by(is_latest=True).update({"is_latest": False})

    min_supported = data.get("min_supported_version_code")
    release = CopilotAppRelease(
        version_name=version_name,
        version_code=version_code,
        apk_path=apk_path,
        release_notes=(data.get("release_notes") or "").strip() or None,
        is_latest=is_latest,
        min_supported_version_code=int(min_supported) if min_supported else None,
        uploaded_by=_admin_id(),
    )
    db.session.add(release)
    db.session.flush()

    record_audit(
        actor_user_id=_admin_id(), landlord_id=None,
        action="upload_copilot_release", entity_type="copilot", entity_id=release.id,
        description=f"Co-pilot APK v{version_name} (code {version_code}) uploaded"
                    + (" and marked latest." if is_latest else "."),
        after_data=release.to_dict(),
    )
    db.session.commit()
    return jsonify(release.to_dict()), 201
