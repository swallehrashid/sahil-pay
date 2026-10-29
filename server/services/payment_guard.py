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


# ===========================================================================
# THE INVOICE RULE — money is only ever recorded against something invoiced
# ===========================================================================
#
# A payment is an answer to a charge. You invoice first, then a payment is
# allocated to that invoice; allocating to something that does not exist yet is
# not bookkeeping, it is a guess. The app used to accept any amount and quietly
# park whatever exceeded the invoiced total as "tenant credit", which is how the
# dashboard ended up showing more collected than was ever invoiced and why
# receipts came out carrying negative lines.
#
# The rule, enforced from here on:
#
#     every confirmed payment is fully allocated to invoice line items
#     => recorded payments can never exceed what has been invoiced
#
# An advance is NOT an exception. If a tenant pays January through December in
# January, only January is invoiced, so only January is recorded; the rest is
# money in the landlord's M-Pesa account that gets recorded month by month as
# each month is invoiced. Nothing is lost — it simply is not *recorded* before
# there is a charge to record it against.
#
# Credit already held from before this rule still drains normally against new
# invoices (services/allocation_service.apply_tenant_credit), so historical
# balances are untouched — only NEW over-invoice recording is refused.

class ExceedsInvoiced(ApiError):
    """A payment is bigger than what the tenant has actually been invoiced."""

    def __init__(self, message: str, errors: dict | None = None):
        super().__init__(message, status=422, code="exceeds_invoiced", errors=errors)


def outstanding_invoiced(tenant) -> "Decimal":
    """
    What this tenant has been invoiced and still owes: the sum of `remaining`
    over every open line item on a live, non-void invoice. This is the ceiling
    on what may be recorded as paid for them right now.
    """
    from decimal import Decimal
    from services.allocation_service import outstanding_line_items

    total = Decimal("0.00")
    for li in outstanding_line_items(tenant):
        total += Decimal(str(li.remaining or 0))
    return total


def assert_within_invoiced(tenant, amount, *, what: str = "payment") -> "Decimal":
    """
    Refuse to record `amount` for `tenant` when it exceeds their outstanding
    invoiced total. Returns that outstanding total when the amount fits.

    The message names the two figures and the fix, because "invalid amount" sends
    somebody hunting for a bug that is not there — the amount is fine, there is
    just nothing invoiced to put it against.
    """
    from decimal import Decimal

    amount = Decimal(str(amount or 0))
    outstanding = outstanding_invoiced(tenant)
    if amount <= outstanding:
        return outstanding

    excess = (amount - outstanding).quantize(Decimal("0.01"))
    name = f"{tenant.first_name} {tenant.last_name}".strip() if tenant else "this tenant"
    if outstanding <= 0:
        detail = f"{name} has nothing invoiced and outstanding right now."
    else:
        detail = (f"{name} has only KES {outstanding:,.2f} invoiced and outstanding, "
                  f"so KES {excess:,.2f} of this would not belong to any invoice.")
    raise ExceedsInvoiced(
        f"This {what} of KES {amount:,.2f} is more than has been invoiced. {detail} "
        "Raise the invoice for the period being paid for, then record the payment "
        "against it. Money paid ahead is recorded as each month is invoiced.",
        errors={"amount": "exceeds the invoiced total",
                "outstanding_invoiced": f"{outstanding:.2f}",
                "excess": f"{excess:.2f}"},
    )
