"""
services/line_period.py — which MONTH a charge is for, and what a payment paid.

A receipt that says "Rent  KES 20,000" does not tell a tenant which rent. A
tenant who is two months behind and pays one month needs to see "Rent — August
2026" on the receipt, and "Rent — September 2026 still owed" under it; a tenant
who moves in on the 28th and pays October up front needs "Rent — October 2026"
on a receipt dated in September. Every charge except a one-off lease agreement
fee is FOR a month, so every receipt line says which one.

WHERE THE MONTH COMES FROM, in order:
  1. line.period_month      set explicitly (move-in billing of a future month)
  2. the meter reading      "Water" billed on 1 Oct for the September reading
  3. the rollover trail     a "Rent Balance b/f" line is several months of old
                            debt; BalanceRollover records each origin month
  4. the invoice's month    everything else

A carried balance is split OLDEST-FIRST. If it holds 5,000 from July and 20,000
from August and a payment of 8,000 lands on it, the receipt reads "Rent — July
2026: 5,000" and "Rent — August 2026: 3,000" — and a later payment continues
from where that one stopped. This is the same oldest-first order the billing
engine uses to decide what is still owed (tasks.invoice_tasks._unpaid_components),
so the receipt and the next month's rollover can never disagree.

POINT IN TIME
-------------
A receipt is a record of one moment. Re-downloading August's receipt in
November must print what was true in August, not today's balances. So nothing
here reads `line.amount_paid` for a receipt: it replays the allocations up to
and including the payment being receipted (PaymentAllocation ids only ever
grow), and treats a line as rolled only if it was rolled by then.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

Z = Decimal("0")


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

def first_of(d: date | None) -> date | None:
    return date(d.year, d.month, 1) if d else None


def month_label(d: date | None) -> str:
    return d.strftime("%B %Y") if d else ""


def parse_month(value) -> date | None:
    """'2026-10', '2026-10-01', a date — to the 1st of that month."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return first_of(value)
    text = str(value).strip()
    try:
        year, month = int(text[0:4]), int(text[5:7])
        return date(year, month, 1)
    except (TypeError, ValueError, IndexError):
        return None


def is_undated(li) -> bool:
    """
    A charge with no month: the lease agreement fee, paid once for the tenancy.

    Recognised by category name first (the default "Lease Agreement" category),
    then by the line's own wording, so an older uncategorised line still reads
    right.
    """
    cat = getattr(li, "category", None)
    name = (getattr(cat, "name", None) or "").strip().lower()
    if name in ("lease agreement", "lease", "lease fee", "agreement fee"):
        return True
    return "lease agreement" in (li.item or "").lower()


