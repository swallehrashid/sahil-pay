"""
SahilPay — services/sms_billing.py
=====================================
§9.3  The SMS reselling charge model — ONE POOL, ONE PRICE.

SahilPay is the wholesaler for every landlord on the platform. There is a
single arrangement, and the sender ID a message goes out under does not change
the money:

  * SahilPay buys credits from FluxSMS in bulk at the platform cost and holds
    them in the shared pool (``SmsPricingConfig.pool_balance``).

  * A landlord buys credits from SahilPay at their price — the account-wide
    default, or a negotiated per-landlord rate. That fills their
    ``landlords.sms_balance``, which is a claim against the pool, not stock of
    its own.

  * Sending ALWAYS spends SahilPay's pool and ALWAYS costs SahilPay the
    wholesale price, whether the message goes out as ``SAHILPAY`` or under the
    landlord's own registered sender ID. Every alphanumeric sender ID is
    registered with FluxSMS **on SahilPay's account**, so delivery is billed to
    SahilPay in both cases. The margin is (landlord price − platform cost).

WHY THERE IS NO "BRING YOUR OWN PROVIDER ACCOUNT" PATH
------------------------------------------------------
There used to be one: a landlord with their own sender ID sent using their own
FluxSMS API key, out of their own FluxSMS balance, and was charged a smaller
"service fee" with SahilPay recording zero delivery cost. It was removed
because it silently lost money the moment a sender ID was registered under
SahilPay's account instead — the pool drained for real while the books recorded
nothing, and there was no way to tell the two situations apart from inside the
app. One pool and one price cannot drift like that.

A landlord's own sender ID is now purely cosmetic: it changes the name on the
recipient's handset and nothing else.

The per-credit prices, the wholesale cost (for margin analytics) and the pool
balance all live in the admin-editable ``SmsPricingConfig`` singleton. This
module reads that config at call time and falls back to the module constants
when no config row (or app context) is available, so it stays trivially
testable and remains the single source of truth for "what does this cost the
landlord, and what does it cost us".
"""

from __future__ import annotations

from decimal import Decimal

# GSM-7 encoding: a single SMS holds 160 chars; once a message spans multiple
# segments each segment holds 153 (7 chars per segment go to the concat header).
SINGLE_SEGMENT_LEN = 160
MULTI_SEGMENT_LEN = 153

# Fallback rates when no SmsPricingConfig row / app context is available.
DEFAULT_PRICE_PER_SMS = Decimal("1.00")   # KES/credit charged to a landlord
PLATFORM_COST_PER_SMS = Decimal("0.40")   # KES/credit SahilPay pays FluxSMS

# RETIRED. Kept only so an existing SmsPricingConfig row and the admin PUT that
# writes it do not break; nothing reads it for pricing any more. Every landlord
# pays the default price unless they have a negotiated override, whichever
# sender ID their messages go out under.
CUSTOM_PRICE_PER_SMS  = Decimal("1.00")

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


def effective_price_per_sms(settings, uses_own_sender_id: bool = False,
                            rates: dict | None = None,
                            landlord=None) -> Decimal:
    """
    What THIS landlord pays per SMS credit.

    Precedence:
      1. landlords.sms_price_override — the rate negotiated with this landlord.
      2. the account-wide default price.

    The sender ID is NOT part of this decision. Every credit comes out of the
    same pool and costs SahilPay the same to buy, so a branded sender ID has no
    bearing on what a credit is worth. `uses_own_sender_id` is accepted only so
    existing callers keep working.

    This is the ONE place a landlord's price is decided — the buy screen, the
    balance decrement and the margin report all call it, so the price a
    landlord is quoted and the price they are charged cannot drift apart.
    """
    rates = rates or load_rates()

    # Prefer an explicitly supplied landlord: a landlord with no
    # LandlordSettings row would otherwise silently lose their negotiated rate.
    landlord = landlord or getattr(settings, "landlord", None)
    override = getattr(landlord, "sms_price_override", None) if landlord else None
    if override is not None:
        try:
            return Decimal(str(override))
        except (TypeError, ValueError, ArithmeticError):
            pass

    return rates["default_price"]


def compute_sms_charge(text: str, uses_own_sender_id: bool = False,
                       rates: dict | None = None) -> Decimal:
    """
    DEPRECATED — use price_sms(), which bills by credits rather than raw
    segments and honours a landlord's negotiated rate. Retained only so any
    out-of-tree caller keeps working; it cannot see a per-landlord override
    because it is given no landlord.
    """
    rates = rates or load_rates()
    return (rates["default_price"] * count_segments(text)).quantize(Decimal("0.01"))


def compute_platform_cost(text: str, uses_own_sender_id: bool = False,
                          rates: dict | None = None) -> Decimal:
    """
    DEPRECATED — see compute_sms_charge. SahilPay pays for delivery whichever
    sender ID is on the message, so this no longer returns zero for branded
    senders.
    """
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
    unit_price = effective_price_per_sms(settings, uses_own, rates)
    charge = (unit_price * credits).quantize(Decimal("0.01"))
    # Delivery is billed to SahilPay whichever sender ID is on the message,
    # because every registered sender ID sits on SahilPay's FluxSMS account.
    # Recording 0 here for branded senders is what used to hide the loss.
    cost = (rates["platform_cost"] * credits).quantize(Decimal("0.01"))
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
