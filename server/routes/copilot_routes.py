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
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from functools import wraps

from flask import Blueprint, request, jsonify, g, redirect

from extensions import db
from models import Landlord, CopilotDevice, CopilotDeviceStatus, CopilotAppRelease
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
