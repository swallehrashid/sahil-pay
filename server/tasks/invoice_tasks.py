"""
SahilPay — tasks/invoice_tasks.py
====================================
§4.2  Bulk invoice generation — rent, recurring bills, penalties, custom,
and utility invoices — dispatched from invoice_routes.py / utility_routes.py
via .delay() since generating invoices for a whole portfolio can take a
while. Every generator shares _create_invoice(), which builds the Invoice +
InvoiceLineItem rows and bumps the tenant's running balance by the new
total (the same transaction that records payment_allocations is what later
brings that balance back down — see models.py §1's "Running balances" note).
"""

from __future__ import annotations

import logging
from datetime import date

from celery_app import celery
from utils import gen_reference, parse_date

logger = logging.getLogger(__name__)


def _create_invoice(landlord_id, tenant, unit, property_, invoice_type, issue_date, due_date, line_items, title=None):
    """
    line_items: list of dicts with keys item, description (optional),
    quantity (optional, default 1), unit_price. amount is computed here.
    """
    from extensions import db
    from models import Invoice, InvoiceLineItem

    total = sum(float(li.get("quantity", 1)) * float(li["unit_price"]) for li in line_items)

    invoice = Invoice(
        invoice_number=gen_reference("INV"),
        landlord_id=landlord_id,
        tenant_id=tenant.id,
        unit_id=unit.id,
        property_id=property_.id,
        invoice_type=invoice_type,
        issue_date=issue_date,
        due_date=due_date,
        status="open",
        total_amount=total,
        amount_paid=0,
        balance=total,
        title=title,
    )
    db.session.add(invoice)
    db.session.flush()

    for li in line_items:
        quantity = li.get("quantity", 1)
        unit_price = li["unit_price"]
        db.session.add(
            InvoiceLineItem(
                invoice_id=invoice.id,
                item=li["item"],
                description=li.get("description"),
                quantity=quantity,
                unit_price=unit_price,
                amount=float(quantity) * float(unit_price),
                utility_reading_id=li.get("utility_reading_id"),
                # Charge-category restructure: stamp the (category, subcategory) when the
                # caller supplies it. Older generators pass neither (left NULL for now).
                category_id=li.get("category_id"),
                subcategory=li.get("subcategory"),
            )
        )

    # Ledger convention (matches landlord_dashboard_routes/report_routes/export_service):
    # negative balance = arrears (owed), positive = advance (credit). Issuing a bill
    # increases what's owed, so it moves balance DOWN (more negative).
    tenant.balance = float(tenant.balance or 0) - total
    db.session.add(tenant)
    return invoice


# ===========================================================================
# Month-end billing & rollover (charge-category restructure, spec §3)
# ===========================================================================

def _first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def _unpaid_components(li) -> list[tuple[date, "Decimal"]]:
    """
    The still-owed provenance of a line, as [(origin_month, amount)]:
      • a 'current' line  → a single component tagged with its own invoice month;
      • a 'balance' line  → its BalanceRollover components (the months the debt
        originally arose), with the line's amount_paid consumed OLDEST-first so each
        component's remaining is correct. Provenance survives repeated rolls.
    """
    from decimal import Decimal
    from models import BalanceRollover, SubCategory

    remaining = li.remaining
    if remaining <= 0:
        return []

    if li.subcategory == SubCategory.balance.value:
        comps = (
            BalanceRollover.query
            .filter_by(target_line_item_id=li.id)
            .order_by(BalanceRollover.origin_month.asc(), BalanceRollover.id.asc())
            .all()
        )
        if comps:
            paid = li.amount_paid or Decimal("0")
            out: list[tuple[date, Decimal]] = []
            for c in comps:
                amt = c.amount or Decimal("0")
                if paid >= amt:
                    paid -= amt
                    continue
                out.append((c.origin_month, amt - paid))
                paid = Decimal("0")
            return out

    # 'current' line, or a defensive fallback for a balance line with no components.
    origin = _first_of_month(li.invoice.issue_date) if li.invoice and li.invoice.issue_date else date.today()
    return [(origin, remaining)]


