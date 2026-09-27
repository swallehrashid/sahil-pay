"""
services/cascade_delete_service.py — a tenant lives in a unit, a unit in a property.

    delete a property  -> its units go, and every tenant in them
    delete a unit      -> its tenants go; the property stays
    delete a tenant    -> only the tenant; unit and property stay

Deletes are soft (is_deleted + deleted_at), as everywhere else in the system:
invoices and payments keep pointing at real rows, so statements and reports for
past months still add up. What matters is that a deleted parent never leaves a
live child behind — before this, deleting 100 properties left 1,000 tenants in
the system attached to units nobody could see.

Nothing here commits; the caller owns the transaction.
"""

from __future__ import annotations

from datetime import date, datetime


def delete_tenant(tenant, *, when: datetime | None = None) -> None:
    from extensions import db
    from models import TenantUnitHistory

    if tenant.is_deleted:
        return
    when = when or datetime.utcnow()
    tenant.is_deleted = True
    tenant.deleted_at = when
    tenant.move_out_date = tenant.move_out_date or date.today()

    unit = tenant.unit
    if unit is not None:
        still_there = [t for t in unit.tenants if not t.is_deleted and t.id != tenant.id]
        if not still_there:
            unit.is_occupied = False

    history = (
        TenantUnitHistory.query
        .filter_by(tenant_id=tenant.id, unit_id=tenant.unit_id)
        .filter(TenantUnitHistory.moved_out_at.is_(None))
        .first()
    )
    if history:
        history.moved_out_at = date.today()
    db.session.flush()


def delete_unit(unit, *, when: datetime | None = None) -> int:
    """Soft-delete *unit* and every live tenant in it. Returns tenants removed."""
    from extensions import db
    from models import QueuedCharge

    when = when or datetime.utcnow()
    removed = 0
    for tenant in list(unit.tenants):
        if not tenant.is_deleted:
            delete_tenant(tenant, when=when)
            removed += 1

    # A charge queued for a unit that no longer exists has nowhere to go.
    QueuedCharge.query.filter_by(unit_id=unit.id, status=QueuedCharge.STATUS_QUEUED).update(
        {QueuedCharge.status: QueuedCharge.STATUS_CANCELLED}, synchronize_session=False)

    if not unit.is_deleted:
        unit.is_deleted = True
        unit.deleted_at = when
    unit.is_occupied = False
    db.session.flush()
    return removed


def delete_property(prop, *, when: datetime | None = None) -> dict:
    """Soft-delete *prop*, all its units and all their tenants."""
    from extensions import db

    when = when or datetime.utcnow()
    units = tenants = 0
    for unit in list(prop.units):
        if unit.is_deleted:
            continue
        tenants += delete_unit(unit, when=when)
        units += 1
    prop.is_deleted = True
    prop.deleted_at = when
    db.session.flush()
    return {"units": units, "tenants": tenants}


def repair_orphans(landlord_id: int | None = None) -> dict:
    """
    Soft-delete every live unit whose property is deleted, and every live tenant
    whose unit (or that unit's property) is deleted. Safe to run repeatedly.
    """
    from extensions import db
    from models import Property, QueuedCharge, Tenant, TenantUnitHistory, Unit

    now = datetime.utcnow()

    dead_props = db.session.query(Property.id).filter(Property.is_deleted.is_(True))
    unit_q = Unit.query.filter(Unit.is_deleted.is_(False), Unit.property_id.in_(dead_props))
    if landlord_id is not None:
        unit_q = unit_q.join(Property, Property.id == Unit.property_id).filter(
            Property.landlord_id == landlord_id)
    orphan_unit_ids = [u.id for u in unit_q.with_entities(Unit.id).all()]
    if orphan_unit_ids:
        Unit.query.filter(Unit.id.in_(orphan_unit_ids)).update(
            {Unit.is_deleted: True, Unit.deleted_at: now, Unit.is_occupied: False},
            synchronize_session=False)

    dead_units = db.session.query(Unit.id).filter(Unit.is_deleted.is_(True))
    tenant_q = Tenant.query.filter(Tenant.is_deleted.is_(False), Tenant.unit_id.in_(dead_units))
    if landlord_id is not None:
        tenant_q = tenant_q.filter(Tenant.landlord_id == landlord_id)
    orphan_tenant_ids = [t.id for t in tenant_q.with_entities(Tenant.id).all()]
    if orphan_tenant_ids:
        Tenant.query.filter(Tenant.id.in_(orphan_tenant_ids)).update(
            {Tenant.is_deleted: True, Tenant.deleted_at: now,
             Tenant.move_out_date: db.func.coalesce(Tenant.move_out_date, date.today())},
            synchronize_session=False)
        TenantUnitHistory.query.filter(
            TenantUnitHistory.tenant_id.in_(orphan_tenant_ids),
            TenantUnitHistory.moved_out_at.is_(None),
        ).update({TenantUnitHistory.moved_out_at: date.today()}, synchronize_session=False)

    QueuedCharge.query.filter(
        QueuedCharge.status == QueuedCharge.STATUS_QUEUED,
        QueuedCharge.unit_id.in_(dead_units),
    ).update({QueuedCharge.status: QueuedCharge.STATUS_CANCELLED}, synchronize_session=False)

    db.session.flush()
    return {"units": len(orphan_unit_ids), "tenants": len(orphan_tenant_ids)}
