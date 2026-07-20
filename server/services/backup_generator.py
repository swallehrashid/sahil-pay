"""
SahilPay — services/backup_generator.py
=======================================
Detailed, on-demand data backups built on the same report engine as the
statements (report_builder.ReportDocument). A backup is just a very wide,
un-summarised export of the landlord's records for a chosen SCOPE:

    tenants     — every tenant, full detail
    payments    — every payment, full detail
    units       — every unit, full detail
    properties  — every property, full detail
    property    — one property: its units + tenants + payments (scope_id)
    grouping    — one property group: same three sections per group (scope_id)

Because it returns a ReportDocument, a backup automatically gets the JSON
preview, the per-section column editor (pick exactly which columns to back up),
and Excel/PDF download — no separate machinery, no Celery, downloads immediately.
"""

from __future__ import annotations

from decimal import Decimal

from services.report_builder import Column, ReportDocument, Section, build_meta, DATE, MONEY, NUMBER, TEXT

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Per-entity section builders (each returns a fully-detailed Section)
# ---------------------------------------------------------------------------


def _tenants_section(tenants) -> Section:
    columns = [
        Column("unit", "Unit", TEXT),
        Column("property", "Property", TEXT),
        Column("first_name", "First name", TEXT),
        Column("last_name", "Last name", TEXT),
        Column("phone", "Phone", TEXT),
        Column("secondary_phone", "Secondary phone", TEXT, default=False),
        Column("email", "Email", TEXT),
        Column("national_id", "National ID", TEXT, default=False),
        Column("kra_pin", "KRA PIN", TEXT, default=False),
        Column("account_number", "Account no.", TEXT, default=False),
        Column("deposit_amount", "Deposit invoiced", MONEY),
        Column("deposit_paid", "Deposit paid", MONEY),
        Column("deposit_returned", "Deposit returned", MONEY, default=False),
        Column("balance", "Balance", MONEY),
        Column("lease_start_date", "Lease start", DATE, default=False),
        Column("lease_expiry_date", "Lease expiry", DATE, default=False),
        Column("move_in_date", "Move-in", DATE),
        Column("move_out_date", "Move-out", DATE, default=False),
        Column("status", "Status", TEXT),
    ]
    rows = []
    for t in tenants:
        bal = t.balance or ZERO
        rows.append({
            "unit": t.unit.name if t.unit else "—",
            "property": t.unit.property.name if t.unit and t.unit.property else "—",
            "first_name": t.first_name,
            "last_name": t.last_name,
            "phone": t.phone,
            "secondary_phone": t.secondary_phone,
            "email": t.email,
            "national_id": t.national_id,
            "kra_pin": t.kra_pin,
            "account_number": t.account_number,
            "deposit_amount": t.deposit_amount or ZERO,
            "deposit_paid": t.deposit_paid or ZERO,
            "deposit_returned": t.deposit_returned or ZERO,
            "balance": bal,
            "lease_start_date": t.lease_start_date,
            "lease_expiry_date": t.lease_expiry_date,
            "move_in_date": t.move_in_date,
            "move_out_date": t.move_out_date,
            "status": "In arrears" if bal < 0 else ("Advance/Credit" if bal > 0 else "Settled"),
        })
    return Section("tenants", "Tenants", columns, rows)


def _payments_section(payments) -> Section:
    columns = [
        Column("date", "Date", DATE),
        Column("ref", "Reference", TEXT),
        Column("tenant", "Tenant", TEXT),
        Column("unit", "Unit", TEXT),
        Column("property", "Property", TEXT),
        Column("amount", "Amount", MONEY),
        Column("method", "Method", TEXT),
        Column("source", "Source", TEXT),
        Column("mpesa_reference", "M-Pesa ref", TEXT, default=False),
        Column("status", "Status", TEXT),
    ]
    rows = []
    total = ZERO
    for p in payments:
        rows.append({
            "date": p.payment_date,
            "ref": p.payment_ref,
            "tenant": f"{p.tenant.first_name} {p.tenant.last_name}" if p.tenant else "—",
            "unit": p.unit.name if p.unit else "—",
            "property": p.property.name if p.property else "—",
            "amount": p.amount or ZERO,
            "method": p.payment_method or "—",
            "source": p.source or "—",
            "mpesa_reference": p.mpesa_reference,
            "status": p.status or "—",
        })
        total += p.amount or ZERO
    rows.sort(key=lambda r: (r["date"] is None, r["date"]))
    return Section("payments", "Payments", columns, rows, totals={"amount": total})


