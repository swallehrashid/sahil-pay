"""
SahilPay — services/sms_service.py
=====================================
SMS dispatch via Africa's Talking. send_sms() is a real implementation —
it posts to Africa's Talking's REST API using stdlib urllib (no extra
dependency) whenever AT_USERNAME/AT_API_KEY are configured, and falls back
to logging the message when they aren't, so OTP/reminder flows still
complete while testing without real SMS credentials.

send_otp_sms is the Celery task wrapper otp_routes.py dispatches via
.delay(); send_sms is the plain synchronous function used everywhere else
(e.g. document_routes.py sends an immediate SMS notification).
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app

from celery_app import celery

logger = logging.getLogger(__name__)

AFRICASTALKING_SMS_URL = "https://api.africastalking.com/version1/messaging"


def send_sms(recipient: str, content: str) -> str | None:
    """
    Send a single SMS. Returns the raw provider response on success, or None
    if Africa's Talking isn't configured (the message is logged instead) or
    the send fails. Never raises — a failed SMS should never fail the
    request/task that triggered it.
    """
    username = current_app.config.get("AT_USERNAME")
    api_key = current_app.config.get("AT_API_KEY")
    sender_id = current_app.config.get("AT_SENDER_ID")

    if not username or not api_key:
        logger.info("SMS [stub — Africa's Talking not configured] to %s: %s", recipient, content)
        return None

    body = {"username": username, "to": recipient, "message": content}
    if sender_id:
        body["from"] = sender_id

    data = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        AFRICASTALKING_SMS_URL,
        data=data,
        headers={
            "apiKey": api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode("utf-8")
            logger.info("SMS sent to %s via Africa's Talking.", recipient)
            return payload
    except urllib.error.URLError as exc:
        logger.error("send_sms failed for %s: %s", recipient, exc)
        return None


@celery.task(name="services.sms_service.send_otp_sms")
def send_otp_sms(identifier: str, code: str, first_name: str) -> None:
    """Celery task — sends a tenant's OTP login code via SMS."""
    content = f"Hi {first_name}, your SahilPay login code is {code}. It expires shortly — do not share it."
    send_sms(identifier, content)