def _run_monthly_billing_for_tenant(landlord, tenant, run_month_first: date, issue_dt: date, actor_user_id):
    """
    Do the month-end work for ONE tenant (caller owns the transaction / commit):
      1. Roll unpaid prior-month current/balance lines into one "{Category} Balance
         b/f" line per category on the new monthly invoice (deposits NEVER roll);
         mark sources 'rolled'; write BalanceRollover provenance rows.
      2. Add a 'current' line for each active auto_bill_monthly category.
      3. Apply any held tenant credit.
    Idempotent: skips a tenant who already has this run month's monthly invoice.
    Returns "created" | "skipped" | "empty".
    """
    from decimal import Decimal
    from extensions import db
    from models import (
        Invoice, InvoiceLineItem, InvoiceType, InvoiceStatus, LineItemStatus,
        BalanceRollover, ChargeCategory, SubCategory,
    )
    from services.allocation_service import recompute_invoice, apply_tenant_credit
    from services.audit_service import record_audit

    unit = tenant.unit
    if unit is None:
        return "empty"

    # Idempotency guard — one monthly invoice per tenant per run month.
    existing = (
        Invoice.query
        .filter_by(tenant_id=tenant.id, landlord_id=landlord.id,
                   invoice_type=InvoiceType.monthly.value, is_deleted=False)
        .filter(Invoice.issue_date >= run_month_first)
        .first()
    )
    if existing is not None:
        return "skipped"

    Z = Decimal("0")

    # ---- Gather rollover components (read-only first) ----
    # Prior-month, still-open current/balance lines. Deposits are excluded → never roll.
    source_lines = (
        InvoiceLineItem.query
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(Invoice.tenant_id == tenant.id,
                Invoice.landlord_id == landlord.id,
                Invoice.is_deleted.is_(False),
                Invoice.issue_date < run_month_first,
                Invoice.status != InvoiceStatus.void.value,
                InvoiceLineItem.status == LineItemStatus.open.value,
                InvoiceLineItem.subcategory.in_(
                    [SubCategory.current.value, SubCategory.balance.value]),
                InvoiceLineItem.category_id.isnot(None))
        .all()
    )

    # category_id -> {"total": Decimal, "rows": [(source_line, origin_month, amount)]}
    per_category: dict[int, dict] = {}
    for li in source_lines:
        comps = _unpaid_components(li)
        if not comps:
            continue
        bucket = per_category.setdefault(li.category_id, {"total": Z, "rows": []})
        for origin_month, amount in comps:
            if amount <= 0:
                continue
            bucket["total"] += amount
            bucket["rows"].append((li, origin_month, amount))

    # ---- Determine this month's auto-billed current charges ----
    auto_cats = (
        ChargeCategory.query
        .filter_by(landlord_id=landlord.id, is_active=True, auto_bill_monthly=True)
        .order_by(ChargeCategory.id.asc())
        .all()
    )
    current_lines: list[tuple[ChargeCategory, Decimal]] = []
    for cat in auto_cats:
        if cat.name.lower() == "rent":
            amount = Decimal(str(unit.rent_amount or 0))
        else:
            amount = Decimal(str(cat.default_rate or 0))
        if amount > 0:
            current_lines.append((cat, amount))

    if not per_category and not current_lines:
        return "empty"

    cats_by_id = {c.id: c for c in ChargeCategory.query.filter_by(landlord_id=landlord.id).all()}

    # ---- Create the single monthly invoice ----
    invoice = Invoice(
        invoice_number=gen_reference("INV"),
        landlord_id=landlord.id,
        tenant_id=tenant.id,
        unit_id=unit.id,
        property_id=unit.property_id,
        invoice_type=InvoiceType.monthly.value,
        issue_date=issue_dt,
        status=InvoiceStatus.open.value,
        total_amount=Z, amount_paid=Z, balance=Z,
        title=f"Monthly invoice — {issue_dt:%B %Y}",
    )
    db.session.add(invoice)
    db.session.flush()

    total = Z

    # Balance-b/f lines (carried debt — NOT a new charge, so tenant.balance untouched).
    for cid, bucket in per_category.items():
        cat = cats_by_id.get(cid)
        if cat is None or bucket["total"] <= 0:
            continue
        bf = InvoiceLineItem(
            invoice_id=invoice.id,
            item=f"{cat.name} Balance b/f",
            description="Carried forward from unpaid prior months",
            quantity=Decimal("1"),
            unit_price=bucket["total"], amount=bucket["total"],
            category_id=cid, subcategory=SubCategory.balance.value,
            amount_paid=Z, status=LineItemStatus.open.value,
        )
        db.session.add(bf)
        db.session.flush()
        total += bucket["total"]

        for source_line, origin_month, amount in bucket["rows"]:
            db.session.add(BalanceRollover(
                landlord_id=landlord.id, tenant_id=tenant.id, category_id=cid,
                source_line_item_id=source_line.id, target_line_item_id=bf.id,
                origin_month=origin_month, amount=amount,
            ))

    # Mark every rolled source line closed + recompute its invoice header.
    touched_invoices = set()
    for bucket in per_category.values():
        for source_line, _om, _amt in bucket["rows"]:
            if source_line.status != LineItemStatus.rolled.value:
                source_line.status = LineItemStatus.rolled.value
                touched_invoices.add(source_line.invoice_id)
    for inv_id in touched_invoices:
        inv = db.session.get(Invoice, inv_id)
        if inv is not None:
            recompute_invoice(inv)

    # This month's current charges (NEW debt → reduce tenant.balance).
    for cat, amount in current_lines:
        db.session.add(InvoiceLineItem(
            invoice_id=invoice.id,
            item=cat.name,
            quantity=Decimal("1"), unit_price=amount, amount=amount,
            category_id=cat.id, subcategory=SubCategory.current.value,
            amount_paid=Z, status=LineItemStatus.open.value,
        ))
        total += amount
        tenant.balance = Decimal(str(tenant.balance or 0)) - amount

    invoice.total_amount = total
    invoice.balance = total
    db.session.flush()

    # Apply any held credit to the freshly-issued charges.
    apply_tenant_credit(tenant, landlord, ref_date=issue_dt)

    record_audit(actor_user_id, landlord.id, "run_monthly_billing", "invoice", invoice.id,
                 f"Monthly invoice {invoice.invoice_number} generated for "
                 f"{tenant.first_name} {tenant.last_name} "
                 f"({len(per_category)} balance b/f, {len(current_lines)} current).")
    return "created"