def _units_section(units) -> Section:
    columns = [
        Column("property", "Property", TEXT),
        Column("name", "Unit", TEXT),
        Column("rent_amount", "Rent", MONEY),
        Column("tax_rate", "Tax rate", NUMBER, default=False),
        Column("is_occupied", "Occupied", TEXT),
        Column("current_tenant", "Current tenant", TEXT),
    ]
    rows = []
    for u in units:
        active = [t for t in getattr(u, "tenants", []) if not t.is_deleted]
        rows.append({
            "property": u.property.name if u.property else "—",
            "name": u.name,
            "rent_amount": u.rent_amount or ZERO,
            "tax_rate": u.tax_rate,
            "is_occupied": "Yes" if u.is_occupied else "No",
            "current_tenant": f"{active[0].first_name} {active[0].last_name}" if active else "—",
        })
    return Section("units", "Units", columns, rows)


def _properties_section(properties) -> Section:
    columns = [
        Column("name", "Property", TEXT),
        Column("city", "City", TEXT),
        Column("street_name", "Street", TEXT, default=False),
        Column("number_of_units", "Units", NUMBER),
        Column("water_rate", "Water rate", MONEY, default=False),
        Column("electricity_rate", "Electricity rate", MONEY, default=False),
        Column("tax_rate", "Tax rate", NUMBER),
        Column("management_fee", "Management fee", MONEY, default=False),
        Column("owner_phone", "Owner phone", TEXT, default=False),
    ]
    rows = [{
        "name": p.name,
        "city": p.city,
        "street_name": p.street_name,
        "number_of_units": p.number_of_units,
        "water_rate": p.water_rate or ZERO,
        "electricity_rate": p.electricity_rate or ZERO,
        "tax_rate": p.tax_rate,
        "management_fee": p.management_fee or ZERO,
        "owner_phone": p.owner_phone,
    } for p in properties]
    return Section("properties", "Properties", columns, rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_backup(landlord, scope_type: str, scope_id: int | None) -> ReportDocument:
    from models import Payment, Property, PropertyGroup, Tenant, Unit

    lid = landlord.id

    def all_tenants(property_id=None):
        q = Tenant.query.filter_by(landlord_id=lid, is_deleted=False)
        if property_id:
            q = q.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id == property_id)
        return q.all()

    def all_payments(property_id=None):
        q = Payment.query.filter_by(landlord_id=lid, is_deleted=False)
        if property_id:
            q = q.filter(Payment.property_id == property_id)
        return q.all()

    def all_units(property_id=None):
        q = Unit.query.join(Property, Property.id == Unit.property_id).filter(
            Property.landlord_id == lid, Unit.is_deleted.is_(False))
        if property_id:
            q = q.filter(Unit.property_id == property_id)
        return q.all()

    def all_properties():
        return Property.query.filter_by(landlord_id=lid, is_deleted=False).all()

    sections = []
    subject = None

    if scope_type == "tenants":
        sections = [_tenants_section(all_tenants())]
    elif scope_type == "payments":
        sections = [_payments_section(all_payments())]
    elif scope_type == "units":
        sections = [_units_section(all_units())]
    elif scope_type == "properties":
        sections = [_properties_section(all_properties())]
    elif scope_type == "property":
        prop = Property.query.filter_by(id=scope_id, landlord_id=lid).first()
        if not prop:
            return _error_doc(landlord, "Property not found.")
        subject = prop.name
        sections = [
            _units_section(all_units(prop.id)),
            _tenants_section(all_tenants(prop.id)),
            _payments_section(all_payments(prop.id)),
        ]
    elif scope_type == "grouping":
        group = PropertyGroup.query.filter_by(id=scope_id, landlord_id=lid).first()
        if not group:
            return _error_doc(landlord, "Property group not found.")
        subject = f"Group: {group.name}"
        prop_ids = [p.id for p in group.properties]
        tenants, payments, units = [], [], []
        for pid in prop_ids:
            tenants += all_tenants(pid)
            payments += all_payments(pid)
            units += all_units(pid)
        sections = [_units_section(units), _tenants_section(tenants), _payments_section(payments)]
    else:
        return _error_doc(landlord, f"Unknown backup scope '{scope_type}'.")

    meta = build_meta(
        landlord,
        report_title=f"Data Backup — {scope_type.title()}",
        subject=subject,
        period=f"As of {__import__('datetime').date.today().isoformat()}",
    )
    return ReportDocument(f"backup_{scope_type}", f"Data Backup — {scope_type.title()}", meta, sections)


def _error_doc(landlord, message: str) -> ReportDocument:
    meta = build_meta(landlord, report_title="Data Backup")
    section = Section("error", "Error", [Column("message", "Message", TEXT)], [{"message": message}])
    return ReportDocument("backup_error", "Data Backup", meta, [section])
