"""
routes/settings_routes.py — Settings Sub-pages
Blueprint: settings_bp  |  Prefix: /api/settings

Consolidates §4.14 (general), §4.15 (automation), §4.16 (alerts),
§4.17 (account / profile), and backup generation/listing.

Covers:
  /general      — company info, logo, currency, timezone, M-Pesa config
  /automation   — Celery-Beat-read toggles (AutomationSettings)
  /alerts       — per-type AlertSetting rows (upsert semantics)
  /account      — user profile, email, signature, password change
  /account/agent-code — generate or regenerate the co-pilot agent code
  /backup       — POST (generate) + GET (list)
"""

import secrets

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import (
    Landlord, User, LandlordSettings, AutomationSettings,
    AlertSetting, Backup, BackupScopeType, BackupFormat,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service    import record_audit
from services.storage_service  import upload_to_s3

settings_bp = Blueprint("settings", __name__, url_prefix="/api/settings")


# ---------------------------------------------------------------------------
# GET / PUT /api/settings/general
# ---------------------------------------------------------------------------
@settings_bp.route("/general", methods=["GET", "PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def general_settings():
    """
    GET: Return the landlord's general settings (company info, M-Pesa, etc.).
    PUT: Update one or more fields. Logo/signature accept file uploads
         when Content-Type is multipart/form-data.

    Writable fields:
      company_name, abbreviated_name, company_address, invoice_title,
      currency, timezone, account_type,
      mpesa_type, mpesa_number, default_account_number,
      logo (file), signature (file).

    LandlordSettings writable fields:
      sms_enabled, whatsapp_enabled, email_enabled, low_sms_balance_threshold.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Settings returned or updated.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    if request.method == "GET":
        payload = landlord.to_dict()
        settings = landlord.landlord_settings
        payload["channel_settings"] = settings.to_dict() if settings else {}
        return jsonify(payload), 200

    # ── PUT ──────────────────────────────────────────────────────────────────
    # Require edit permission for mutations
    from decorators import _check_permission
    _check_permission("settings", "edit")

    before = landlord.to_dict()

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()
        # Handle logo and signature file uploads
        if "logo" in request.files:
            landlord.logo_url = upload_to_s3(
                request.files["logo"], folder=f"logos/{landlord_id}"
            )
        if "signature" in request.files:
            landlord.signature_url = upload_to_s3(
                request.files["signature"], folder=f"signatures/{landlord_id}"
            )

    landlord_fields = [
        "company_name", "abbreviated_name", "company_address", "invoice_title",
        "currency", "timezone", "account_type",
        "mpesa_type", "mpesa_number", "default_account_number",
        "payment_instructions", "allocation_priority",
    ]
    for field in landlord_fields:
        if field in data:
            setattr(landlord, field, data[field])

    # Update channel settings (LandlordSettings)
    ls = landlord.landlord_settings
    if ls:
        for field in ["sms_enabled", "whatsapp_enabled", "email_enabled",
                      "low_sms_balance_threshold"]:
            if field in data:
                setattr(ls, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_general_settings",
        entity_type="settings",
        entity_id=landlord_id,
        description="General settings updated.",
        before_data=before,
        after_data=landlord.to_dict(),
    )
    db.session.commit()
    return jsonify(landlord.to_dict()), 200


def _get_or_create_settings(landlord_id: int) -> LandlordSettings:
    ls = LandlordSettings.query.filter_by(landlord_id=landlord_id).first()
    if ls is None:
        ls = LandlordSettings(landlord_id=landlord_id)
        db.session.add(ls)
        db.session.flush()
    return ls


# ---------------------------------------------------------------------------
# GET / PUT /api/settings/sms-provider
# ---------------------------------------------------------------------------
@settings_bp.route("/sms-provider", methods=["GET", "PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def sms_provider_settings():
    """
    §9.3 Africa's Talking SMS reselling connection.

    GET: return the landlord's SMS-provider config (api key masked).
    PUT: save api key / username / sender ID. Body:
         { at_api_key?, at_username?, at_sender_id? }
         Sending an empty at_api_key clears the stored key.

    Connecting an AT sender ID lets the landlord send under their own sender
    ID (billed a flat rate per SMS). Without one, SahilPay's shared sender ID
    is used and messages are billed by length.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: SMS provider config.}
    """
    landlord_id = get_current_landlord_id()
    ls = _get_or_create_settings(landlord_id)

    if request.method == "GET":
        db.session.commit()
        # #2 — surface the landlord's live SMS balance, sender mode and the FIXED
        # admin-set per-SMS price so the UI can show exactly what a send costs. The
        # price is never landlord-editable: custom rate if they've connected their own
        # sender ID, otherwise the shared-sender default rate.
        from models import Landlord
        from services.sms_billing import load_rates, DEFAULT_PLATFORM_SENDER
        landlord = db.session.get(Landlord, landlord_id)
        rates = load_rates()
        has_own_sender = bool(getattr(ls, "at_sender_id", None) and getattr(ls, "at_api_key", None))
        payload = ls.to_dict()
        payload.update({
            "sms_balance":   landlord.sms_balance if landlord else 0,
            "sender_mode":   "custom" if has_own_sender else "default",
            "sender_id":     getattr(ls, "at_sender_id", None) or DEFAULT_PLATFORM_SENDER,
            "price_per_sms": float(rates["custom_price"] if has_own_sender else rates["default_price"]),
            "currency":      landlord.currency if landlord else "KES",
        })
        return jsonify(payload), 200

    from decorators import _check_permission
    _check_permission("settings", "edit")

    data = request.get_json(silent=True) or {}
    if "at_api_key" in data:
        ls.at_api_key = (data["at_api_key"] or "").strip() or None
    if "at_username" in data:
        ls.at_username = (data["at_username"] or "").strip() or None
    if "at_sender_id" in data:
        ls.at_sender_id = (data["at_sender_id"] or "").strip() or None

    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_sms_provider",
        entity_type="settings",
        entity_id=landlord_id,
        description="SMS provider credentials updated.",
    )
    db.session.commit()
    return jsonify(ls.to_dict()), 200


# ---------------------------------------------------------------------------
# POST /api/settings/sms-provider/connect  |  /disconnect
# ---------------------------------------------------------------------------
@settings_bp.route("/sms-provider/connect", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def connect_sms_provider():
    """
    Mark the landlord's Africa's Talking account connected. Requires an API
    key, username and sender ID to be saved first.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Connected.}
      400: {description: Missing credentials.}
    """
    landlord_id = get_current_landlord_id()
    ls = _get_or_create_settings(landlord_id)

    missing = [f for f in ("at_api_key", "at_username", "at_sender_id") if not getattr(ls, f)]
    if missing:
        return jsonify({"error": f"Save these first: {', '.join(missing)}."}), 400

    ls.at_connected = True
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="connect_sms_provider",
        entity_type="settings",
        entity_id=landlord_id,
        description=f"Africa's Talking connected — sender ID '{ls.at_sender_id}'.",
    )
    db.session.commit()
    return jsonify({"message": "Africa's Talking connected.", "settings": ls.to_dict()}), 200


@settings_bp.route("/sms-provider/disconnect", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def disconnect_sms_provider():
    """
    Disconnect the landlord's Africa's Talking account. Their messages revert
    to SahilPay's shared sender ID (billed by length). Credentials are kept so
    they can reconnect without re-entering them.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Disconnected.}
    """
    landlord_id = get_current_landlord_id()
    ls = _get_or_create_settings(landlord_id)
    ls.at_connected = False
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="disconnect_sms_provider",
        entity_type="settings",
        entity_id=landlord_id,
        description="Africa's Talking disconnected.",
    )
    db.session.commit()
    return jsonify({"message": "Africa's Talking disconnected.", "settings": ls.to_dict()}), 200


# ---------------------------------------------------------------------------
# GET / PUT /api/settings/automation
# ---------------------------------------------------------------------------
@settings_bp.route("/automation", methods=["GET", "PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def automation_settings():
    """
    GET: Return AutomationSettings for this landlord.
    PUT: Toggle any combination of automation flags.

    Celery Beat reads auto_generate_recurring_invoices,
    auto_generate_recurring_bills, monthly_reminders_enabled,
    lease_expiry_notifications on each beat tick.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Automation settings.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    aut         = landlord.automation_settings if landlord else None

    if request.method == "GET":
        return jsonify(aut.to_dict() if aut else {}), 200

    from decorators import _check_permission
    _check_permission("settings", "edit")

    data = request.get_json(silent=True) or {}
    if aut:
        for field in [
            "auto_generate_recurring_invoices", "auto_generate_recurring_bills",
            "alert_on_new_tenant", "auto_send_payment_acknowledgments",
            "monthly_reminders_enabled", "monthly_reminder_day",
            "lease_expiry_notifications", "lease_expiry_range_days",
        ]:
            if field in data:
                setattr(aut, field, data[field])
        db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_automation_settings",
        entity_type="settings",
        entity_id=landlord_id,
        description="Automation settings updated.",
        after_data=aut.to_dict() if aut else {},
    )
    db.session.commit()
    return jsonify(aut.to_dict() if aut else {}), 200