@celery.task(name="tasks.invoice_tasks.run_monthly_billing_task")
def run_monthly_billing_task(landlord_id, issue_date=None, property_ids=None, unit_ids=None, actor_user_id=None) -> dict:
    """
    Month-end billing + rollover for one landlord (spec §3). One transaction per
    tenant so a single tenant's failure can't poison the whole run.
    """
    from extensions import db
    from models import Landlord, Tenant, Unit

    issue_dt = parse_date(issue_date) or date.today()
    run_month_first = _first_of_month(issue_dt)
    landlord = db.session.get(Landlord, landlord_id)
    if landlord is None:
        return {"created": 0, "skipped": 0, "empty": 0, "errors": 0}

    query = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if unit_ids:
        query = query.filter(Tenant.unit_id.in_(unit_ids))
    elif property_ids:
        query = query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id.in_(property_ids))

    tally = {"created": 0, "skipped": 0, "empty": 0, "errors": 0}
    for tenant in query.all():
        try:
            outcome = _run_monthly_billing_for_tenant(
                landlord, tenant, run_month_first, issue_dt, actor_user_id)
            db.session.commit()
            tally[outcome] = tally.get(outcome, 0) + 1
        except Exception:
            db.session.rollback()
            logger.exception("Monthly billing failed for tenant %s (landlord %s).",
                             tenant.id, landlord_id)
            tally["errors"] += 1
    return tally


@celery.task(name="tasks.invoice_tasks.run_monthly_billing_all")
def run_monthly_billing_all(issue_date=None) -> dict:
    """
    Celery Beat entry (1st of month): run month-end billing for every landlord.
    Demo shadow landlords (DEMO_MODE_SPEC.md §3.4) are skipped — their example
    data must never churn overnight; it only changes via the demo/reset flow.
    """
    from models import Landlord

    totals = {"landlords": 0, "created": 0, "skipped": 0, "empty": 0, "errors": 0}
    for landlord in Landlord.query.filter(Landlord.is_demo.is_(False)).all():
        res = run_monthly_billing_task(landlord.id, issue_date=issue_date)
        totals["landlords"] += 1
        for k in ("created", "skipped", "empty", "errors"):
            totals[k] += res.get(k, 0)
    return totals


