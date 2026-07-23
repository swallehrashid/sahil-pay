"""
SahilPay — services/sms_billing.py
=====================================
§9.3  The SMS reselling charge model.

SahilPay acts as the SMS provider for its landlords:

  * A landlord who has **connected their own SMS sender ID** (a *custom*
    user) sends under that sender ID out of their own provider account
    and is billed SahilPay's **custom price per SMS** — a pure service fee
    (SahilPay incurs no delivery cost for them).

  * A landlord **without** a sender ID (a *default* user) falls back to
    SahilPay's shared sender ID, delivered out of SahilPay's shared credit
    pool, and is billed the **default price per SMS** for every 160-char
    (GSM-7) segment the message occupies, so long messages cost more.

The per-SMS prices, the fixed platform cost per SMS (for margin analytics) and
the shared-pool balance all live in the admin-editable ``SmsPricingConfig``
singleton. This module reads that config at call time and falls back to the
module constants when no config row (or app context) is available, so it stays
trivially testable and remains the single source of truth for "how much does
this SMS cost, who is it from, and what does it cost us".
"""

from __future__ import annotations

from decimal import Decimal

# GSM-7 encoding: a single SMS holds 160 chars; once a message spans multiple
# segments each segment holds 153 (7 chars per segment go to the concat header).
SINGLE_SEGMENT_LEN = 160
MULTI_SEGMENT_LEN = 153

# Fallback rates when no SmsPricingConfig row / app context is available.
DEFAULT_PRICE_PER_SMS = Decimal("1.00")   # KES/SMS, shared sender (default users)
CUSTOM_PRICE_PER_SMS  = Decimal("0.50")   # KES/SMS, own sender (custom users)
PLATFORM_COST_PER_SMS = Decimal("0.65")   # KES/SMS SahilPay pays the provider

DEFAULT_PLATFORM_SENDER = "SAHILPAY"

# Market-aligned default word→credit tiers (FluxSMS/GSM: ~26 words ≈ one 160-char
# SMS segment). Seeded into sms_credit_ranges on first use; fully admin-editable
# thereafter. (min_words, max_words|None, credits).
DEFAULT_CREDIT_RANGES = [
    (1, 25, 1),
    (26, 50, 2),
    (51, 75, 3),
    (76, 100, 4),
    (101, None, 5),
]


