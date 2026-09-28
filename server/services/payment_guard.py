"""
services/payment_guard.py — a payment is reviewed and allocated ONCE, to ONE tenant.

HOW THE SAME MONEY GOT ALLOCATED TWICE
--------------------------------------
Three separate holes, each of which let one M-Pesa payment land on a tenant's
account twice:

1. The split/allocate endpoint (POST /payments/<id>/allocate, used by the
   review queue) never looked at the payment's status. Allocating a payment
   that had already been confirmed from the Payments page simply ran the
   allocation again on top — the tenant's invoices were paid twice from one
   transfer.

2. Duplicates were detected only against Co-pilot's own M-Pesa transaction
   table. Record "QJK4X…" by hand on the Payments page, then let Co-pilot read
   the same SMS, and Co-pilot saw no transaction with that code and created a
   second payment for the same money. (And the other way round.)

3. "Already confirmed?" was checked without locking the row, so a double
   click — or the Payments page and the Co-pilot inbox open side by side —
   could both pass the check before either had saved.

THE RULE, ENFORCED IN ONE PLACE
-------------------------------
`claim_for_allocation()` takes a row lock on the payment, refuses one that is
already confirmed or already carries allocations, and refuses an M-Pesa code
that another confirmed payment on the account already carries. Every path that
allocates money calls it first.

A split across several of one tenant's units shares one M-Pesa code by design
(services/payment_resolver.allocate_manually creates the child payments inside
the same claim), so a split never trips the duplicate check.
"""

from __future__ import annotations

from extensions import db
from utils import ApiError


class AlreadyAllocated(ApiError):
    def __init__(self, message: str):
        super().__init__(message, status=409, code="already_allocated")


def normalise_ref(ref: str | None) -> str | None:
    ref = (ref or "").strip().upper()
    return ref or None


def duplicate_of(landlord_id: int, mpesa_reference: str | None, *, exclude_id: int | None = None):
    """
    Another CONFIRMED, live payment on this account carrying the same M-Pesa
    code, or None. Pending/declined/reversed rows do not count: they never
    reached anybody's ledger.
    """
    from models import Payment, PaymentStatus

    ref = normalise_ref(mpesa_reference)
    if not ref:
        return None
    q = Payment.query.filter(
        Payment.landlord_id == landlord_id,
        Payment.is_deleted.is_(False),
        Payment.status == PaymentStatus.confirmed.value,
        db.func.upper(db.func.trim(Payment.mpesa_reference)) == ref,
    )
    if exclude_id is not None:
        q = q.filter(Payment.id != exclude_id)
    return q.first()


def _describe(dupe) -> str:
    who = ""
    if dupe.tenant is not None:
        who = f" to {dupe.tenant.first_name} {dupe.tenant.last_name}".rstrip()
    return (f"M-Pesa code {dupe.mpesa_reference} was already allocated{who} "
            f"as payment {dupe.payment_ref} on {dupe.payment_date}. "
            "A payment can only be allocated once, to one tenant.")


def assert_not_duplicate(landlord_id: int, mpesa_reference: str | None, *,
                         exclude_id: int | None = None) -> None:
    dupe = duplicate_of(landlord_id, mpesa_reference, exclude_id=exclude_id)
    if dupe is not None:
        raise AlreadyAllocated(_describe(dupe))


def claim_for_allocation(payment):
    """
    Lock *payment* and make sure it may be allocated now. Returns the locked row.

    Raises AlreadyAllocated (409) when it is already confirmed, already carries
    allocations, or its M-Pesa code is already on another confirmed payment.
    Must be called inside the transaction that then allocates it; the lock is
    released on commit/rollback.
    """
    from models import Payment, PaymentAllocation, PaymentStatus

    locked = (
        db.session.query(Payment)
        .filter(Payment.id == payment.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if locked.is_deleted:
        raise AlreadyAllocated("This payment has been deleted.")
    if locked.status == PaymentStatus.confirmed.value:
        who = ""
        if locked.tenant is not None:
            who = f" to {locked.tenant.first_name} {locked.tenant.last_name}"
        raise AlreadyAllocated(
            f"Payment {locked.payment_ref} has already been reviewed and allocated{who}. "
            "A payment can only be allocated once."
        )
    has_allocations = db.session.query(PaymentAllocation.id).filter(
        PaymentAllocation.payment_id == locked.id).first() is not None
    if has_allocations:
        raise AlreadyAllocated(
            f"Payment {locked.payment_ref} already has allocations. "
            "Reverse it first if it went to the wrong place."
        )
    assert_not_duplicate(locked.landlord_id, locked.mpesa_reference, exclude_id=locked.id)
    return locked