@celery.task(name="tasks.invoice_tasks.generate_rent_invoices_task")
def generate_rent_invoices_task(landlord_id, issue_date=None, property_ids=None, unit_ids=None, due_date=None, actor_user_id=None) -> dict:
    """One rent invoice per active (non-deleted) tenant in scope, amount = their unit's rent_amount."""
    from extensions import db
    from models import Tenant, Unit
    from services.audit_service import record_audit

    issue_dt = parse_date(issue_date) or date.today()
    due_dt = parse_date(due_date)

    query = Tenant.query.filter_by(landlord_id=landlord_id)
    if unit_ids:
        query = query.filter(Tenant.unit_id.in_(unit_ids))
    elif property_ids:
        query = query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id.in_(property_ids))

    created = 0
    for tenant in query.all():
        unit = tenant.unit
        if unit is None:
            continue
        invoice = _create_invoice(
            landlord_id, tenant, unit, unit.property, "rent", issue_dt, due_dt,
            [{"item": "Rent", "unit_price": unit.rent_amount}],
            title=f"Rent — {issue_dt.strftime('%B %Y')}",
        )
        record_audit(actor_user_id, landlord_id, "generate_rent_invoice", "invoice", invoice.id, f"Rent invoice {invoice.invoice_number} generated for {tenant.first_name} {tenant.last_name}.")
        created += 1

    db.session.commit()
    return {"created": created}


@celery.task(name="tasks.invoice_tasks.generate_recurring_invoices_task")
def generate_recurring_invoices_task(landlord_id, issue_date=None, property_ids=None, actor_user_id=None) -> dict:
    """One invoice per active RecurringBill, for every tenant in its scope (unit-level or every tenant on the property)."""
    from extensions import db
    from models import RecurringBill, Tenant
    from services.audit_service import record_audit

    issue_dt = parse_date(issue_date) or date.today()

    query = RecurringBill.query.filter_by(landlord_id=landlord_id, is_active=True)
    if property_ids:
        query = query.filter(RecurringBill.property_id.in_(property_ids))

    created = 0
    for bill in query.all():
        if bill.unit_id:
            tenants = Tenant.query.filter_by(unit_id=bill.unit_id).all()
        elif bill.property_id:
            tenants = Tenant.query.join(Tenant.unit).filter_by(property_id=bill.property_id).all()
        else:
            continue

        for tenant in tenants:
            unit = tenant.unit
            if unit is None:
                continue
            invoice = _create_invoice(
                landlord_id, tenant, unit, unit.property, "recurring", issue_dt, None,
                [{"item": bill.name, "unit_price": bill.amount}],
                title=bill.name,
            )
            record_audit(actor_user_id, landlord_id, "generate_recurring_invoice", "invoice", invoice.id, f"Recurring invoice '{bill.name}' generated for {tenant.first_name} {tenant.last_name}.")
            created += 1

    db.session.commit()
    return {"created": created}


@celery.task(name="tasks.invoice_tasks.generate_penalty_invoices_task")
def generate_penalty_invoices_task(landlord_id, issue_date=None, tenant_ids=None, penalty_amount=None, actor_user_id=None) -> dict:
    """One penalty invoice per tenant in arrears (or the given tenant_ids), using penalty_amount or the tenant's/unit's configured penalty."""
    from extensions import db
    from models import Tenant
    from services.audit_service import record_audit

    issue_dt = parse_date(issue_date) or date.today()

    query = Tenant.query.filter_by(landlord_id=landlord_id)
    if tenant_ids:
        query = query.filter(Tenant.id.in_(tenant_ids))
    else:
        # BUG FIX: this filtered `balance > 0`, which is ADVANCE CREDIT — so it
        # fined tenants who had paid ahead and left every real debtor alone.
        # Arrears are NEGATIVE (services/report_generators.py states the
        # convention). See tests/test_penalties.py, which pins the sign.
        query = query.filter(Tenant.balance < 0)

    created = 0
    for tenant in query.all():
        unit = tenant.unit
        if unit is None:
            continue
        amount = penalty_amount or tenant.rent_payment_penalty or (unit.property.rent_payment_penalty if unit.property else None)
        if not amount:
            continue
        invoice = _create_invoice(
            landlord_id, tenant, unit, unit.property, "penalty", issue_dt, None,
            [{"item": "Late payment penalty", "unit_price": amount}],
            title="Late Payment Penalty",
        )
        record_audit(actor_user_id, landlord_id, "generate_penalty_invoice", "invoice", invoice.id, f"Penalty invoice {invoice.invoice_number} generated for {tenant.first_name} {tenant.last_name}.")
        created += 1

    db.session.commit()
    return {"created": created}


