"""
routes/copilot_routes.py — Co-Pilot Device-Facing API
Blueprint: copilot_bp  |  Prefix: /api/copilot

Hit by the Co-Pilot Android app, never by the web frontend. No @jwt_required()
anywhere here — a phone has no browser session. Auth is the device token
issued at /pair, presented as `X-Copilot-Token` on every later call and
checked by @require_copilot_device (see COPILOT_PLATFORM_SPEC.md §4).

  POST /pair              — exchange a landlord's agent_code for a device token (once).
  POST /heartbeat         — device auth. App-open + daily check-in.
  POST /ingest            — device auth. Batch-forward queued SMSs.
  GET  /app/latest        — public. Version-check payload for the update prompt.
  GET  /app/download      — public. Redirects to the latest APK.

COPILOT_LANDLORD_INBOX_SPEC.md §3 adds landlord-SESSION endpoints below (JWT
auth, mirroring settings_routes.py — NOT the device-token pattern above):

  GET  /messages           — landlord's own Co-Pilot inbox, paginated + filtered.
  GET  /messages/<id>      — single message detail, 404 outside this landlord.
  GET  /messages/summary   — counts for the Payments page tab badge.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, g, redirect
from flask_jwt_extended import jwt_required

from extensions import db
from models import (
    Landlord, CopilotDevice, CopilotDeviceStatus, CopilotAppRelease,
    CopilotMessage, CopilotParseStatus, CopilotMatchStatus, PaymentStatus,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit
from services.notification_service import notify
from services.copilot_service import (
    generate_device_token, hash_device_token, process_copilot_message,
)

copilot_bp = Blueprint("copilot", __name__, url_prefix="/api/copilot")

# Curated preset list the app's Senders screen ships with (COPILOT_APP_SPEC.md §6).
# The pairing response feeds these to the app so a typo-prone free-type isn't the
# only option; landlords can still add a custom sender ID in the app itself.
SENDER_PRESETS = [
    "MPESA", "KCB", "EQUITY BANK", "CO-OP BANK", "NCBA",
    "ABSA", "FAMILY BANK", "DTB", "STANBIC", "I&M",
]

_MAX_BATCH = 50
_MAX_TEXT_LEN = 1000

# Simple in-process rate limiter for /pair (5 attempts / 15 min / IP). Best
# effort in a multi-process deployment — the agent code is short, so the goal
# is just to make brute force expensive, not airtight.
_PAIR_ATTEMPTS: dict[str, list[float]] = {}
_PAIR_WINDOW_SECONDS = 15 * 60
_PAIR_MAX_ATTEMPTS = 5


def _pair_rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _PAIR_ATTEMPTS.get(ip, []) if now - t < _PAIR_WINDOW_SECONDS]
    attempts.append(now)
    _PAIR_ATTEMPTS[ip] = attempts
    return len(attempts) > _PAIR_MAX_ATTEMPTS


def require_copilot_device(fn):
    """Resolves the active CopilotDevice from X-Copilot-Token, 401 otherwise.
    Attaches it to g.copilot_device and bumps last_seen_at on every call."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        raw_token = request.headers.get("X-Copilot-Token", "").strip()
        if not raw_token:
            return jsonify({"error": "Missing X-Copilot-Token header."}), 401

        device = CopilotDevice.query.filter_by(
            token_hash=hash_device_token(raw_token),
            status=CopilotDeviceStatus.active.value,
        ).first()
        if device is None:
            return jsonify({"error": "Invalid or revoked device token."}), 401

        g.copilot_device = device
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
        return fn(*args, **kwargs)
    return wrapper


def _latest_release() -> CopilotAppRelease | None:
    return CopilotAppRelease.query.filter_by(is_latest=True).first()


def _copilot_enabled(landlord: Landlord) -> bool:
    ls = landlord.landlord_settings
    return bool(ls and ls.copilot_enabled and not ls.copilot_admin_locked)