def base_label(li) -> str:
    """The charge name without any month: 'Rent', 'Water', 'Rent Deposit', 'Rent Balance'."""
    cat = getattr(li, "category", None)
    sub = li.subcategory
    if cat is not None and sub:
        if sub == "balance":
            # "Rent Balance b/f" reads oddly once a month is attached to it:
            # "Rent — August 2026" is what the tenant is paying off.
            return cat.name
        return cat.subcategory_display().get(sub, li.item)
    text = li.item or "Charge"
    for suffix in (" Balance b/f", " balance b/f", " b/f"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _reading_month(li) -> date | None:
    reading = getattr(li, "utility_reading", None)
    return parse_month(reading.reading_month) if reading is not None else None


def line_month(li) -> date | None:
    """The month a single-month line is for (current, deposit, one-off)."""
    if is_undated(li):
        return None
    if li.period_month:
        return first_of(li.period_month)
    rm = _reading_month(li)
    if rm:
        return rm
    inv = li.invoice
    return first_of(inv.issue_date) if inv is not None and inv.issue_date else None


def components(li) -> list[tuple[date | None, Decimal]]:
    """
    What the line is made of, oldest first, as [(month, amount)].

    A balance-b/f line is its rollover trail; anything else is one component.
    """
    if li.subcategory == "balance":
        from models import BalanceRollover
        rows = (
            BalanceRollover.query
            .filter_by(target_line_item_id=li.id)
            .order_by(BalanceRollover.origin_month.asc(), BalanceRollover.id.asc())
            .all()
        )
        if rows:
            comps = [(first_of(r.origin_month), Decimal(r.amount or 0)) for r in rows]
            # A balance line whose amount was edited after it was created no
            # longer sums to its trail; the difference belongs to the newest month.
            gap = Decimal(li.amount or 0) - sum((a for _, a in comps), Z)
            if gap > 0:
                comps[-1] = (comps[-1][0], comps[-1][1] + gap)
            return comps
    return [(line_month(li), Decimal(li.amount or 0))]


def slice_components(comps, already_paid: Decimal, amount: Decimal):
    """
    The part of `comps` that `amount` covers, once `already_paid` has been
    taken off the oldest end. Returns [(month, amount)] with no zero rows.
    """
    out = []
    skip, take = Decimal(already_paid or 0), Decimal(amount or 0)
    for month, size in comps:
        if take <= 0:
            break
        if skip >= size:
            skip -= size
            continue
        room = size - skip
        skip = Z
        portion = min(room, take)
        if portion > 0:
            out.append((month, portion))
            take -= portion
    if take > 0:                       # rounding / edited line: keep the money visible
        out.append((comps[-1][0] if comps else None, take))
    return out


def label(li, month: date | None) -> str:
    base = base_label(li)
    return f"{base} — {month_label(month)}" if month else base


# ---------------------------------------------------------------------------
# A payment, replayed
# ---------------------------------------------------------------------------

def _allocations_upto(line_ids, cutoff_alloc_id: int):
    """{line_id: total allocated by allocations with id <= cutoff} from confirmed payments."""
    from extensions import db
    from models import Payment, PaymentAllocation, PaymentStatus

    if not line_ids:
        return {}
    rows = (
        db.session.query(PaymentAllocation.line_item_id,
                         db.func.coalesce(db.func.sum(PaymentAllocation.amount_allocated), 0))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .filter(PaymentAllocation.line_item_id.in_(list(line_ids)),
                PaymentAllocation.id <= cutoff_alloc_id,
                Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value)
        .group_by(PaymentAllocation.line_item_id)
        .all()
    )
    return {lid: Decimal(total or 0) for lid, total in rows}


def paid_lines(payment) -> list[dict]:
    """
    Every charge this payment paid, split by month, oldest first.

    [{line_item_id, invoice_number, group, label, base, month, amount, is_deposit}]
    """
    from models import PaymentAllocation

    allocs = sorted(payment.payment_allocations, key=lambda a: a.id or 0)
    allocs = [a for a in allocs if a.line_item_id is not None and a.line_item is not None]
    if not allocs:
        return []

    first_id = allocs[0].id
    before = _allocations_upto({a.line_item_id for a in allocs}, first_id - 1)
    # Allocations of THIS payment to the same line (merged by apply_allocations,
    # but be safe) must stack, not each start from the same offset.
    running = dict(before)

    out = []
    for a in allocs:
        li = a.line_item
        amount = Decimal(a.amount_allocated or 0)
        if amount <= 0:
            continue
        offset = running.get(li.id, Z)
        running[li.id] = offset + amount
        for month, portion in slice_components(components(li), offset, amount):
            out.append(_row(li, month, portion))
    return _merge_same(out)


def _group_of(li) -> str:
    from models import ChargeCategoryKind
    cat = li.category
    if li.subcategory == "deposit" or (cat is None and "deposit" in (li.item or "").lower()):
        return "deposits"
    if cat is not None and cat.kind == ChargeCategoryKind.utility.value:
        return "utilities"
    if cat is not None and (cat.name or "").strip().lower() == "rent":
        return "rent"
    return "other"


def _row(li, month, amount) -> dict:
    inv = li.invoice
    return {
        "line_item_id":   li.id,
        "invoice_number": inv.invoice_number if inv is not None else None,
        "group":          _group_of(li),
        "base":           base_label(li),
        "month":          month.isoformat() if month else None,
        "month_label":    month_label(month),
        "label":          label(li, month),
        "amount":         amount,
        "is_deposit":     li.subcategory == "deposit",
    }


def _merge_same(rows: list[dict]) -> list[dict]:
    """One row per (charge, month): two lines for 'Rent — August' read as a mistake."""
    merged: dict[tuple, dict] = {}
    order = []
    for r in rows:
        key = (r["base"], r["month"], r["group"])
        if key in merged:
            merged[key]["amount"] += r["amount"]
        else:
            merged[key] = dict(r)
            order.append(key)
    result = [merged[k] for k in order]
    result.sort(key=lambda r: (r["month"] or "9999", _GROUP_ORDER.get(r["group"], 9), r["base"]))
    return result


_GROUP_ORDER = {"rent": 0, "utilities": 1, "other": 2, "deposits": 3}


def outstanding_after(payment) -> list[dict]:
    """
    What the tenant still owed straight after this payment, by charge and month.

    Replays the ledger to that moment: lines that existed then, less every
    allocation up to and including this payment's last one, skipping lines that
    had already been rolled into a newer balance line by then (their debt is on
    that newer line, and counting both would double it).
    """
    from models import (BalanceRollover, Invoice, InvoiceLineItem, InvoiceStatus,
                        PaymentAllocation)
    from extensions import db

    tenant_id = payment.tenant_id
    if tenant_id is None:
        return []

    alloc_ids = [a.id for a in payment.payment_allocations if a.id is not None]
    cutoff_alloc = max(alloc_ids) if alloc_ids else (
        db.session.query(db.func.coalesce(db.func.max(PaymentAllocation.id), 0)).scalar() or 0
    )
    stamps = [a.created_at for a in payment.payment_allocations if a.created_at]
    cutoff_time = max(stamps) if stamps else (payment.updated_at or payment.created_at)

    lines = (
        InvoiceLineItem.query
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .filter(Invoice.tenant_id == tenant_id,
                Invoice.is_deleted.is_(False),
                Invoice.status != InvoiceStatus.void.value)
        .all()
    )
    if cutoff_time is not None:
        lines = [li for li in lines if li.created_at is None or li.created_at <= cutoff_time]
    if not lines:
        return []

    ids = {li.id for li in lines}
    # A line counts as rolled at the cutoff only if the balance line that took
    # it already existed then.
    rolled_by_then = set()
    rollovers = (
        db.session.query(BalanceRollover.source_line_item_id, InvoiceLineItem.created_at)
        .join(InvoiceLineItem, InvoiceLineItem.id == BalanceRollover.target_line_item_id)
        .filter(BalanceRollover.source_line_item_id.in_(list(ids)))
        .all()
    )
    for source_id, target_created in rollovers:
        if cutoff_time is None or target_created is None or target_created <= cutoff_time:
            rolled_by_then.add(source_id)

    paid = _allocations_upto(ids, cutoff_alloc)
    out = []
    for li in lines:
        if li.id in rolled_by_then:
            continue
        owed = Decimal(li.amount or 0) - paid.get(li.id, Z)
        if owed <= 0:
            continue
        already = paid.get(li.id, Z)
        comps = components(li)
        total = sum((a for _, a in comps), Z)
        for month, portion in slice_components(comps, already, total - already):
            out.append(_row(li, month, portion))
    return _merge_same(out)


def credit_note(payment) -> str | None:
    """
    What an advance is for, in words a tenant understands — "held for your
    October 2026 rent" — rather than a bare "credit".
    """
    from models import Tenant
    tenant = payment.tenant if payment.tenant_id else None
    if tenant is None:
        return None
    ref = payment.payment_date or date.today()
    nxt = date(ref.year + (ref.month // 12), ref.month % 12 + 1, 1)
    return f"Held on your account and applied to your next bill ({month_label(nxt)})."
