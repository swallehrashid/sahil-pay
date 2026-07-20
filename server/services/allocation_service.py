"""
services/allocation_service.py — Payment → invoice-LINE allocation engine.

Charge-category restructure (CATEGORY_RESTRUCTURE_SPEC.md §2). Money is allocated
to individual invoice LINE ITEMS, because each line belongs to a (category,
subcategory) pair and the reports/rollover depend on knowing exactly which
subcategory each shilling cleared.

When a landlord records/confirms a payment they choose:
  • auto   — the amount cascades through the tenant's outstanding line items in the
             landlord's configured (category, subcategory) priority order; within a
             bucket, oldest issue_date first ("oldest debt first").
  • manual — they pass explicit {line_item_id, amount} rows (one screen listing all
             outstanding items). Legacy {invoice_id, amount_allocated} rows are still
             accepted and expanded across that invoice's lines until the UI is reworked.

Any un-allocated remainder becomes tenant CREDIT (advance), tracked in credit_ledger
+ Tenant.credit_balance, and consumed first by the next auto-allocation / monthly bill.

Ledger convention: Tenant.balance moves by the ALLOCATED amount (owed-positive is
negative here, matching the rest of the app); unallocated cash sits in credit_balance,
NOT in balance, so nothing is double-counted. Applying credit later moves it from
credit_balance into balance.

Every function FLUSHES but never commits — the caller owns the transaction.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from extensions import db
from models import (
    ChargeCategory, CreditLedger, Invoice, InvoiceLineItem, InvoiceStatus,
    LineItemStatus, Payment, PaymentAllocation, PaymentStatus, PaymentSource,
    SubCategory,
)

# Kenya default priority grouping (spec §1.6): clear oldest arrears first, then
# deposits, then this month's charges. Within a group, by category creation order.
_DEFAULT_SUBCATEGORY_ORDER = [
    SubCategory.balance.value,
    SubCategory.deposit.value,
    SubCategory.current.value,
]

_ZERO = Decimal("0")


def _D(value) -> Decimal:
    return Decimal(str(value or 0))


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

def _pair_key(category_id: int, subcategory: str) -> str:
    return f"{category_id}:{subcategory}"


def _parse_pair_key(key: str) -> tuple[int, str] | None:
    try:
        cid, sub = key.split(":", 1)
        cid = int(cid)
    except (ValueError, AttributeError):
        return None
    if sub not in (s.value for s in SubCategory):
        return None
    return (cid, sub)


def allocation_priority_pairs(landlord) -> list[tuple[int, str]]:
    """
    The landlord's ordered (category_id, subcategory) allocation priority.

    Reads Landlord.allocation_priority_json (list of "<category_id>:<subcategory>"),
    keeps only pairs of the landlord's ACTIVE categories, then backfills any missing
    active pairs in the Kenya default order (all balances → all deposits → all
    currents, by category creation order). Inactive categories are skipped for AUTO
    allocation (their invoices stay manually payable).
    """
    cats = (
        ChargeCategory.query
        .filter_by(landlord_id=landlord.id, is_active=True)
        .order_by(ChargeCategory.id.asc())
        .all()
    )
    valid = {_pair_key(c.id, s): (c.id, s)
             for c in cats for s in (x.value for x in SubCategory)}

    order: list[tuple[int, str]] = []
    seen: set[str] = set()

    raw = (getattr(landlord, "allocation_priority_json", None) or "").strip()
    if raw:
        try:
            stored = json.loads(raw)
        except (ValueError, TypeError):
            stored = []
        for key in stored:
            if key in valid and key not in seen:
                order.append(valid[key])
                seen.add(key)

    # Backfill missing pairs: balance → deposit → current, category id asc.
    for sub in _DEFAULT_SUBCATEGORY_ORDER:
        for c in cats:
            key = _pair_key(c.id, sub)
            if key not in seen:
                order.append((c.id, sub))
                seen.add(key)

    return order


def priority_pairs_labeled(landlord) -> list[dict]:
    """The priority list with display labels — for the settings editor / preview."""
    cats = {c.id: c for c in ChargeCategory.query.filter_by(landlord_id=landlord.id).all()}
    out = []
    for cid, sub in allocation_priority_pairs(landlord):
        cat = cats.get(cid)
        if not cat:
            continue
        out.append({
            "key":           _pair_key(cid, sub),
            "category_id":   cid,
            "category_name": cat.name,
            "kind":          cat.kind,
            "subcategory":   sub,
            "label":         cat.subcategory_display()[sub],
        })
    return out


# ---------------------------------------------------------------------------
# Outstanding line items
# ---------------------------------------------------------------------------

def outstanding_line_items(tenant) -> list[InvoiceLineItem]:
    """
    Every line item the tenant still owes on: status 'open', positive remaining, on a
    non-deleted, non-void invoice. Rolled lines are excluded by status.

    Queries invoices directly (not tenant.invoices) so freshly-flushed invoices in the
    same transaction are seen — the monthly rollover task creates invoices and then
    applies credit within one session.
    """
    if not tenant:
        return []
    invs = (
        Invoice.query
        .filter_by(tenant_id=tenant.id, is_deleted=False)
        .filter(Invoice.status != InvoiceStatus.void.value)
        .all()
    )
    items: list[InvoiceLineItem] = []
    for inv in invs:
        for li in inv.line_items:
            if li.status == LineItemStatus.open.value and li.remaining > 0:
                items.append(li)
    return items


def _bucket_key(li: InvoiceLineItem) -> str | None:
    if li.category_id is None or li.subcategory is None:
        return None
    return _pair_key(li.category_id, li.subcategory)


# ---------------------------------------------------------------------------
# Auto allocation (returns rows; does not mutate)
# ---------------------------------------------------------------------------

def auto_allocate(tenant, amount, landlord, ref_date: date | None = None) -> list[dict]:
    """
    Spread `amount` across the tenant's outstanding line items in the landlord's
    (category, subcategory) priority order, oldest issue_date first within a bucket.
    Returns [{line_item_id, invoice_id, amount_allocated}] (Decimals). Non-mutating —
    feed the result to apply_allocations().
    """
    ref_date = ref_date or date.today()
    remaining = _D(amount)
    if remaining <= 0:
        return []

    # Bucket outstanding lines by (category, subcategory).
    buckets: dict[str, list[InvoiceLineItem]] = {}
    unbucketed: list[InvoiceLineItem] = []
    for li in outstanding_line_items(tenant):
        key = _bucket_key(li)
        if key is None:
            unbucketed.append(li)
        else:
            buckets.setdefault(key, []).append(li)

    def _line_sort(li: InvoiceLineItem):
        issue = li.invoice.issue_date if li.invoice else None
        return (issue or ref_date, li.id)

    allocations: list[dict] = []

    def _drain(lines: list[InvoiceLineItem]):
        nonlocal remaining
        for li in sorted(lines, key=_line_sort):
            if remaining <= 0:
                break
            take = min(remaining, li.remaining)
            if take <= 0:
                continue
            allocations.append({
                "line_item_id":    li.id,
                "invoice_id":      li.invoice_id,
                "amount_allocated": take,
            })
            remaining -= take

    for cid, sub in allocation_priority_pairs(landlord):
        if remaining <= 0:
            break
        _drain(buckets.get(_pair_key(cid, sub), []))

    # Lines with no category yet (legacy / not-stamped) still get paid, last.
    if remaining > 0 and unbucketed:
        _drain(unbucketed)

    return allocations


# ---------------------------------------------------------------------------
# Manual allocation normalisation
# ---------------------------------------------------------------------------

def normalize_manual_allocations(rows: list[dict], tenant, landlord,
                                 ref_date: date | None = None) -> list[dict]:
    """
    Turn incoming manual rows into canonical line-level rows.
      • {line_item_id, amount|amount_allocated}  → used directly (preferred).
      • {invoice_id, amount_allocated}           → legacy: expanded across that
        invoice's outstanding lines (subcategory priority, oldest first) until the
        row's amount is used up. Kept working until the record-payment UI is reworked.
    Validates each amount is > 0 and ≤ the line's remaining balance.
    """
    ref_date = ref_date or date.today()
    line_by_id = {li.id: li for li in outstanding_line_items(tenant)}
    result: list[dict] = []
    used: dict[int, Decimal] = {}

    def _remaining(li: InvoiceLineItem) -> Decimal:
        return li.remaining - used.get(li.id, _ZERO)

    def _add(li: InvoiceLineItem, amt: Decimal):
        amt = min(amt, _remaining(li))
        if amt <= 0:
            return
        result.append({
            "line_item_id":     li.id,
            "invoice_id":       li.invoice_id,
            "amount_allocated": amt,
        })
        used[li.id] = used.get(li.id, _ZERO) + amt

    # Priority order used to expand legacy invoice-level rows deterministically.
    pair_rank = {_pair_key(c, s): i
                 for i, (c, s) in enumerate(allocation_priority_pairs(landlord))}

    for row in rows or []:
        amt = _D(row.get("amount") if row.get("amount") is not None
                 else row.get("amount_allocated"))
        if amt <= 0:
            continue

        if row.get("line_item_id") is not None:
            li = line_by_id.get(int(row["line_item_id"]))
            if li is not None:
                _add(li, amt)
            continue

        inv_id = row.get("invoice_id")
        if inv_id is None:
            continue
        inv_lines = [li for li in line_by_id.values() if li.invoice_id == int(inv_id)]
        inv_lines.sort(key=lambda li: (
            pair_rank.get(_bucket_key(li), 9_999),
            li.invoice.issue_date if li.invoice else ref_date,
            li.id,
        ))
        rem = amt
        for li in inv_lines:
            if rem <= 0:
                break
            take = min(rem, _remaining(li))
            if take <= 0:
                continue
            _add(li, take)
            rem -= take

    return result


# ---------------------------------------------------------------------------
# Applying allocations
# ---------------------------------------------------------------------------

def recompute_invoice(inv: Invoice) -> None:
    """Recompute an invoice header from its line items (rolled lines excluded from balance)."""
    amount_paid = sum((li.amount_paid or _ZERO for li in inv.line_items), _ZERO)
    open_balance = sum(
        (li.remaining for li in inv.line_items if li.status != LineItemStatus.rolled.value),
        _ZERO,
    )
    inv.amount_paid = amount_paid
    inv.balance = open_balance
    if inv.status == InvoiceStatus.void.value:
        return
    if open_balance <= 0 and (inv.total_amount or _ZERO) > 0:
        inv.status = InvoiceStatus.paid.value
    elif amount_paid > 0:
        inv.status = InvoiceStatus.partial.value
    else:
        inv.status = InvoiceStatus.open.value


def apply_allocations(payment, tenant, allocations: list[dict], landlord_id: int) -> Decimal:
    """
    Persist line-level PaymentAllocation rows, bump each line's amount_paid/status,
    recompute affected invoice headers, move Tenant.balance by the allocated amount,
    and push any un-allocated remainder of the payment into tenant credit.
    Returns the total actually allocated. Flushes; caller commits.
    """
    total_allocated = _ZERO
    touched_invoices: set[int] = set()

    for alloc in allocations:
        line_id = alloc.get("line_item_id")
        amt = _D(alloc.get("amount_allocated"))
        if not line_id or amt <= 0:
            continue
        li = db.session.get(InvoiceLineItem, int(line_id))
        if li is None or li.invoice is None or li.invoice.landlord_id != landlord_id:
            continue
        if li.invoice.is_deleted:
            continue
        amt = min(amt, li.remaining)
        if amt <= 0:
            continue

        existing = PaymentAllocation.query.filter_by(
            payment_id=payment.id, line_item_id=li.id
        ).first()
        if existing:
            existing.amount_allocated = (existing.amount_allocated or _ZERO) + amt
        else:
            db.session.add(PaymentAllocation(
                payment_id=payment.id,
                invoice_id=li.invoice_id,
                line_item_id=li.id,
                amount_allocated=amt,
            ))

        li.amount_paid = (li.amount_paid or _ZERO) + amt
        if li.remaining <= 0:
            li.status = LineItemStatus.paid.value
        total_allocated += amt
        touched_invoices.add(li.invoice_id)

    for inv_id in touched_invoices:
        inv = db.session.get(Invoice, inv_id)
        if inv is not None:
            recompute_invoice(inv)

    # Ledger: allocated money reduces what's owed (owed is negative here).
    if total_allocated > 0:
        tenant.balance = _D(tenant.balance) + total_allocated

    # Remainder of a REAL payment (not a credit re-application) becomes tenant credit.
    if payment.source != PaymentSource.credit.value:
        remainder = _D(payment.amount) - total_allocated
        if remainder > 0:
            _add_credit(tenant, landlord_id, remainder, payment=payment,
                        memo=f"Advance from payment {payment.payment_ref}")

    db.session.flush()
    return total_allocated


# ---------------------------------------------------------------------------
# Tenant credit
# ---------------------------------------------------------------------------

def _add_credit(tenant, landlord_id: int, amount: Decimal, *, payment=None,
                line_item_id: int | None = None, memo: str | None = None) -> None:
    """Record a signed credit-ledger movement and keep credit_balance in sync."""
    amount = _D(amount)
    if amount == 0:
        return
    db.session.add(CreditLedger(
        landlord_id=landlord_id,
        tenant_id=tenant.id,
        amount=amount,
        payment_id=payment.id if payment else None,
        line_item_id=line_item_id,
        memo=memo,
    ))
    tenant.credit_balance = _D(tenant.credit_balance) + amount


def apply_tenant_credit(tenant, landlord, ref_date: date | None = None) -> Decimal:
    """
    Consume the tenant's held credit against their outstanding line items (same auto
    cascade). Creates ONE synthetic 'credit' payment so the applications show on
    statements, writes negative credit-ledger rows, and moves credit_balance into
    balance. Returns the amount applied. Flushes; caller commits.
    """
    ref_date = ref_date or date.today()
    credit = _D(tenant.credit_balance)
    if credit <= 0:
        return _ZERO

    allocations = auto_allocate(tenant, credit, landlord, ref_date=ref_date)
    applied = sum((_D(a["amount_allocated"]) for a in allocations), _ZERO)
    if applied <= 0:
        return _ZERO

    synthetic = Payment(
        payment_ref  = _credit_ref(landlord.id),
        landlord_id  = landlord.id,
        tenant_id    = tenant.id,
        unit_id      = tenant.unit_id,
        property_id  = tenant.unit.property_id if tenant.unit else None,
        amount       = applied,
        payment_date = ref_date,
        status       = PaymentStatus.confirmed.value,
        source       = PaymentSource.credit.value,
        notes        = "Auto-applied tenant credit",
    )
    db.session.add(synthetic)
    db.session.flush()

    apply_allocations(synthetic, tenant, allocations, landlord.id)
    # Draw the applied amount back out of the credit balance.
    _add_credit(tenant, landlord.id, -applied, payment=synthetic,
                memo="Credit applied to outstanding items")
    db.session.flush()
    return applied


def _credit_ref(landlord_id: int) -> str:
    from datetime import datetime
    n = Payment.query.filter_by(landlord_id=landlord_id).count() + 1
    return f"CR-{landlord_id}-{datetime.utcnow():%y%m%d}-{n:05d}"


# ---------------------------------------------------------------------------
# LEGACY — invoice-level categorisation, kept only for the current receipt
# builder (services/receipt_service.py). Superseded by per-line (category,
# subcategory) tagging; removed when receipts are reworked (spec §5.5 / Phase 7).
# ---------------------------------------------------------------------------

def categorize_invoice(inv, ref_date: date) -> str:
    from models import InvoiceType
    issue = inv.issue_date or ref_date
    is_current = (issue.year == ref_date.year and issue.month == ref_date.month)
    itype = inv.invoice_type
    if itype == InvoiceType.deposit.value:
        return "deposits"
    if itype == InvoiceType.utility.value:
        return "utilities_current" if is_current else "utilities_cf"
    if itype == InvoiceType.rent.value:
        return "rent_current" if is_current else "rent_cf"
    return "other"