@celery.task(name="tasks.invoice_tasks.generate_custom_invoices_task")
def generate_custom_invoices_task(landlord_id, tenant_ids, issue_date, line_items, title=None, due_date=None, actor_user_id=None) -> dict:
    """One custom invoice per tenant in tenant_ids, sharing the same line_items."""
    from extensions import db
    from models import Tenant
    from services.audit_service import record_audit

    issue_dt = parse_date(issue_date) or date.today()
    due_dt = parse_date(due_date)

    created = 0
    for tenant in Tenant.query.filter(Tenant.id.in_(tenant_ids), Tenant.landlord_id == landlord_id).all():
        unit = tenant.unit
        if unit is None:
            continue
        invoice = _create_invoice(landlord_id, tenant, unit, unit.property, "custom", issue_dt, due_dt, line_items, title=title)
        record_audit(actor_user_id, landlord_id, "generate_custom_invoice", "invoice", invoice.id, f"Custom invoice {invoice.invoice_number} generated for {tenant.first_name} {tenant.last_name}.")
        created += 1

    db.session.commit()
    return {"created": created}


@celery.task(name="tasks.invoice_tasks.generate_utility_invoices_task")
def generate_utility_invoices_task(landlord_id, property_id=None, utility_item=None, reading_month=None, reading_ids=None, actor_user_id=None, combine=False) -> dict:
    """
    Bill each unlinked UtilityReading in scope (by reading_ids, or by
    property/item/month). Amount = consumption × the property's configured
    rate for water/electricity; garbage/security have no rate column on
    Property, so consumption is billed at face value for those items.

    combine=False: one new utility invoice per reading.
    combine=True:  append each reading to the tenant's open/partial invoice for
                   the reading's month (creating one if none is open yet) — so a
                   tenant gets a single combined bill for the month.
    """
    from datetime import date as _date
    from decimal import Decimal
    from sqlalchemy import extract
    from extensions import db
    from models import UtilityReading, Invoice, InvoiceLineItem, InvoiceStatus
    from services.audit_service import record_audit

    query = UtilityReading.query.filter_by(landlord_id=landlord_id, invoice_id=None)
    if reading_ids:
        query = query.filter(UtilityReading.id.in_(reading_ids))
    else:
        if property_id:
            query = query.filter(UtilityReading.property_id == property_id)
        if utility_item:
            query = query.filter(UtilityReading.utility_item == utility_item)
        if reading_month:
            query = query.filter(UtilityReading.reading_month == reading_month)

    created = combined = 0
    for reading in query.all():
        tenant = reading.unit.tenants[0] if reading.unit and reading.unit.tenants else None
        if tenant is None:
            continue

        utility_name = reading.category.name if reading.category else reading.utility_item.capitalize()

        # Flat (non-metered) readings carry an explicit amount; metered ones bill
        # consumption × rate — prefer the category's own default_rate, then fall
        # back to the property's water/electricity rate columns.
        if reading.amount is not None:
            amount = Decimal(str(reading.amount))
            consumption = 0
            unit_price = amount
        else:
            item_lower = (reading.utility_item or "").lower()
            if reading.category and reading.category.default_rate is not None:
                rate = reading.category.default_rate
            elif item_lower == "water":
                rate = reading.property.water_rate if reading.property else None
            elif item_lower == "electricity":
                rate = reading.property.electricity_rate if reading.property else None
            else:
                rate = None
            unit_price  = float(rate) if rate else 1.0
            consumption = float(reading.consumption or 0)
            amount      = Decimal(str(consumption)) * Decimal(str(unit_price))
        description = f"{reading.reading_month} — {reading.previous_reading or 0} to {reading.current_reading}" if reading.amount is None else f"{reading.reading_month} flat charge"

        target = None
        if combine:
            try:
                year, month = (int(x) for x in reading.reading_month.split("-")[:2])
                target = (
                    Invoice.query
                    .filter_by(tenant_id=tenant.id, landlord_id=landlord_id, is_deleted=False)
                    .filter(Invoice.status.in_([InvoiceStatus.open.value, InvoiceStatus.partial.value]))
                    .filter(extract("year",  Invoice.issue_date) == year)
                    .filter(extract("month", Invoice.issue_date) == month)
                    .order_by(Invoice.id.desc())
                    .first()
                )
            except (ValueError, AttributeError):
                target = None

        if target is not None:
            db.session.add(InvoiceLineItem(
                invoice_id=target.id, item=reading.utility_item, description=description,
                quantity=Decimal("1"), unit_price=amount, amount=amount, utility_reading_id=reading.id,
                category_id=reading.category_id, subcategory="current",
            ))
            target.total_amount = (target.total_amount or Decimal("0")) + amount
            target.balance      = target.total_amount - (target.amount_paid or Decimal("0"))
            tenant.balance      = Decimal(str(tenant.balance or 0)) - amount
            # Append the utility's name to the invoice title if not already present —
            # "Rent" becomes "Rent, Electricity" (matches the invoice-form naming rule).
            existing_names = [p.strip() for p in (target.title or "").split(",") if p.strip()]
            if utility_name not in existing_names:
                existing_names.append(utility_name)
                target.title = ", ".join(existing_names)
            reading.invoice_id  = target.id
            combined += 1
        else:
            invoice = _create_invoice(
                landlord_id, tenant, reading.unit, reading.property, "utility",
                _date(*[int(x) for x in reading.reading_month.split("-")[:2]], 1) if reading.reading_month else date.today(),
                None,
                [{
                    "item": reading.utility_item, "description": description,
                    "quantity": 1, "unit_price": amount, "utility_reading_id": reading.id,
                    "category_id": reading.category_id, "subcategory": "current",
                }],
                title=utility_name,
            )
            reading.invoice_id = invoice.id
            record_audit(actor_user_id, landlord_id, "generate_utility_invoice", "invoice", invoice.id, f"Utility invoice {invoice.invoice_number} generated for {tenant.first_name} {tenant.last_name}.")
            created += 1
        db.session.add(reading)

    db.session.commit()
    return {"created": created, "combined": combined}


