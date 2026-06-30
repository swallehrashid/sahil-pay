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
            )
        )

    # Ledger convention (matches landlord_dashboard_routes/report_routes/export_service):
    # negative balance = arrears (owed), positive = advance (credit). Issuing a bill
    # increases what's owed, so it moves balance DOWN (more negative).
    tenant.balance = float(tenant.balance or 0) - total
    db.session.add(tenant)
    return invoice


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
        query = query.filter(Tenant.balance > 0)

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

        if reading.utility_item == "water":
            rate = reading.property.water_rate if reading.property else None
        elif reading.utility_item == "electricity":
            rate = reading.property.electricity_rate if reading.property else None
        else:
            rate = None

        unit_price  = float(rate) if rate else 1.0
        consumption = float(reading.consumption or 0)
        amount      = Decimal(str(consumption)) * Decimal(str(unit_price))
        description = f"{reading.reading_month} — {reading.previous_reading or 0} to {reading.current_reading}"

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
            ))
            target.total_amount = (target.total_amount or Decimal("0")) + amount
            target.balance      = target.total_amount - (target.amount_paid or Decimal("0"))
            tenant.balance      = Decimal(str(tenant.balance or 0)) - amount
            reading.invoice_id  = target.id
            combined += 1
        else:
            invoice = _create_invoice(
                landlord_id, tenant, reading.unit, reading.property, "utility",
                _date(*[int(x) for x in reading.reading_month.split("-")[:2]], 1) if reading.reading_month else date.today(),
                None,
                [{
                    "item": reading.utility_item, "description": description,
                    "quantity": consumption, "unit_price": unit_price, "utility_reading_id": reading.id,
                }],
                title=f"{reading.utility_item.capitalize()} — {reading.reading_month}",
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