# ---------------------------------------------------------------------------
# POST /api/settings/automation/run  — run enabled scheduled automations now
# ---------------------------------------------------------------------------
@settings_bp.route("/automation/run", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def run_automations_now():
    """
    Run the landlord's ENABLED scheduled automations (monthly reminders, lease-
    expiry notices) once, immediately. Same logic Celery Beat runs on schedule —
    exposed so the toggles are verifiable without a running scheduler. Disabled
    automations are skipped, so the result reflects exactly what's turned on.
    """
    from services.automation_service import run_all_scheduled

    landlord = db.session.get(Landlord, get_current_landlord_id())
    result = run_all_scheduled(landlord)
    db.session.commit()
    return jsonify({"message": "Automations run.", "result": result}), 200


# ---------------------------------------------------------------------------
# GET / PUT /api/settings/alerts
# ---------------------------------------------------------------------------
@settings_bp.route("/alerts", methods=["GET", "PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def alert_settings():
    """
    GET: Return all AlertSetting rows for this landlord (one per alert type).
    PUT: Upsert one or more alert settings.
         Body: [{ alert_type, is_enabled, cadence?, channel? }, ...]

    If a row for the given alert_type does not exist, it is created.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Alert settings.}
    """
    landlord_id = get_current_landlord_id()

    if request.method == "GET":
        alerts = AlertSetting.query.filter_by(landlord_id=landlord_id).all()
        return jsonify({"alerts": [a.to_dict() for a in alerts]}), 200

    from decorators import _check_permission
    _check_permission("settings", "edit")

    data = request.get_json(silent=True) or {}
    items = data if isinstance(data, list) else data.get("alerts", [])

    updated = []
    for item in items:
        alert_type = item.get("alert_type")
        if not alert_type:
            continue
        row = AlertSetting.query.filter_by(
            landlord_id=landlord_id, alert_type=alert_type
        ).first()
        if not row:
            row = AlertSetting(landlord_id=landlord_id, alert_type=alert_type)
            db.session.add(row)
        for field in ["is_enabled", "cadence", "channel"]:
            if field in item:
                setattr(row, field, item[field])
        updated.append(row)

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_alert_settings",
        entity_type="settings",
        entity_id=landlord_id,
        description=f"{len(updated)} alert setting(s) updated.",
        after_data={"alerts": [a.to_dict() for a in updated]},
    )
    db.session.commit()
    return jsonify({"alerts": [a.to_dict() for a in updated]}), 200


# ---------------------------------------------------------------------------
# GET / PUT /api/settings/account
# ---------------------------------------------------------------------------
@settings_bp.route("/account", methods=["GET", "PUT"])
@jwt_required()
@require_landlord_or_team()
def account_settings():
    """
    GET: Return current user profile (username, names, email, phone, signature_url).
    PUT: Update profile fields.
         For password change: supply current_password + new_password.
         For signature: multipart form-data with 'signature' file field.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Account profile.}
    """
    user_id  = int(get_jwt_identity())
    user     = db.session.get(User, user_id)
    landlord_id = get_current_landlord_id()
    landlord = db.session.get(Landlord, landlord_id)

    if request.method == "GET":
        payload = user.to_dict()
        if landlord:
            payload["signature_url"] = landlord.signature_url
        return jsonify(payload), 200

    before = user.to_dict()

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()
        if "signature" in request.files and landlord:
            landlord.signature_url = upload_to_s3(
                request.files["signature"], folder=f"signatures/{landlord_id}"
            )

    # Profile fields on User
    for field in ["email", "phone"]:
        if field in data:
            setattr(user, field, data[field])

    # Password change
    current_pw = data.get("current_password")
    new_pw     = data.get("new_password")
    if current_pw and new_pw:
        if not check_password_hash(user.password_hash or "", current_pw):
            return jsonify({"error": "Current password is incorrect."}), 400
        if len(new_pw) < 8:
            return jsonify({"error": "New password must be at least 8 characters."}), 400
        user.password_hash = generate_password_hash(new_pw)
        user.must_change_password = False    # they've set their own password now

    db.session.commit()

    record_audit(
        actor_user_id=user_id,
        landlord_id=landlord_id,
        action="update_account",
        entity_type="account",
        entity_id=user_id,
        description="Account profile updated.",
        before_data=before,
        after_data=user.to_dict(),
    )
    db.session.commit()
    return jsonify(user.to_dict()), 200


# ---------------------------------------------------------------------------
# POST /api/settings/account/agent-code
# ---------------------------------------------------------------------------
@settings_bp.route("/account/agent-code", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def generate_agent_code():
    """
    Generate or regenerate the co-pilot agent code for this landlord.
    The agent code is a unique short string used by the Co-Pilot mobile app
    to identify which landlord account to post M-Pesa SMS data to.
    Regenerating invalidates the old code immediately.
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: New agent code generated.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    old_code = landlord.agent_code

    # Generate a unique 8-character alphanumeric code
    while True:
        code = secrets.token_urlsafe(6)[:8].upper()
        # Check uniqueness
        exists = Landlord.query.filter_by(agent_code=code).first()
        if not exists:
            break

    landlord.agent_code = code
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="generate_agent_code",
        entity_type="settings",
        entity_id=landlord_id,
        description=f"Agent code regenerated. Old: {old_code}, New: {code}.",
        after_data={"agent_code": code},
    )
    db.session.commit()

    return jsonify({
        "message":    "Agent code generated successfully.",
        "agent_code": code,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/settings/backup
# ---------------------------------------------------------------------------
@settings_bp.route("/backup", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def generate_backup():
    """
    Queue generation of a scoped backup export.
    Body:
      { scope_type: 'property'|'grouping'|'tenants'|'payments'|'category',
        scope_id?: int,   -- required for property / grouping / category scopes
        format: 'excel'|'pdf' }

    The Celery task generates the file and updates backup.file_url on completion.
    Returns the backup record immediately (file_url is null until complete).
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      202: {description: Backup generation queued.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    scope_type = data.get("scope_type")
    fmt        = data.get("format", BackupFormat.excel.value)

    if not scope_type:
        return jsonify({"error": "scope_type is required."}), 400
    if scope_type not in [s.value for s in BackupScopeType]:
        return jsonify({"error": f"Invalid scope_type. Valid: {[s.value for s in BackupScopeType]}."}), 400

    backup = Backup(
        landlord_id = landlord_id,
        scope_type  = scope_type,
        scope_id    = data.get("scope_id"),
        format      = fmt,
        file_url    = None,
    )
    db.session.add(backup)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="generate_backup",
        entity_type="settings",
        entity_id=backup.id,
        description=f"Backup export queued (scope={scope_type}, format={fmt}).",
        after_data=backup.to_dict(),
    )
    db.session.commit()

    from tasks.backup_tasks import generate_backup_task
    generate_backup_task.delay(backup.id)

    return jsonify({
        "message":   "Backup generation queued.",
        "backup":    backup.to_dict(),
    }), 202


# ---------------------------------------------------------------------------
# GET /api/settings/backup/generate  — synchronous, detailed, column-selectable
# ---------------------------------------------------------------------------
@settings_bp.route("/backup/generate", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def generate_backup_sync():
    """
    Build a detailed backup for a scope and return it immediately.
    ?scope_type=tenants|payments|units|properties|property|grouping
    ?scope_id=  (required for property / grouping)
    ?format=json|excel|pdf   (json = on-screen preview + column catalog)
    ?columns=section.col,...  (pick exactly which columns to back up)

    Unlike POST /backup (which queues a Celery job), this generates synchronously
    so the download works with nothing else running.
    """
    from services.backup_generator import build_backup
    from services.report_builder import document_to_json, parse_column_selection, render_document

    landlord = Landlord.query.filter_by(id=get_current_landlord_id()).first()
    scope_type = request.args.get("scope_type", "tenants")
    scope_id = request.args.get("scope_id", type=int)
    fmt = (request.args.get("format") or "json").lower()
    selection = parse_column_selection(request.args.get("columns"))

    doc = build_backup(landlord, scope_type, scope_id)

    if fmt == "json":
        return jsonify(document_to_json(doc, selection)), 200

    file_bytes = render_document(doc, fmt, selection)
    mime = "application/pdf" if fmt == "pdf" else \
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ext = "pdf" if fmt == "pdf" else "xlsx"
    fname = f"backup_{scope_type}" + (f"_{scope_id}" if scope_id else "")
    return Response(
        file_bytes, mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={fname}.{ext}"},
    ), 200


# ---------------------------------------------------------------------------
# GET /api/settings/backup
# ---------------------------------------------------------------------------
@settings_bp.route("/backup", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def list_backups():
    """
    List previously generated backups for this landlord.
    Backups with file_url=None are still processing.
    ?page=, ?per_page=
    ---
    tags: [Settings]
    security:
      - Bearer: []
    responses:
      200: {description: Backup list.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    paginated = (
        Backup.query
        .filter_by(landlord_id=landlord_id)
        .order_by(Backup.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        "backups":      [b.to_dict() for b in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200