# ---------------------------------------------------------------------------
# POST /api/copilot/pair
# ---------------------------------------------------------------------------
@copilot_bp.route("/pair", methods=["POST"])
def pair_device():
    """
    Exchange an agent_code for a long-lived device token. The token is
    returned exactly once — only its sha256 hash is ever stored.
    Body: { agent_code, device_name, device_model?, app_version? }
    ---
    tags: [Co-Pilot]
    responses:
      200: {description: Device paired; device_token returned once.}
      403: {description: Co-pilot not enabled for this landlord.}
      404: {description: Invalid agent code.}
      429: {description: Too many pairing attempts from this address.}
    """
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if _pair_rate_limited(ip):
        return jsonify({"error": "Too many pairing attempts. Try again later."}), 429

    data = request.get_json(silent=True) or {}
    agent_code = (data.get("agent_code") or "").strip()
    device_name = (data.get("device_name") or "").strip()[:100]
    device_model = (data.get("device_model") or "").strip()[:100] or None
    app_version = (data.get("app_version") or "").strip()[:20] or None

    if not agent_code or not device_name:
        return jsonify({"error": "agent_code and device_name are required."}), 400

    landlord = Landlord.query.filter(
        db.func.upper(Landlord.agent_code) == agent_code.upper()
    ).first()
    if landlord is None:
        return jsonify({"error": "Invalid code."}), 404

    if not _copilot_enabled(landlord):
        return jsonify({
            "error": "Co-pilot is not enabled for this account. "
                     "Enable it in Sahil Settings → Co-pilot first.",
        }), 403

    raw_token, token_hash = generate_device_token()
    device = CopilotDevice(
        landlord_id=landlord.id,
        device_name=device_name,
        device_model=device_model,
        app_version=app_version,
        token_hash=token_hash,
        status=CopilotDeviceStatus.active.value,
        sender_ids=json.dumps([]),
        last_seen_at=datetime.utcnow(),
    )
    db.session.add(device)
    db.session.flush()

    # A device the landlord didn't expect is the #1 tell of a leaked code.
    if landlord.user_id:
        notify(
            recipient_user_id=landlord.user_id,
            category="copilot_device_paired",
            template_key="copilot_device_paired",
            template_kwargs={"device_name": device_name},
            landlord_id=landlord.id,
            link="/landlord/settings?tab=copilot",
            entity_type="copilot", entity_id=device.id,
        )
    record_audit(
        actor_user_id=None, landlord_id=landlord.id, action="copilot_device_paired",
        entity_type="copilot", entity_id=device.id,
        description=f"Co-pilot device \"{device_name}\" paired via agent code.",
    )
    db.session.commit()

    return jsonify({
        "device_token":   raw_token,
        "device_id":      device.id,
        "landlord_name":  landlord.company_name,
        "sender_presets": SENDER_PRESETS,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/copilot/heartbeat
# ---------------------------------------------------------------------------
@copilot_bp.route("/heartbeat", methods=["POST"])
@require_copilot_device
def heartbeat():
    """
    App-open + daily check-in. Reports app_version/sender_ids/queued_count;
    returns whether the device/landlord are still active so the app can show
    PAUSED/REVOKED banners or prompt a self-update.
    Body: { app_version?, sender_ids?: [...], queued_count? }
    ---
    tags: [Co-Pilot]
    security:
      - CopilotToken: []
    responses:
      200: {description: Device status + latest release info.}
    """
    device = g.copilot_device
    data = request.get_json(silent=True) or {}

    if data.get("app_version"):
        device.app_version = str(data["app_version"])[:20]
    if isinstance(data.get("sender_ids"), list):
        device.sender_ids = json.dumps([str(s)[:30] for s in data["sender_ids"]][:50])

    landlord = db.session.get(Landlord, device.landlord_id)
    release = _latest_release()

    db.session.commit()

    return jsonify({
        "status":                      device.status,
        "copilot_enabled":             _copilot_enabled(landlord) if landlord else False,
        "latest_version_code":        release.version_code if release else None,
        "min_supported_version_code": release.min_supported_version_code if release else None,
        "apk_url":                    "/api/copilot/app/download" if release else None,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/copilot/ingest
# ---------------------------------------------------------------------------
@copilot_bp.route("/ingest", methods=["POST"])
@require_copilot_device
def ingest():
    """
    Batch-forward queued SMSs. Always 200 once auth passes — outcomes are
    per-message inside `results` (client_uuid replay makes retries safe, so
    the app should keep a message QUEUED and retry on any ambiguous failure).
    Body: { messages: [{ client_uuid, sender_id, text, received_at? }] }
    ---
    tags: [Co-Pilot]
    security:
      - CopilotToken: []
    responses:
      200: {description: Per-message ingest results.}
      400: {description: Bad batch (too large, or missing fields).}
    """
    device = g.copilot_device
    data = request.get_json(silent=True) or {}
    messages = data.get("messages")

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "messages must be a non-empty array."}), 400
    if len(messages) > _MAX_BATCH:
        return jsonify({"error": f"Batch too large; max {_MAX_BATCH} messages per request."}), 400

    landlord = db.session.get(Landlord, device.landlord_id)
    results = []

    for item in messages:
        client_uuid = str(item.get("client_uuid") or "")
        sender_id = str(item.get("sender_id") or "")
        text = str(item.get("text") or "")[:_MAX_TEXT_LEN]
        received_at = None
        if item.get("received_at"):
            try:
                received_at = datetime.fromisoformat(str(item["received_at"]).replace("Z", "+00:00"))
            except ValueError:
                received_at = None

        if not client_uuid or not sender_id or not text:
            results.append({
                "client_uuid": client_uuid or None,
                "status": "rejected", "match": "n_a",
                "error": "client_uuid, sender_id and text are all required.",
            })
            continue

        try:
            msg = process_copilot_message(
                device, client_uuid=client_uuid, sender_id=sender_id,
                raw_text=text, received_at=received_at,
            )
            db.session.commit()
            results.append({
                "client_uuid": client_uuid,
                "status": msg.parse_status,
                "match": msg.match_status,
                "payment_ref": msg.payment.payment_ref if msg.payment_id and msg.payment else None,
                "error": msg.error_reason,
            })
        except Exception as exc:
            db.session.rollback()
            results.append({
                "client_uuid": client_uuid,
                "status": "rejected", "match": "n_a",
                "error": "Unexpected error processing this message.",
            })
            from flask import current_app
            current_app.logger.exception("copilot ingest: failed on client_uuid=%s: %s", client_uuid, exc)

    return jsonify({
        "results": results,
        "copilot_enabled": _copilot_enabled(landlord) if landlord else False,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/copilot/app/latest  (public)
# ---------------------------------------------------------------------------
@copilot_bp.route("/app/latest", methods=["GET"])
def app_latest():
    """Version-check payload for the app's self-update flow. Public — nothing
    secret in an APK's version metadata. ---
    tags: [Co-Pilot]
    responses:
      200: {description: Latest release info.}
      404: {description: No release uploaded yet.}
    """
    release = _latest_release()
    if release is None:
        return jsonify({"error": "No Co-pilot release is available yet."}), 404

    return jsonify({
        "version_name":                release.version_name,
        "version_code":                release.version_code,
        "min_supported_version_code":  release.min_supported_version_code,
        "apk_url":                     "/api/copilot/app/download",
        "release_notes":               release.release_notes,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/copilot/app/download  (public)
# ---------------------------------------------------------------------------
@copilot_bp.route("/app/download", methods=["GET"])
def app_download():
    """
    Redirects to the latest uploaded APK. This is the one link you send
    clients — public on purpose, since there's nothing secret in the APK
    itself and the app is never distributed via Play Store.
    ---
    tags: [Co-Pilot]
    responses:
      302: {description: Redirect to the APK file.}
      404: {description: No release uploaded yet.}
    """
    release = _latest_release()
    if release is None:
        return jsonify({"error": "No Co-pilot release is available yet."}), 404
    return redirect(release.apk_path)


# ===========================================================================
# Landlord inbox (COPILOT_LANDLORD_INBOX_SPEC.md §3)
# ===========================================================================
# Session-authenticated (JWT), NOT device-token. Mirrors settings_routes.py's
# auth stack exactly — do not reuse @require_copilot_device here.

def _serialise_message(msg: "CopilotMessage") -> dict:
    """§3.1/§3.2 response shape — the landlord's own inbox row, with the raw
    SMS body (redacted or not) plus enough tenant/payment context to act on
    it, without duplicating the payment-review flow."""
    tenant = msg.tenant
    payment = msg.payment
    return {
        "id":               msg.id,
        "sender_id":        msg.sender_id,
        "created_at":       msg.created_at.isoformat() if msg.created_at else None,
        "sms_received_at":  msg.sms_received_at.isoformat() if msg.sms_received_at else None,
        "parse_status":     msg.parse_status,
        "match_status":     msg.match_status,
        "parsed_amount":    str(msg.parsed_amount) if msg.parsed_amount is not None else None,
        "parsed_ref":       msg.parsed_ref,
        "parsed_name":      msg.parsed_name,
        "parsed_account":   msg.parsed_account,
        "parsed_phone":     msg.parsed_phone,
        "tenant": (
            {"id": tenant.id, "name": f"{tenant.first_name} {tenant.last_name}".strip(),
             "unit": tenant.unit.name if tenant.unit else None}
            if tenant else None
        ),
        "payment": (
            {"id": payment.id, "payment_ref": payment.payment_ref, "status": payment.status}
            if payment else None
        ),
        "error_reason":     msg.error_reason,
        "raw_text":         msg.raw_text,
        "raw_text_redacted": msg.raw_text_redacted,
    }


@copilot_bp.route("/messages", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def list_landlord_messages():
    """
    The landlord's own Co-Pilot inbox — every SMS ever forwarded on their
    behalf, whatever the outcome. This is the data source for the Payments
    page's Co-Pilot tab (§4).

    ?status=all|parsed|unparsed|duplicate|rejected (default all)
    ?match=all|matched|unmatched (default all)
    ?q= substring over parsed_name / parsed_ref / parsed_account
    ?page=, ?per_page= (default 25, max 100)
    ---
    tags: [Co-Pilot]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated Co-pilot message list.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = min(request.args.get("per_page", 25, type=int), 100)

    query = CopilotMessage.query.filter_by(landlord_id=landlord_id)

    status = request.args.get("status", "all")
    if status and status != "all":
        query = query.filter(CopilotMessage.parse_status == status)

    match = request.args.get("match", "all")
    if match and match != "all":
        query = query.filter(CopilotMessage.match_status == match)

    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                CopilotMessage.parsed_name.ilike(like),
                CopilotMessage.parsed_ref.ilike(like),
                CopilotMessage.parsed_account.ilike(like),
            )
        )

    paginated = query.order_by(CopilotMessage.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "messages":     [_serialise_message(m) for m in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


@copilot_bp.route("/messages/<int:message_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def get_landlord_message(message_id):
    """
    Single Co-Pilot message — the detail modal's data source (§4.3). 404 if
    it isn't this landlord's (never leak by guessable ID).
    ---
    tags: [Co-Pilot]
    security:
      - Bearer: []
    responses:
      200: {description: Co-pilot message detail.}
      404: {description: Message not found.}
    """
    landlord_id = get_current_landlord_id()
    msg = CopilotMessage.query.filter_by(id=message_id, landlord_id=landlord_id).first()
    if msg is None:
        return jsonify({"error": "Message not found."}), 404

    payload = _serialise_message(msg)
    payload["template_name"] = msg.template.name if msg.template else None
    return jsonify(payload), 200


@copilot_bp.route("/messages/summary", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def landlord_messages_summary():
    """
    Counts for the Payments page's Co-Pilot tab badge (§4.1).
    `pending_review` = messages whose linked Payment is still `pending`.
    ---
    tags: [Co-Pilot]
    security:
      - Bearer: []
    responses:
      200: {description: "{unparsed, unmatched, pending_review} counts."}
    """
    landlord_id = get_current_landlord_id()

    from models import Payment

    unparsed = CopilotMessage.query.filter_by(
        landlord_id=landlord_id, parse_status=CopilotParseStatus.unparsed.value,
    ).count()
    unmatched = CopilotMessage.query.filter_by(
        landlord_id=landlord_id, match_status=CopilotMatchStatus.unmatched.value,
    ).count()
    pending_review = (
        CopilotMessage.query
        .join(Payment, Payment.id == CopilotMessage.payment_id)
        .filter(
            CopilotMessage.landlord_id == landlord_id,
            Payment.status == PaymentStatus.pending.value,
        )
        .count()
    )

    return jsonify({
        "unparsed":       unparsed,
        "unmatched":      unmatched,
        "pending_review": pending_review,
    }), 200