@celery.task(name="tasks.invoice_tasks.bulk_generate_invoices_task")
def bulk_generate_invoices_task(landlord_id, invoice_type, **kwargs) -> dict:
    """Generic dispatcher to the type-specific generator — kept for callers that pick the type dynamically."""
    dispatch = {
        "rent": generate_rent_invoices_task,
        "recurring": generate_recurring_invoices_task,
        "penalty": generate_penalty_invoices_task,
        "custom": generate_custom_invoices_task,
        "utility": generate_utility_invoices_task,
    }
    generator = dispatch.get(invoice_type)
    if generator is None:
        logger.warning("bulk_generate_invoices_task: unknown invoice_type '%s'", invoice_type)
        return {"created": 0}
    return generator(landlord_id, **kwargs)


@celery.task(name="tasks.invoice_tasks.bulk_download_invoices_task")
def bulk_download_invoices_task(landlord_id, invoice_ids) -> str | None:
    """Zips one PDF per invoice and uploads the archive, returning its URL (the task's result)."""
    import zipfile
    from io import BytesIO

    from models import Invoice
    from services.pdf_service import generate_invoice_pdf
    from services.storage_service import upload_to_s3

    invoices = Invoice.query.filter(Invoice.id.in_(invoice_ids), Invoice.landlord_id == landlord_id).all()
    if not invoices:
        return None

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for invoice in invoices:
            zf.writestr(f"{invoice.invoice_number}.pdf", generate_invoice_pdf(invoice))

    return upload_to_s3(
        buf.getvalue(),
        folder=f"invoices/{landlord_id}/bulk",
        filename="invoices.zip",
        content_type="application/zip",
    )
