"""
SahilPay — services/export_service.py
========================================
§4.11 / §4.12 statement & insights report generation. Every report shares
one render path: gather (headers, rows) from the database, then render to
either PDF (WeasyPrint, reusing pdf_service's styling) or Excel (openpyxl)
depending on the caller's ?format=pdf|excel — so adding a new report only
means writing its query, never its rendering.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from sqlalchemy import func

from services.pdf_service import _BASE_STYLE, _money
from utils import parse_date, render_pdf

# ---------------------------------------------------------------------------
# Shared (headers, rows) -> bytes rendering
# ---------------------------------------------------------------------------


def _render_table(title: str, headers: list[str], rows: list[list], fmt: str) -> bytes:
    if fmt == "excel":
        return _render_excel(title, headers, rows)
    return _render_pdf_table(title, headers, rows)


def _render_pdf_table(title: str, headers: list[str], rows: list[list]) -> bytes:
    head_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{'' if cell is None else cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head><body>"
        f"<h1>{title}</h1>"
        f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>"
        f"</body></html>"
    )
    return render_pdf(html)


def _render_excel(title: str, headers: list[str], rows: list[list]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Report"
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([str(c) if isinstance(c, Decimal) else c for c in row])
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _date_range_filter(query, column, start_date: str | None, end_date: str | None):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start:
        query = query.filter(column >= start)
    if end:
        query = query.filter(column <= end)
    return query


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def generate_tenant_statement(landlord_id: int, tenant_id: int, fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from models import Invoice, Payment, Tenant

    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id).first()
    if tenant is None:
        return _render_table("Tenant Statement", ["Error"], [["Tenant not found."]], fmt)

    entries = []
    invoices = _date_range_filter(Invoice.query.filter_by(tenant_id=tenant_id), Invoice.issue_date, start_date, end_date)
    for inv in invoices.all():
        entries.append((inv.issue_date, f"Invoice {inv.invoice_number}", inv.total_amount, Decimal("0")))
    payments = _date_range_filter(Payment.query.filter_by(tenant_id=tenant_id), Payment.payment_date, start_date, end_date)
    for pay in payments.all():
        entries.append((pay.payment_date, f"Payment {pay.payment_ref}", Decimal("0"), pay.amount))
    entries.sort(key=lambda e: e[0] or date.min)

    running = Decimal("0")
    rows = []
    for d, label, due, paid in entries:
        running += (due or 0) - (paid or 0)
        rows.append([d, label, _money(due), _money(paid), _money(running)])

    return _render_table(
        f"Tenant Statement — {tenant.first_name} {tenant.last_name}",
        ["Date", "Item", "Due", "Paid", "Running Balance"],
        rows,
        fmt,
    )


def generate_property_statement(landlord_id: int, property_id: int, fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from models import Payment, Property

    prop = Property.query.filter_by(id=property_id, landlord_id=landlord_id).first()
    if prop is None:
        return _render_table("Property Statement", ["Error"], [["Property not found."]], fmt)

    query = _date_range_filter(Payment.query.filter_by(property_id=property_id), Payment.payment_date, start_date, end_date)
    rows = [
        [
            pay.payment_date,
            f"{pay.tenant.first_name} {pay.tenant.last_name}" if pay.tenant else "—",
            pay.payment_ref,
            _money(pay.amount),
        ]
        for pay in query.order_by(Payment.payment_date).all()
    ]
    return _render_table(f"Property Statement — {prop.name}", ["Date", "Tenant", "Reference", "Amount"], rows, fmt)


def generate_arrears_report(landlord_id: int, fmt: str, property_id: int | None, as_of_date: str | None) -> bytes:
    from models import Tenant, Unit

    query = Tenant.query.filter(Tenant.landlord_id == landlord_id, Tenant.balance > 0)
    if property_id:
        query = query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id == property_id)

    rows = [
        [
            f"{t.first_name} {t.last_name}",
            t.unit.property.name if t.unit and t.unit.property else "—",
            t.unit.name if t.unit else "—",
            t.phone,
            _money(t.balance),
        ]
        for t in query.order_by(Tenant.balance.desc()).all()
    ]
    title = f"Arrears Report (as of {as_of_date or date.today().isoformat()})"
    return _render_table(title, ["Tenant", "Property", "Unit", "Phone", "Arrears"], rows, fmt)


def generate_deleted_tenants_report(landlord_id: int, fmt: str, property_id: int | None) -> bytes:
    from extensions import db
    from models import Tenant, Unit

    query = (
        db.session.query(Tenant)
        .execution_options(include_deleted=True)
        .filter(Tenant.landlord_id == landlord_id, Tenant.is_deleted.is_(True))
    )
    if property_id:
        query = query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id == property_id)

    rows = [
        [
            f"{t.first_name} {t.last_name}",
            t.unit.name if t.unit else "—",
            t.phone,
            _money(t.balance),
            t.deleted_at.date().isoformat() if t.deleted_at else "—",
        ]
        for t in query.all()
    ]
    return _render_table("Deleted Tenants Report", ["Tenant", "Unit", "Phone", "Balance at deletion", "Deleted on"], rows, fmt)


def generate_expenses_report(landlord_id: int, fmt: str, property_id: int | None, start_date: str | None, end_date: str | None) -> bytes:
    from models import Expense

    query = Expense.query.filter_by(landlord_id=landlord_id)
    if property_id:
        query = query.filter(Expense.property_id == property_id)
    query = _date_range_filter(query, Expense.expense_date, start_date, end_date)

    rows = [[e.expense_date, e.property.name if e.property else "—", e.category, e.status, _money(e.amount)] for e in query.order_by(Expense.expense_date).all()]
    total = sum((e.amount or 0 for e in query.all()), Decimal("0"))
    rows.append(["", "", "", "Total", _money(total)])
    return _render_table("Expenses Report", ["Date", "Property", "Category", "Status", "Amount"], rows, fmt)


def generate_mom_report(landlord_id: int, fmt: str, property_id: int | None, year: int | None) -> bytes:
    return _comparative_report(landlord_id, fmt, property_id, year, period="month")


def generate_yoy_report(landlord_id: int, fmt: str, property_id: int | None) -> bytes:
    return _comparative_report(landlord_id, fmt, property_id, year=None, period="year")


def _comparative_report(landlord_id: int, fmt: str, property_id: int | None, year: int | None, period: str) -> bytes:
    from extensions import db
    from models import Invoice, Payment

    bucket = func.to_char(Payment.payment_date, "YYYY-MM" if period == "month" else "YYYY")

    payments_q = db.session.query(bucket.label("bucket"), func.sum(Payment.amount).label("total")).filter(
        Payment.landlord_id == landlord_id
    )
    invoices_q = db.session.query(
        func.to_char(Invoice.issue_date, "YYYY-MM" if period == "month" else "YYYY").label("bucket"),
        func.sum(Invoice.total_amount).label("total"),
    ).filter(Invoice.landlord_id == landlord_id)

    if property_id:
        payments_q = payments_q.filter(Payment.property_id == property_id)
        invoices_q = invoices_q.filter(Invoice.property_id == property_id)
    if period == "month" and year:
        payments_q = payments_q.filter(func.extract("year", Payment.payment_date) == year)
        invoices_q = invoices_q.filter(func.extract("year", Invoice.issue_date) == year)

    payments_by_bucket = dict(payments_q.group_by("bucket").all())
    invoices_by_bucket = dict(invoices_q.group_by("bucket").all())

    buckets = sorted(set(payments_by_bucket) | set(invoices_by_bucket))
    rows = [[b, _money(invoices_by_bucket.get(b, 0)), _money(payments_by_bucket.get(b, 0))] for b in buckets]

    label = "Month-on-Month" if period == "month" else "Year-on-Year"
    return _render_table(f"{label} Report", ["Period", "Invoiced", "Collected"], rows, fmt)


def generate_grouping_report(landlord_id: int, group_id: int, fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from models import Payment, Property, PropertyGroup, Tenant, Unit

    group = PropertyGroup.query.filter_by(id=group_id, landlord_id=landlord_id).first()
    if group is None:
        return _render_table("Grouping Report", ["Error"], [["Property group not found."]], fmt)

    rows = []
    for prop in group.properties:
        collected_q = _date_range_filter(Payment.query.filter_by(property_id=prop.id), Payment.payment_date, start_date, end_date)
        collected = sum((p.amount or 0 for p in collected_q.all()), Decimal("0"))
        arrears = sum(
            (t.balance or 0 for t in Tenant.query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id == prop.id, Tenant.balance > 0).all()),
            Decimal("0"),
        )
        unit_count = Unit.query.filter_by(property_id=prop.id).count()
        occupied = Unit.query.filter_by(property_id=prop.id, is_occupied=True).count()
        occupancy = round((occupied / unit_count) * 100, 1) if unit_count else 0
        rows.append([prop.name, _money(collected), _money(arrears), f"{occupancy}%"])

    return _render_table(f"Grouping Report — {group.name}", ["Property", "Collected", "Arrears", "Occupancy"], rows, fmt)


def generate_occupancy_report(landlord_id: int, fmt: str, property_id: int | None) -> bytes:
    from models import Property, Unit

    query = Property.query.filter_by(landlord_id=landlord_id)
    if property_id:
        query = query.filter(Property.id == property_id)

    rows = []
    for prop in query.all():
        for unit in prop.units:
            days_unoccupied = 0 if unit.is_occupied else 30  # best-effort: no vacancy-start timestamp tracked yet
            lost_rent = Decimal("0") if unit.is_occupied else (unit.rent_amount or Decimal("0"))
            rows.append([prop.name, unit.name, _money(unit.rent_amount), days_unoccupied, _money(lost_rent)])

    return _render_table("Occupancy Report", ["Property", "Unit", "Rent Amount", "Days Unoccupied", "Estimated Lost Rent"], rows, fmt)


def generate_payments_report(landlord_id: int, fmt: str, start_date: str | None, end_date: str | None, property_id: int | None):
    """Returns (file_bytes, mime, filename) — the one export function streamed directly as a download."""
    from models import Payment

    query = Payment.query.filter_by(landlord_id=landlord_id)
    if property_id:
        query = query.filter(Payment.property_id == property_id)
    query = _date_range_filter(query, Payment.payment_date, start_date, end_date)

    rows = [
        [
            p.payment_date,
            p.payment_ref,
            f"{p.tenant.first_name} {p.tenant.last_name}" if p.tenant else "—",
            p.status,
            _money(p.amount),
        ]
        for p in query.order_by(Payment.payment_date).all()
    ]
    file_bytes = _render_table("Payments Report", ["Date", "Reference", "Tenant", "Status", "Amount"], rows, fmt)

    if fmt == "excel":
        return file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "payments-report.xlsx"
    return file_bytes, "application/pdf", "payments-report.pdf"
