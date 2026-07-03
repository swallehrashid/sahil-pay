"""
services/allocation_service.py — Payment → invoice allocation.

When a landlord confirms a tenant's submitted payment they choose:
  • manual — they pass explicit {invoice_id, amount_allocated} rows, or
  • auto   — the amount is spread across the tenant's outstanding invoices in
             the landlord's configured category priority order.

Categories (each an outstanding-invoice bucket):
    utilities_cf      — utility invoices from a prior month (balance carried forward)
    utilities_current — utility invoices issued in the current month
    rent_cf           — rent invoices from a prior month (balance carried forward)
    rent_current      — rent invoices issued in the current month
    other             — penalty / custom / recurring invoices

Default priority (spec): clear utility arrears first, then this month's
utilities, then rent arrears, then this month's rent, then everything else.
The landlord can reorder these in Settings → Payments (Landlord.allocation_priority,
a CSV of the keys below). Within a bucket, oldest issue_date is cleared first.

Every function here FLUSHES but never commits — the caller owns the transaction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from extensions import db
from models import Invoice, InvoiceStatus, InvoiceType, PaymentAllocation

# Ordered canonical category list == the default priority.
ALLOCATION_CATEGORIES = [
    "utilities_cf",
    "utilities_current",
    "rent_cf",
    "rent_current",
    "other",
]

CATEGORY_LABELS = {
    "utilities_cf":      "Utilities — balance carried forward",
    "utilities_current": "Utilities — current month",
    "rent_cf":           "Rent — balance carried forward",
    "rent_current":      "Rent — current month",
    "other":             "Other charges (penalties, custom)",
}

DEFAULT_ALLOCATION_PRIORITY = list(ALLOCATION_CATEGORIES)


def get_allocation_priority(landlord) -> list[str]:
    """Landlord's configured order, defaulting + backfilling any missing keys."""
    raw = (getattr(landlord, "allocation_priority", None) or "").strip()
    order = [k.strip() for k in raw.split(",") if k.strip() in ALLOCATION_CATEGORIES]
    # Append any categories the landlord didn't list so nothing is un-allocatable.
    for key in ALLOCATION_CATEGORIES:
        if key not in order:
            order.append(key)
    return order


def _invoice_balance(inv) -> Decimal:
    paid = inv.amount_paid or Decimal("0")
    return (inv.total_amount or Decimal("0")) - paid


def categorize_invoice(inv, ref_date: date) -> str:
    """Map an invoice to one of ALLOCATION_CATEGORIES."""
    issue = inv.issue_date or ref_date
    is_current = (issue.year == ref_date.year and issue.month == ref_date.month)
    itype = inv.invoice_type

    if itype == InvoiceType.utility.value:
        return "utilities_current" if is_current else "utilities_cf"
    if itype == InvoiceType.rent.value:
        return "rent_current" if is_current else "rent_cf"
    return "other"


def outstanding_invoices(tenant) -> list:
    """Tenant's non-deleted invoices with a positive remaining balance."""
    invs = [
        inv for inv in tenant.invoices
        if not inv.is_deleted and _invoice_balance(inv) > 0
    ]
    return invs


def auto_allocate(tenant, amount: Decimal, landlord, ref_date: date | None = None) -> list[dict]:
    """
    Spread `amount` across outstanding invoices in the landlord's priority order.
    Returns a list of {invoice_id, amount_allocated} (Decimals). Does not mutate
    anything — pass the result to apply_allocations().
    """
    ref_date = ref_date or date.today()
    remaining = Decimal(str(amount))
    priority = get_allocation_priority(landlord)

    # Bucket outstanding invoices by category.
    buckets: dict[str, list] = {k: [] for k in ALLOCATION_CATEGORIES}
    for inv in outstanding_invoices(tenant):
        buckets[categorize_invoice(inv, ref_date)].append(inv)

    allocations: list[dict] = []
    for category in priority:
        if remaining <= 0:
            break
        # Oldest first within a bucket.
        for inv in sorted(buckets.get(category, []), key=lambda i: (i.issue_date or ref_date, i.id)):
            if remaining <= 0:
                break
            bal = _invoice_balance(inv)
            if bal <= 0:
                continue
            take = min(remaining, bal)
            allocations.append({"invoice_id": inv.id, "amount_allocated": take})
            remaining -= take

    return allocations


def apply_allocations(payment, tenant, allocations: list[dict], landlord_id: int) -> Decimal:
    """
    Persist PaymentAllocation rows and update each invoice's amount_paid / balance /
    status. Returns the total amount actually allocated (remainder is advance credit).
    Flushes; caller commits.
    """
    total_allocated = Decimal("0")
    for alloc in allocations:
        inv_id = alloc.get("invoice_id")
        alloc_amt = Decimal(str(alloc.get("amount_allocated", 0)))
        if not inv_id or alloc_amt <= 0:
            continue
        inv = Invoice.query.filter_by(id=inv_id, landlord_id=landlord_id, is_deleted=False).first()
        if not inv:
            continue

        db.session.add(PaymentAllocation(
            payment_id=payment.id, invoice_id=inv.id, amount_allocated=alloc_amt,
        ))
        inv.amount_paid = (inv.amount_paid or Decimal("0")) + alloc_amt
        inv.balance = (inv.total_amount or Decimal("0")) - inv.amount_paid
        if inv.balance <= 0:
            inv.status = InvoiceStatus.paid.value
        elif inv.amount_paid > 0:
            inv.status = InvoiceStatus.partial.value
        else:
            inv.status = InvoiceStatus.open.value
        total_allocated += alloc_amt

    db.session.flush()
    return total_allocated
