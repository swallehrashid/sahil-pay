"""
services/sms_provider_service.py — how a landlord's SMS leaves the building.

THREE WAYS, IN ORDER OF HOW MUCH THE LANDLORD BRINGS
----------------------------------------------------
  shared       Sahil Pay's own sender name (SAHILPAY) on Sahil Pay's FluxSMS
               account. Billed from the landlord's Sahil Pay SMS balance.

  branded      The landlord's own sender NAME, registered by Sahil Pay on Sahil
               Pay's FluxSMS account. Only the name on the handset changes; it
               is still billed from the landlord's Sahil Pay SMS balance.

  own_account  THIRD PARTY. The landlord already has their own FluxSMS account
               — their own API key, their own approved sender ID, their own
               credit. Sahil Pay sends through THEIR account: the provider bills
               them directly, so nothing is deducted from their Sahil Pay SMS
               balance and nothing is drawn from Sahil Pay's pool.

The API key is validated LIVE on connect (a balance check against FluxSMS) —
an unchecked key used to connect "successfully" and then fail silently on
every send. It is stored encrypted, and never returned to the browser.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PREFIX = "enc:"

MODE_SHARED = "shared"
MODE_BRANDED = "branded"
MODE_OWN = "own_account"


def store_key(settings, raw: str | None) -> None:
    from services.twofa_service import encrypt_secret
    raw = (raw or "").strip()
    settings.sms_api_key = (_PREFIX + encrypt_secret(raw)) if raw else None


def has_own_key(settings) -> bool:
    """
    True only for a key saved through THIS flow (stored encrypted).

    Accounts can still carry a plaintext key from before, when "any key stored
    against a landlord is ignored" was the rule and sender names lived only on
    Sahil Pay's account. Those keys were never verified and may be long dead:
    treating one as a live third-party account would silently move that
    landlord's SMS onto it. They keep being ignored.
    """
    stored = getattr(settings, "sms_api_key", None) or ""
    return stored.startswith(_PREFIX)


def own_key(settings) -> str | None:
    """The landlord's own provider API key, decrypted — or None."""
    if not has_own_key(settings):
        return None
    from services.twofa_service import decrypt_secret
    return decrypt_secret(settings.sms_api_key[len(_PREFIX):])


def mode(settings) -> str:
    if settings is None or not settings.sms_connected or not settings.sms_sender_id:
        return MODE_SHARED
    return MODE_OWN if has_own_key(settings) else MODE_BRANDED


def sending_key(settings) -> str | None:
    """The API key a send must use: the landlord's own in own_account mode, else None (platform)."""
    return own_key(settings) if mode(settings) == MODE_OWN else None


def verify(settings) -> tuple[bool, str, int | None]:
    """
    Check the landlord's own API key against FluxSMS right now.
    Returns (ok, message, provider_balance).
    """
    from services.sms_service import _post

    key = own_key(settings)
    if not key:
        return False, "Enter your FluxSMS API key.", None
    result = _post("/check_sms_balance", {"api_key": key})
    if result is None:
        return False, ("Could not reach the SMS provider to check the key. "
                       "Try again in a minute."), None
    if result.get("success"):
        balance = result.get("sms_balance")
        return True, f"Key accepted by FluxSMS — {balance} SMS credit(s) on your account.", balance
    reason = result.get("error") or result.get("message") or "rejected"
    return False, f"FluxSMS rejected this API key: {reason}.", None


def describe(settings) -> dict:
    m = mode(settings)
    return {
        "mode": m,
        "label": {
            MODE_SHARED: "Sahil Pay shared sender",
            MODE_BRANDED: "Your sender name on Sahil Pay's account",
            MODE_OWN: "Your own FluxSMS account (third party)",
        }[m],
        "billed_to": "your FluxSMS account" if m == MODE_OWN else "your Sahil Pay SMS balance",
    }
