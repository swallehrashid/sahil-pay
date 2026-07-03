"""
SahilPay — services/sms_billing.py
=====================================
§9.3  The SMS reselling charge model.

SahilPay acts as the SMS provider for its landlords:

  * A landlord who has **connected their own Africa's Talking sender ID**
    sends under that sender ID and is billed a **flat rate per SMS**
    (OWN_SENDER_RATE), regardless of message length — "a shilling per SMS".

  * A landlord **without** a sender ID falls back to SahilPay's shared sender
    ID and is billed **by length**: PLATFORM_PER_SEGMENT for every 160-char
    (GSM-7) segment the message occupies, so long messages cost more.

This module is pure/stateless so it is trivially testable and is the single
source of truth for "how much does this SMS cost and who is it from".
"""

from __future__ import annotations

from decimal import Decimal

# GSM-7 encoding: a single SMS holds 160 chars; once a message spans multiple
# segments each segment holds 153 (7 chars per segment go to the concat header).
SINGLE_SEGMENT_LEN = 160
MULTI_SEGMENT_LEN = 153

OWN_SENDER_RATE = Decimal("1.00")       # flat KES per SMS, own sender ID
PLATFORM_PER_SEGMENT = Decimal("1.00")  # KES per 160-char segment, shared sender ID

DEFAULT_PLATFORM_SENDER = "SahilPay"


def count_segments(text: str) -> int:
    """How many SMS segments `text` occupies (min 1)."""
    length = len(text or "")
    if length <= SINGLE_SEGMENT_LEN:
        return 1
    # Concatenated message: every segment is 153 chars.
    return -(-length // MULTI_SEGMENT_LEN)  # ceil division


def resolve_sender(settings) -> tuple[str, bool]:
    """
    Return ``(sender_id, uses_own_sender_id)`` for a landlord's LandlordSettings.

    Uses the landlord's registered Africa's Talking sender ID when they have
    connected one; otherwise falls back to SahilPay's shared sender ID.
    """
    if settings is not None and settings.at_connected and settings.at_sender_id:
        return settings.at_sender_id, True
    return _platform_sender(), False


def _platform_sender() -> str:
    try:
        from flask import current_app
        return current_app.config.get("AT_SENDER_ID") or DEFAULT_PLATFORM_SENDER
    except Exception:
        return DEFAULT_PLATFORM_SENDER


def compute_sms_charge(text: str, uses_own_sender_id: bool) -> Decimal:
    """
    KES charged for sending `text`:
      * own sender ID  → flat OWN_SENDER_RATE per message
      * shared sender  → PLATFORM_PER_SEGMENT × segment count (length-based)
    """
    if uses_own_sender_id:
        return OWN_SENDER_RATE
    return (PLATFORM_PER_SEGMENT * count_segments(text)).quantize(Decimal("0.01"))


def quote_sms(text: str, settings) -> dict:
    """A previewable quote for a send: sender, segments, and cost."""
    sender_id, uses_own = resolve_sender(settings)
    segments = count_segments(text)
    charge = compute_sms_charge(text, uses_own)
    return {
        "sender_id":          sender_id,
        "uses_own_sender_id": uses_own,
        "segments":           segments,
        "charge":             float(charge),
        "length":             len(text or ""),
    }
