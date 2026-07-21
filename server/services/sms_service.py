"""
SahilPay — services/sms_service.py
=====================================
SMS dispatch via FluxSMS (https://api.fluxsms.co.ke). send_sms() is a real
implementation — it posts JSON to FluxSMS's REST API whenever FLUXSMS_API_KEY
is configured, and falls back to logging the message when it isn't, so
OTP/reminder flows still complete while testing without real SMS credentials.

send_otp_sms is the Celery task wrapper otp_routes.py dispatches via
.delay(); send_sms is the plain synchronous function used everywhere else
(e.g. document_routes.py sends an immediate SMS notification).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from flask import current_app

from celery_app import celery

logger = logging.getLogger(__name__)


def _base_url() -> str:
    try:
        return current_app.config.get("FLUXSMS_BASE_URL") or "https://api.fluxsms.co.ke"
    except Exception:
        return "https://api.fluxsms.co.ke"


def _normalize_phone(phone: str) -> str:
    """Strip everything but digits and a leading '+' before sending to FluxSMS.
    Accepts 07XXXXXXXX / 01XXXXXXXX local format or 254XXXXXXXXX international —
    FluxSMS converts either on its end."""
    return re.sub(r"[^\d]", "", phone or "")


def _post(path: str, body: dict) -> dict | None:
    """POST JSON to a FluxSMS endpoint. Returns the parsed response dict, or
    None on a transport-level failure (never raises)."""
    url = _base_url().rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            logger.error("FluxSMS %s failed: HTTP %s", path, exc.code)
            return None
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        logger.error("FluxSMS %s failed: %s", path, exc)
        return None


def send_sms(
    recipient: str,
    content: str,
    sender_id: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """
    Send a single SMS via FluxSMS. Returns the provider's messageid string on
    success, or None if FluxSMS isn't configured (the message is logged
    instead) or the send fails. Never raises — a failed SMS should never fail
    the request/task that triggered it.

    §9.3 reselling: a landlord who has connected their own FluxSMS sender ID
    passes their own `api_key`/`sender_id`; otherwise the platform's global
    API key + shared sender ID (SAHILPAY) are used.
    """
    api_key = api_key or current_app.config.get("FLUXSMS_API_KEY")
    sender_id = sender_id or current_app.config.get("FLUXSMS_SENDER_ID")

    if not api_key:
        logger.info("SMS [stub — FluxSMS not configured] to %s (from %s): %s", recipient, sender_id or "-", content)
        return None

    phone = _normalize_phone(recipient)
    body = {"api_key": api_key, "message": content, "phone": phone, "sender_id": sender_id}

    result = _post("/sendsms", body)
    if result is None:
        return None

    if result.get("response-code") == 200:
        message_id = result.get("messageid")
        logger.info("SMS sent to %s via FluxSMS (messageid=%s).", recipient, message_id)
        return message_id

    logger.error("send_sms failed for %s: %s", recipient, result.get("error") or result)
    return None


def check_sms_balance(api_key: str | None = None) -> int | None:
    """FluxSMS pool/account balance for `api_key` (defaults to the platform
    key). Returns None on any failure — never raises."""
    api_key = api_key or current_app.config.get("FLUXSMS_API_KEY")
    if not api_key:
        return None
    result = _post("/check_sms_balance", {"api_key": api_key})
    if result and result.get("success"):
        return result.get("sms_balance")
    logger.error("check_sms_balance failed: %s", (result or {}).get("error") or result)
    return None


def get_delivery_status(message_id: str, api_key: str | None = None) -> dict | None:
    """Raw /smsstatus response for `message_id`, or None on failure."""
    api_key = api_key or current_app.config.get("FLUXSMS_API_KEY")
    if not api_key:
        return None
    return _post("/smsstatus", {"api_key": api_key, "message_id": message_id})


@celery.task(name="services.sms_service.send_otp_sms")
def send_otp_sms(identifier: str, code: str, first_name: str) -> None:
    """Celery task — sends a tenant's OTP login code via SMS.

    Honours COMMS_SIMULATION_MODE like every other outbound message path: when
    simulation is on (the default until go-live) the code is logged instead of
    dispatched, so a non-production environment that happens to carry the real
    FluxSMS key never fires a live SMS at a real number. In production
    (COMMS_SIMULATION_MODE=false) real OTP codes are sent."""
    content = f"Hi {first_name}, your Sahil Pay login code is {code}. It expires shortly — do not share it."
    if current_app.config.get("COMMS_SIMULATION_MODE", True):
        logger.info("SMS [simulated — OTP not sent] to %s: %s", identifier, content)
        return
    send_sms(identifier, content)
