"""
services/daraja_service.py — the ONLY module that talks HTTP to Safaricom's
Daraja API. Every route that needs an access token, an STK Push, an STK
status query, or a B2C payment goes through here.

Platform credentials only (PLATFORM_DARAJA_*) — this module has no notion of
a landlord's own paybill; rent stays off these rails (MPESA_INTEGRATION_SPEC.md D1).

Safaricom rejects any callback URL containing the word "mpesa" or "safaricom"
(discovered registering C2B URLs for production) — callers must pass URLs
built under /api/webhooks/daraja/..., never /api/webhooks/mpesa/....

MPESA_SIMULATION_MODE is NOT checked here — callers decide whether to call
this module at all. This module only performs real HTTP against DARAJA_BASE_URL.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime
from decimal import Decimal

import requests as ext_requests
from flask import current_app


class DarajaError(Exception):
    """Wraps a Daraja API failure. Carries the provider's own error fields
    when available so callers/logs can show something actionable."""

    def __init__(self, message: str, error_code: str | None = None, response_data: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.response_data = response_data or {}


def _cfg(key: str, default: str | None = None) -> str | None:
    return current_app.config.get(key, default)


def _base_url() -> str:
    return _cfg("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

def normalize_msisdn(raw: str | None) -> str | None:
    """Return a Safaricom MSISDN as 2547XXXXXXXX / 2541XXXXXXXX, or None if
    `raw` isn't a valid Kenyan Safaricom-format number."""
    if not raw:
        return None
    phone = raw.strip().replace("+", "").replace(" ", "").replace("-", "")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "254" + phone[1:]
    if re.match(r"^2547\d{8}$|^2541\d{8}$", phone):
        return phone
    return None


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def get_access_token(scope: str = "platform") -> str:
    """Obtain a Daraja OAuth token using the platform's own paybill
    credentials. Token is short-lived — fetch fresh each time; Daraja does
    not mind frequent calls to this endpoint."""
    consumer_key    = _cfg("PLATFORM_DARAJA_CONSUMER_KEY", "")
    consumer_secret = _cfg("PLATFORM_DARAJA_CONSUMER_SECRET", "")

    if not consumer_key or not consumer_secret:
        raise DarajaError("Platform Daraja consumer key/secret are not configured.")

    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

    try:
        resp = ext_requests.get(
            f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials",
            headers={"Authorization": f"Basic {credentials}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except ext_requests.RequestException as e:
        raise DarajaError(f"Could not obtain Daraja access token: {e}") from e


def _stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


# ---------------------------------------------------------------------------
# STK Push (Lipa Na M-Pesa Online)
# ---------------------------------------------------------------------------

def stk_push(phone: str, amount, account_ref: str, description: str, callback_url: str) -> dict:
    """
    Trigger an M-Pesa Express (STK) prompt on `phone` for `amount` shillings.
    Returns the raw Daraja response dict on HTTP success (caller must still
    check ResponseCode == "0"). Raises DarajaError on transport/token failure.
    """
    shortcode = _cfg("PLATFORM_DARAJA_SHORTCODE", "")
    passkey   = _cfg("PLATFORM_DARAJA_PASSKEY", "")
    if not shortcode or not passkey:
        raise DarajaError("Platform Daraja shortcode/passkey are not configured.")
    if not callback_url:
        raise DarajaError("callback_url is required for STK Push.")

    token     = get_access_token()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    password  = _stk_password(shortcode, passkey, timestamp)

    payload = {
        "BusinessShortCode": shortcode,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            int(float(amount)),
        "PartyA":            phone,
        "PartyB":            shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback_url,
        "AccountReference":  str(account_ref)[:12],
        "TransactionDesc":   str(description)[:13],
    }

    try:
        resp = ext_requests.post(
            f"{_base_url()}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except ext_requests.RequestException as e:
        raise DarajaError(f"STK Push request failed: {e}") from e


def stk_query(checkout_request_id: str) -> dict:
    """Query the outcome of a previously-issued STK Push. Used by the
    reconciliation sweep for pushes whose callback never arrived."""
    shortcode = _cfg("PLATFORM_DARAJA_SHORTCODE", "")
    passkey   = _cfg("PLATFORM_DARAJA_PASSKEY", "")
    if not shortcode or not passkey:
        raise DarajaError("Platform Daraja shortcode/passkey are not configured.")

    token     = get_access_token()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    password  = _stk_password(shortcode, passkey, timestamp)

    payload = {
        "BusinessShortCode": shortcode,
        "Password":          password,
        "Timestamp":         timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    try:
        resp = ext_requests.post(
            f"{_base_url()}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except ext_requests.RequestException as e:
        raise DarajaError(f"STK status query failed: {e}") from e


# ---------------------------------------------------------------------------
# B2C (Business to Customer) — affiliate payouts
# ---------------------------------------------------------------------------

def b2c_payment(phone: str, amount, remarks: str, occasion: str, originator_id: str) -> dict:
    """
    Send `amount` WHOLE SHILLINGS to `phone` via Daraja B2C (CommandID
    BusinessPayment). `originator_id` must be a UUID this caller generated —
    it is our idempotency handle for the async result callback.
    """
    shortcode            = _cfg("PLATFORM_DARAJA_SHORTCODE", "")
    initiator_name        = _cfg("PLATFORM_DARAJA_INITIATOR_NAME", "")
    security_credential    = _cfg("PLATFORM_DARAJA_SECURITY_CREDENTIAL", "")
    result_url            = _cfg("PLATFORM_DARAJA_B2C_RESULT_URL", "")
    timeout_url            = _cfg("PLATFORM_DARAJA_B2C_TIMEOUT_URL", "")

    if not shortcode or not initiator_name or not security_credential:
        raise DarajaError("B2C initiator credentials are not configured.")
    if not result_url or not timeout_url:
        raise DarajaError("B2C result/timeout URLs are not configured.")

    whole_amount = int(Decimal(str(amount)))  # B2C rejects decimals
    if whole_amount <= 0:
        raise DarajaError("B2C amount must be a positive whole number of shillings.")

    token = get_access_token()

    payload = {
        "OriginatorConversationID": originator_id,
        "InitiatorName":            initiator_name,
        "SecurityCredential":       security_credential,
        "CommandID":                "BusinessPayment",
        "Amount":                   whole_amount,
        "PartyA":                   shortcode,
        "PartyB":                   phone,
        "Remarks":                  str(remarks)[:100],
        "QueueTimeOutURL":          timeout_url,
        "ResultURL":                result_url,
        "Occasion":                 str(occasion)[:100],
    }

    try:
        resp = ext_requests.post(
            f"{_base_url()}/mpesa/b2c/v3/paymentrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except ext_requests.RequestException as e:
        raise DarajaError(f"B2C payment request failed: {e}") from e