def count_segments(text: str) -> int:
    """How many SMS segments `text` occupies (min 1)."""
    length = len(text or "")
    if length <= SINGLE_SEGMENT_LEN:
        return 1
    # Concatenated message: every segment is 153 chars.
    return -(-length // MULTI_SEGMENT_LEN)  # ceil division


def count_words(text: str) -> int:
    """Number of whitespace-separated words in `text` (min 0)."""
    return len((text or "").split())


def _seed_default_ranges():
    """
    Create the default credit ranges if none exist, committing so the first-use
    seed persists (read paths call this; without a commit the seeded rows would
    roll back at request end and be re-created — and re-numbered — every call).
    Guards against a race by re-checking after acquiring rows.
    """
    from extensions import db
    from models import SmsCreditRange
    if SmsCreditRange.query.count() == 0:
        for mn, mx, cr in DEFAULT_CREDIT_RANGES:
            db.session.add(SmsCreditRange(min_words=mn, max_words=mx, credits=cr))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return SmsCreditRange.query.order_by(SmsCreditRange.min_words).all()


def load_credit_ranges() -> list[dict]:
    """
    Return the admin-defined word→credit tiers (seeding market defaults on first
    use), sorted ascending. Falls back to the module defaults with no db context.
    """
    try:
        from models import SmsCreditRange
        rows = SmsCreditRange.query.order_by(SmsCreditRange.min_words).all()
        if not rows:
            rows = _seed_default_ranges()
        return [r.to_dict() for r in rows]
    except Exception:
        return [{"id": None, "min_words": mn, "max_words": mx, "credits": cr}
                for (mn, mx, cr) in DEFAULT_CREDIT_RANGES]


def credits_for_words(word_count: int, ranges: list[dict] | None = None) -> int:
    """
    Credits charged for a message of `word_count` words, per the tier table.
    Uses the first tier whose [min_words, max_words] contains the count; if the
    count exceeds every closed tier and the last tier is open-ended (max=None),
    that tier's credits apply. Falls back to 1 credit if no tier matches.
    """
    ranges = ranges if ranges is not None else load_credit_ranges()
    wc = max(1, int(word_count or 0))
    for r in ranges:
        mn = r["min_words"]
        mx = r["max_words"]
        if wc >= mn and (mx is None or wc <= mx):
            return int(r["credits"])
    return 1


def credits_for_text(text: str, ranges: list[dict] | None = None) -> int:
    """Credits for the given message text (word-count based)."""
    return credits_for_words(count_words(text), ranges)


def load_rates() -> dict:
    """
    Read the live SmsPricingConfig singleton, returning the three rates plus the
    shared-sending master toggle and pool balance. Falls back to module
    constants when there is no app/db context (e.g. unit tests) so callers never
    need a live database.
    """
    try:
        from models import SmsPricingConfig
        cfg = SmsPricingConfig.get_singleton()
        return {
            "default_price":  Decimal(str(cfg.default_price_per_sms)),
            "custom_price":   Decimal(str(cfg.custom_price_per_sms)),
            "platform_cost":  Decimal(str(cfg.platform_cost_per_sms)),
            "shared_enabled": bool(cfg.shared_sending_enabled),
            "pool_balance":   int(cfg.pool_balance),
        }
    except Exception:
        return {
            "default_price":  DEFAULT_PRICE_PER_SMS,
            "custom_price":   CUSTOM_PRICE_PER_SMS,
            "platform_cost":  PLATFORM_COST_PER_SMS,
            "shared_enabled": True,
            "pool_balance":   0,
        }


def resolve_sender(settings) -> tuple[str, bool]:
    """
    Return ``(sender_id, uses_own_sender_id)`` for a landlord's LandlordSettings.

    Uses the landlord's registered custom sender ID when they have connected
    one; otherwise falls back to SahilPay's shared sender ID.
    """
    if settings is not None and settings.sms_connected and settings.sms_sender_id:
        return settings.sms_sender_id, True
    return _platform_sender(), False


def _platform_sender() -> str:
    try:
        from flask import current_app
        return current_app.config.get("FLUXSMS_SENDER_ID") or DEFAULT_PLATFORM_SENDER
    except Exception:
        return DEFAULT_PLATFORM_SENDER


def compute_sms_charge(text: str, uses_own_sender_id: bool, rates: dict | None = None) -> Decimal:
    """
    KES charged to the landlord for sending `text`:
      * own sender  (custom) → custom_price × segment count
      * shared      (default)→ default_price × segment count (length-based)
    """
    rates = rates or load_rates()
    unit = rates["custom_price"] if uses_own_sender_id else rates["default_price"]
    return (unit * count_segments(text)).quantize(Decimal("0.01"))


def compute_platform_cost(text: str, uses_own_sender_id: bool, rates: dict | None = None) -> Decimal:
    """
    SahilPay's own cost of delivering `text`. Zero for custom users (they
    deliver via their own AT account); platform_cost × segments for shared
    (default) sends out of SahilPay's pool.
    """
    if uses_own_sender_id:
        return Decimal("0.00")
    rates = rates or load_rates()
    return (rates["platform_cost"] * count_segments(text)).quantize(Decimal("0.01"))


def price_sms(text: str, settings, rates: dict | None = None,
              ranges: list[dict] | None = None) -> dict:
    """
    Full economics for a single send — the one call dispatch_message needs:
    sender, own-vs-shared, credits (from the admin word→credit tiers), resale
    charge, and SahilPay's cost.

    `credits` (not raw segments) is now the billed unit: it is what the
    landlord's balance is decremented by and what the resale/platform price
    multiplies. `segments` is retained for diagnostics/GSM reference.
    """
    rates = rates or load_rates()
    sender_id, uses_own = resolve_sender(settings)
    segments = count_segments(text)
    words = count_words(text)
    credits = credits_for_words(words, ranges)
    unit_price = rates["custom_price"] if uses_own else rates["default_price"]
    charge = (unit_price * credits).quantize(Decimal("0.01"))
    cost = Decimal("0.00") if uses_own else (rates["platform_cost"] * credits).quantize(Decimal("0.01"))
    return {
        "sender_id":          sender_id,
        "uses_own_sender_id": uses_own,
        "segments":           segments,
        "words":              words,
        "credits":            credits,
        "length":             len(text or ""),
        "charge":             charge,
        "platform_cost":      cost,
    }


def quote_sms(text: str, settings) -> dict:
    """A previewable quote for a send: sender, credits, and cost (floats)."""
    q = price_sms(text, settings)
    return {
        "sender_id":          q["sender_id"],
        "uses_own_sender_id": q["uses_own_sender_id"],
        "segments":           q["segments"],
        "words":              q["words"],
        "credits":            q["credits"],
        "charge":             float(q["charge"]),
        "platform_cost":      float(q["platform_cost"]),
        "length":             q["length"],
    }
