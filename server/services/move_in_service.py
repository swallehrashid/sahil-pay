"""
services/move_in_service.py — the move-in invoice, raised on the Add Tenant form.

ONE EDITOR, TWO KINDS OF MOVE-IN
--------------------------------
The Add Tenant form carries a normal invoice editor: pick any charge — Rent
Deposit, Rent (this month), Rent Balance, Penalty…, Water Deposit, Lease
Agreement, a custom item — and type the amounts. What differs between tenants
is only WHICH MONTH the bill is for:

  Moving in before the 20th (e.g. 15 September)
      "Bill the next month's move-in now" is left UNTICKED. The bill is for the
      move-in month: "Rent — September 2026" at whatever the landlord charges
      for the part month (say 5,000 of a 10,000 rent), plus the deposit, the
      lease fee… From 1 October the tenant pays the full rent.

  Moving in from the 20th (e.g. 26 September)
      The box is TICKED and a month chosen (October by default). The invoice is
      still raised and paid on the 26th, but EVERY line on it is FOR October:
      "Rent — October 2026", "Rent Deposit — October 2026". The receipt, the
      reports and the 1 October billing run all treat it as October's.

"Include the first month's rent" adds the Rent (this month) line, prefilled
with the unit's rent and editable. In the ticked case it is the chosen month's
rent; unticked, it is the move-in month's (usually cut down to the part month).

The Lease Agreement fee prints without a month on the receipt (a one-off), but
its line is still recorded against the billed month so reports count it there.

WHY THE MONTH IS STORED ON EACH LINE
------------------------------------
InvoiceLineItem.period_month. It is what lets the receipt say "Rent — October"
on a September invoice, what the Payments Report files the money under, and
what the monthly run checks so it never bills October's rent a second time
(tasks.invoice_tasks._months_already_billed) — nor September's, for a tenant
who was billed a part month on the 15th.

THE QUEUE IS NOT THE ANSWER HERE
--------------------------------
Queued charges wait for the NEXT invoice. A tenant paying October's rent on the
26th needs the bill, and the receipt, on the 26th.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from extensions import db
from utils import ApiError, gen_reference

Z = Decimal("0")
SUBCATEGORIES = ("deposit", "balance", "current")
# From this day on, the move-in form suggests billing NEXT month.
NEXT_MONTH_FROM_DAY = 20


def _first(d: date) -> date:
    return date(d.year, d.month, 1)


def _next_month(d: date) -> date:
    return date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def suggested_first_rent_month(move_in: date) -> date:
    """The month the form suggests: next month from the 20th, else this month."""
    return _next_month(move_in) if move_in.day >= NEXT_MONTH_FROM_DAY else _first(move_in)


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ApiError(f"'{value}' is not an amount.", status=400)


def _category(landlord_id: int, name: str):
    from models import ChargeCategory
    return (ChargeCategory.query
            .filter(ChargeCategory.landlord_id == landlord_id,
                    db.func.lower(ChargeCategory.name) == name.lower())
            .order_by(ChargeCategory.is_default.desc(), ChargeCategory.id.asc())
            .first())


def _billed_month(tenant, options: dict) -> tuple[date, bool]:
    """(the month every line is for, whether it is next-month billing)."""
    from services import line_period as lp

    move_in = tenant.move_in_date or date.today()
    next_month = bool(options.get("bill_next_month"))
    if not next_month:
        return _first(move_in), False
    chosen = (lp.parse_month(options.get("bill_month"))
              or lp.parse_month(options.get("first_rent_month"))
              or _next_month(move_in))
    if chosen <= _first(move_in):
        raise ApiError("'Bill the next month's move-in now' is for a month AFTER the "
                       "move-in month. Untick it to bill the move-in month.", status=400)
    return chosen, True


def _legacy_lines(tenant, options: dict) -> list[dict]:
    """Older callers sent deposit_amount / lease_fee / include_first_rent instead of lines."""
    rent_cat = _category(tenant.landlord_id, "Rent")
    lease_cat = _category(tenant.landlord_id, "Lease Agreement")
    unit = tenant.unit
    lines = []
    if options.get("include_first_rent", True) and unit is not None and unit.rent_amount:
        lines.append({"category_id": rent_cat.id if rent_cat else None, "subcategory": "current",
                      "item": "Rent", "amount": options.get("rent_amount") or unit.rent_amount})
    deposit = options.get("deposit_amount", tenant.deposit_amount)
    if deposit:
        lines.append({"category_id": rent_cat.id if rent_cat else None, "subcategory": "deposit",
                      "item": "Rent Deposit", "amount": deposit})
    if options.get("lease_fee"):
        lines.append({"category_id": lease_cat.id if lease_cat else None, "subcategory": "current",
                      "item": "Lease Agreement", "amount": options["lease_fee"]})
    return lines


def _plan(tenant, options: dict) -> dict:
    from models import ChargeCategory
    from services import line_period as lp

    if tenant.unit is None:
        raise ApiError("This tenant has no unit.", status=400)
    month, next_month = _billed_month(tenant, options)

    raw_lines = options.get("lines")
    if raw_lines is None:
        raw_lines = _legacy_lines(tenant, options)
    if not isinstance(raw_lines, list):
        raise ApiError("lines must be a list.", status=400)

    cats = {c.id: c for c in ChargeCategory.query.filter_by(landlord_id=tenant.landlord_id).all()}
    lines = []
    for raw in raw_lines:
        amount = _amount(raw.get("amount"))
        if amount <= 0:
            continue
        sub = raw.get("subcategory") or "current"
        if sub not in SUBCATEGORIES:
            raise ApiError(f"Unknown charge type '{sub}'.", status=400)
        cid = raw.get("category_id")
        cat = None
        if cid not in (None, "", "custom"):
            cat = cats.get(int(cid))
            if cat is None:
                raise ApiError("That charge category is not on this account.", status=400)
        if cat is not None:
            item = cat.subcategory_display().get(sub, cat.name)
        else:
            item = str(raw.get("item") or "").strip()[:120]
            if not item:
                raise ApiError("A custom line needs a name.", status=400)
        lines.append({
            "item": item,
            "description": (raw.get("description") or None),
            "amount": amount,
            "category_id": cat.id if cat else None,
            "subcategory": sub,
            "period_month": month,
            "undated": bool(cat is not None and (cat.name or "").strip().lower()
                            in ("lease agreement", "lease", "lease fee", "agreement fee"))
                       or "lease agreement" in item.lower(),
        })

    total = sum((l["amount"] for l in lines), Z)
    return {
        "move_in_date": (tenant.move_in_date or date.today()).isoformat(),
        "bill_next_month": next_month,
        "billed_month": month.isoformat(),
        "billed_month_label": lp.month_label(month),
        "lines": [{
            "item": l["item"], "description": l["description"], "amount": float(l["amount"]),
            "category_id": l["category_id"], "subcategory": l["subcategory"],
            "period_month": month.isoformat(),
            # What the receipt will print: the lease fee has no month.
            "label": l["item"] if l["undated"] else f"{l['item']} — {lp.month_label(month)}",
        } for l in lines],
        "total": float(total),
        "_lines": lines,
        "_month": month,
    }


def preview(tenant, options: dict) -> dict:
    """What bill_move_in() would create, without creating it."""
    plan = _plan(tenant, options)
    plan.pop("_lines")
    plan.pop("_month")
    return plan


def bill_move_in(tenant, options: dict, *, actor_user_id=None):
    """
    Create the move-in invoice for *tenant*. Returns the Invoice, or None when
    no line has an amount. Refuses to bill the same tenant's move-in twice.
    Flushes; the caller commits.
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

    month = plan["_month"]
    move_in = tenant.move_in_date or date.today()
    if tenant.lease_start_date is None:
        # Next-month billing: the tenancy's rent starts in the billed month, so a
        # September run after the 26th bills them no September rent.
        tenant.lease_start_date = month if plan["bill_next_month"] else move_in

    total = sum((l["amount"] for l in lines), Z)
    title = (f"Move-in — {plan['billed_month_label']} (billed {move_in:%d %b %Y})"
             if plan["bill_next_month"] else f"Move-in — {plan['billed_month_label']}")
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
        title=title,
    )
    db.session.add(invoice)
    db.session.flush()
    for l in lines:
        db.session.add(InvoiceLineItem(
            invoice_id=invoice.id, item=l["item"], description=l["description"],
            quantity=Decimal("1"), unit_price=l["amount"], amount=l["amount"],
            category_id=l["category_id"], subcategory=l["subcategory"],
            amount_paid=Z, status=LineItemStatus.open.value,
            period_month=month,
        ))
    # New debt makes the running balance more negative (see models.py).
    tenant.balance = Decimal(str(tenant.balance or 0)) - total
    db.session.flush()

    apply_tenant_credit(tenant, tenant.landlord, ref_date=move_in)

    record_audit(actor_user_id, tenant.landlord_id, "move_in_invoice", "invoice", invoice.id,
                 f"Move-in invoice {invoice.invoice_number} for {tenant.first_name} "
                 f"{tenant.last_name}: {len(lines)} line(s) for {plan['billed_month_label']}"
                 f"{' (billed in advance)' if plan['bill_next_month'] else ''}, KES {total:,.2f}.")
    return invoice
