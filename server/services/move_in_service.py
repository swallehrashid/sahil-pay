"""
services/move_in_service.py — billing a tenant the day they move in.

THE KENYAN MONTH-END MOVE-IN
----------------------------
A tenant takes a unit on the 28th of September. They pay, that day, the
deposit, the lease agreement fee and OCTOBER's rent — nobody charges a full
month for the last three days of September, and many landlords do not charge
those days at all. The tenant wants a receipt that says "Rent — October 2026",
dated the day they paid.

Before this, the system could not say that. The only ways to take the money
were an invoice dated September with a bare "Rent" line — which then read as
September's rent on the receipt, while the 1st-of-October run billed October's
rent AGAIN — or leaving the money as unexplained credit.

WHAT THIS DOES
--------------
One MOVE-IN invoice, issued on the move-in date, whose lines each say which
month they are for (InvoiceLineItem.period_month):

    Rent Deposit                  (dated the first rent month)
    Lease Agreement               (no month — a one-off fee)
    Rent — October 2026           (period_month = 2026-10-01)
    Rent — 28–30 Sep 2026         (optional pro-rata for the move-in month)

and sets the lease start to the first rent month if none was given.

On 1 October the monthly run sees October's rent already exists and does not
bill it again (tasks.invoice_tasks._months_already_billed); anything else due
that month — a queued meter reading, an unpaid balance — is still billed. From
November the tenant is on the normal monthly cycle.

THE QUEUE IS NOT THE ANSWER HERE
--------------------------------
The invoice queue holds charges whose amount is not known until month end
(meter readings) or that wait for approval, and it bills them on the NEXT
invoice. Queueing October's rent would mean the tenant pays on the 28th and
gets no receipt for it until the queue is consumed on the 1st — the opposite of
what they asked for.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from extensions import db
from utils import ApiError, gen_reference

Z = Decimal("0")
# From this day of the month on, a new tenant's first FULL rent month is next
# month by default. Ten days or fewer left in the month is the common Kenyan
# cut-off; the landlord can always pick the month themselves.
NEXT_MONTH_FROM_DAY = 20


def _first(d: date) -> date:
    return date(d.year, d.month, 1)


def _next_month(d: date) -> date:
    return date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def suggested_first_rent_month(move_in: date) -> date:
    return _next_month(move_in) if move_in.day >= NEXT_MONTH_FROM_DAY else _first(move_in)


def prorated_rent(rent: Decimal, move_in: date) -> tuple[Decimal, int, int]:
    """(amount, days charged, days in month) for the rest of the move-in month."""
    days_in_month = calendar.monthrange(move_in.year, move_in.month)[1]
    days = days_in_month - move_in.day + 1
    amount = (Decimal(rent) * days / days_in_month).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return amount, days, days_in_month


def _category(landlord_id: int, name: str):
    from models import ChargeCategory
    return (ChargeCategory.query
            .filter(ChargeCategory.landlord_id == landlord_id,
                    db.func.lower(ChargeCategory.name) == name.lower())
            .order_by(ChargeCategory.is_default.desc(), ChargeCategory.id.asc())
            .first())


def preview(tenant, options: dict) -> dict:
    """What bill_move_in() would create, without creating it."""
    return _plan(tenant, options)


def _plan(tenant, options: dict) -> dict:
    from services import line_period as lp

    unit = tenant.unit
    if unit is None:
        raise ApiError("This tenant has no unit.", status=400)
    move_in = tenant.move_in_date or date.today()
    first_month = lp.parse_month(options.get("first_rent_month")) or suggested_first_rent_month(move_in)
    if first_month < _first(move_in):
        raise ApiError("The first rent month cannot be before the move-in month.", status=400)
    rent = Decimal(str(options.get("rent_amount") or unit.rent_amount or 0))

    rent_cat = _category(tenant.landlord_id, "Rent")
    lease_cat = _category(tenant.landlord_id, "Lease Agreement")
    lines: list[dict] = []

    if options.get("prorate_move_in_month") and first_month > _first(move_in) and rent > 0:
        amount, days, _dim = prorated_rent(rent, move_in)
        last = calendar.monthrange(move_in.year, move_in.month)[1]
        if amount > 0:
            lines.append({
                "item": "Rent",
                "description": f"Pro-rata {move_in.day}–{last} {move_in:%b %Y} ({days} days)",
                "amount": amount, "category_id": rent_cat.id if rent_cat else None,
                "subcategory": "current", "period_month": _first(move_in),
            })

    if options.get("include_first_rent", True) and rent > 0:
        lines.append({
            "item": "Rent", "description": f"Rent for {lp.month_label(first_month)}",
            "amount": rent, "category_id": rent_cat.id if rent_cat else None,
            "subcategory": "current", "period_month": first_month,
        })

    deposit = options.get("deposit_amount")
    if deposit is None:
        deposit = tenant.deposit_amount
    deposit = Decimal(str(deposit or 0))
    if deposit > 0:
        lines.append({
            "item": "Rent Deposit", "description": "Refundable deposit",
            "amount": deposit, "category_id": rent_cat.id if rent_cat else None,
            "subcategory": "deposit", "period_month": first_month,
        })

    lease_fee = Decimal(str(options.get("lease_fee") or 0))
    if lease_fee > 0:
        lines.append({
            "item": "Lease Agreement", "description": "Tenancy agreement fee",
            "amount": lease_fee, "category_id": lease_cat.id if lease_cat else None,
            "subcategory": "current", "period_month": None,
        })

    for extra in options.get("extra_lines") or []:
        amount = Decimal(str(extra.get("amount") or 0))
        if amount <= 0 or not extra.get("item"):
            continue
        lines.append({
            "item": str(extra["item"])[:120], "description": extra.get("description"),
            "amount": amount, "category_id": extra.get("category_id"),
            "subcategory": extra.get("subcategory") or "current",
            "period_month": lp.parse_month(extra.get("month")) or first_month,
        })

    return {
        "move_in_date": move_in.isoformat(),
        "first_rent_month": first_month.isoformat(),
        "first_rent_month_label": lp.month_label(first_month),
        "lines": [{**l, "amount": float(l["amount"]),
                   "period_month": l["period_month"].isoformat() if l["period_month"] else None,
                   "month_label": lp.month_label(l["period_month"])} for l in lines],
        "total": float(sum((l["amount"] for l in lines), Z)),
        "_lines": lines,
        "_first_month": first_month,
    }


def bill_move_in(tenant, options: dict, *, actor_user_id=None):
    """
    Create the move-in invoice for *tenant*. Returns the Invoice, or None when
    there is nothing to bill. Refuses to bill the same tenant twice. Flushes;
    the caller commits.
    """
    from models import Invoice, InvoiceLineItem, InvoiceType, LineItemStatus
    from services.audit_service import record_audit
    from services.allocation_service import apply_tenant_credit

    existing = Invoice.query.filter_by(tenant_id=tenant.id, is_deleted=False,
                                       invoice_type=InvoiceType.move_in.value).first()
    if existing is not None:
        raise ApiError(f"{tenant.first_name} already has a move-in invoice "
                       f"({existing.invoice_number}).", status=409)

    plan = _plan(tenant, options)
    lines = plan["_lines"]
    if not lines:
        return None

    first_month = plan["_first_month"]
    if tenant.lease_start_date is None:
        tenant.lease_start_date = first_month

    move_in = tenant.move_in_date or date.today()
    total = sum((l["amount"] for l in lines), Z)
    invoice = Invoice(
        invoice_number=gen_reference("INV"),
        landlord_id=tenant.landlord_id,
        tenant_id=tenant.id,
        unit_id=tenant.unit_id,
        property_id=tenant.unit.property_id,
        invoice_type=InvoiceType.move_in.value,
        issue_date=move_in,
        due_date=move_in,
        status="open",
        total_amount=total, amount_paid=Z, balance=total,
        title=f"Move-in — first rent month {plan['first_rent_month_label']}",
    )
    db.session.add(invoice)
    db.session.flush()
    for l in lines:
        db.session.add(InvoiceLineItem(
            invoice_id=invoice.id, item=l["item"], description=l.get("description"),
            quantity=Decimal("1"), unit_price=l["amount"], amount=l["amount"],
            category_id=l.get("category_id"), subcategory=l.get("subcategory"),
            amount_paid=Z, status=LineItemStatus.open.value,
            period_month=l.get("period_month"),
        ))
    # New debt makes the running balance more negative (see models.py).
    tenant.balance = Decimal(str(tenant.balance or 0)) - total
    db.session.flush()

    landlord = tenant.landlord
    apply_tenant_credit(tenant, landlord, ref_date=move_in)

    record_audit(actor_user_id, tenant.landlord_id, "move_in_invoice", "invoice", invoice.id,
                 f"Move-in invoice {invoice.invoice_number} for {tenant.first_name} "
                 f"{tenant.last_name}: first rent month {plan['first_rent_month_label']}, "
                 f"KES {total:,.2f}.")
    return invoice
