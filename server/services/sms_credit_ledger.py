"""
SahilPay — services/sms_credit_ledger.py
=========================================
The SMS-balance SOURCE OF TRUTH.

``landlords.sms_balance`` is a fast running counter: +credits on a confirmed
purchase, −credits on a send. A counter has no memory of how it got where it
is, so a single stray increment — e.g. the same M-Pesa payment confirmed twice,
once by the STK callback and once by the C2B confirmation of the very same money
— sticks forever and silently. That is exactly how a landlord who bought 1,000
credits ended up reading 2,000.

This module defines what the balance SHOULD be, derived only from events that
actually happened and can be trusted:

    balance = confirmed-purchase credits (one grant per M-Pesa receipt)
            + admin manual credits (genuine, excluding our own corrections)
            − credits used on messages that were actually charged

Nothing a failed, unconfirmed or reversed payment did counts. Each distinct
M-Pesa receipt grants its credits once, no matter how many callbacks reported
it. ``reconcile_sms_balance`` rebuilds a landlord's balance from this truth and
records the correction in the per-landlord credit ledger so every change is
visible and reversible. The deploy migration calls the same logic for every
landlord, so a redeploy heals historical drift on the first request.

Going forward the counter cannot drift back: crediting is idempotent per
receipt (services/billing_service.finalize_sms_purchase) and every send records
the credits it burned (communication_logs.sms_credits), so the counter and this
derivation stay in agreement.
"""

from __future__ import annotations

# Marker on the reason of a SmsLandlordCredit row that THIS reconciliation
# writes. These rows document a correction for the audit trail; they are the
# balance landing where the truth says, NOT an extra manual grant — so the
# manual-credits term below deliberately excludes them, keeping the identity
# "balance == purchases + manual − used" stable across repeated reconciles.
RECON_REASON_PREFIX = "SYS-RECON:"


def _confirmed_purchase_credits(landlord_id: int) -> int:
    """
    Credits from CONFIRMED, non-reversed SMS purchases, counting each distinct
    M-Pesa receipt once. Two transactions that carry the same receipt (the
    STK-callback row and the C2B-confirmation row for one payment) collapse to a
    single grant — this is the fix for the double-credit at the read side.

    A transaction with no receipt (a legacy self-reported purchase an admin
    manually verified) has no key to dedupe on, so each is counted once on its
    own — they were never the source of the duplication.
    """
    from models import BillingTransaction, BillingTransactionType

    rows = (
        BillingTransaction.query
        .filter(
            BillingTransaction.landlord_id == landlord_id,
            BillingTransaction.type == BillingTransactionType.sms_purchase.value,
            BillingTransaction.is_verified.is_(True),
            BillingTransaction.is_reversed.is_(False),
            BillingTransaction.sms_count.isnot(None),
        )
        .order_by(BillingTransaction.id.asc())
        .all()
    )

    total = 0
    seen_receipts: set[str] = set()
    for txn in rows:
        receipt = (txn.payment_reference or "").strip()
        if receipt:
            if receipt in seen_receipts:
                continue          # same payment, already counted
            seen_receipts.add(receipt)
        total += int(txn.sms_count or 0)
    return total


def _manual_credits(landlord_id: int) -> int:
    """
    Signed sum of genuine admin manual adjustments (cash paid to the operator,
    goodwill credits, hand corrections). Excludes rows this reconciliation wrote
    — those record where the balance was moved TO, not an additional grant.
    """
    from extensions import db
    from models import SmsLandlordCredit

    total = (
        db.session.query(db.func.coalesce(db.func.sum(SmsLandlordCredit.credits_added), 0))
        .filter(
            SmsLandlordCredit.landlord_id == landlord_id,
            db.not_(SmsLandlordCredit.reason.like(RECON_REASON_PREFIX + "%")),
        )
        .scalar()
    )
    return int(total or 0)


def _credits_used(landlord_id: int) -> int:
    """
    Credits burned by this landlord's SMS sends — summed from the per-message
    ``sms_credits`` the send recorded, never from ``sms_segments`` (raw GSM
    segments, a different unit). Failed/blocked/demo/own-key sends recorded 0,
    so they correctly do not count as usage.
    """
    from extensions import db
    from models import CommunicationLog, MessageChannel

    total = (
        db.session.query(db.func.coalesce(db.func.sum(CommunicationLog.sms_credits), 0))
        .filter(
            CommunicationLog.landlord_id == landlord_id,
            CommunicationLog.message_type == MessageChannel.sms.value,
        )
        .scalar()
    )
    return int(total or 0)


def compute_truth(landlord_id: int) -> dict:
    """
    The derived balance and its components for one landlord. Pure read — nothing
    is written, so callers can preview a reconciliation (admin UI, tests, the
    migration's dry run) before applying it.
    """
    purchased = _confirmed_purchase_credits(landlord_id)
    manual    = _manual_credits(landlord_id)
    used      = _credits_used(landlord_id)
    # A balance can never be negative: over-use past what was ever bought is
    # already prevented at send time (decrement floors at 0), so the truth
    # floors too rather than carrying a phantom debt.
    target    = max(0, purchased + manual - used)
    return {
        "purchased": purchased,
        "manual":    manual,
        "used":      used,
        "target":    target,
    }


def reconcile_sms_balance(landlord, *, actor_admin_id: int | None = None,
                          apply: bool = True) -> dict:
    """
    Rebuild ``landlord.sms_balance`` from the source of truth.

    Returns {before, after, delta, purchased, manual, used, changed}. When
    ``apply`` is True and the truth differs from the current balance, the
    balance is set to the truth and a SmsLandlordCredit row records the signed
    correction (reason prefixed ``SYS-RECON:``) so the move is auditable and
    reversible. The row is flushed, not committed — the caller owns the
    transaction. ``apply=False`` computes and returns without writing.
    """
    from extensions import db
    from models import SmsLandlordCredit

    truth  = compute_truth(landlord.id)
    before = int(landlord.sms_balance or 0)
    target = truth["target"]
    delta  = target - before
    result = {
        "before":    before,
        "after":     target,
        "delta":     delta,
        "purchased": truth["purchased"],
        "manual":    truth["manual"],
        "used":      truth["used"],
        "changed":   delta != 0,
    }

    if apply and delta != 0:
        landlord.sms_balance = target
        db.session.add(SmsLandlordCredit(
            landlord_id=landlord.id,
            admin_user_id=actor_admin_id,
            credits_added=delta,
            balance_after=target,
            reason=(
                f"{RECON_REASON_PREFIX} rebuilt from confirmed payments "
                f"({truth['purchased']} purchased + {truth['manual']} manual "
                f"− {truth['used']} used); was {before}."
            )[:255],
        ))
        db.session.flush()

    return result
