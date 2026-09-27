"""Property -> units -> tenants: deleting a parent never leaves a live child behind."""

import pytest

from models import QueuedCharge
from services.cascade_delete_service import repair_orphans
from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_tenant, _make_unit, _token,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def block(app, db_session):
    landlord, user = _make_landlord(db_session, "cd")
    prop = _make_property(db_session, landlord, "Block")
    units = [_make_unit(db_session, prop, f"U{i}") for i in range(3)]
    tenants = [_make_tenant(db_session, landlord, u) for u in units]
    for u in units:
        u.is_occupied = True
    db_session.flush()
    h = _auth(_token(app, user, landlord_id=landlord.id))
    return landlord, h, prop, units, tenants


def _tenant_count(client, h):
    return client.get("/api/tenants/", headers=h).get_json()["summary"]["total_tenants"]


def test_deleting_a_property_takes_its_units_and_tenants(client, block):
    landlord, h, prop, units, tenants = block
    r = client.delete(f"/api/properties/{prop.id}", headers=h)
    assert r.status_code == 200
    body = r.get_json()
    assert body["units_deleted"] == 3 and body["tenants_deleted"] == 3
    assert all(u.is_deleted for u in units)
    assert all(t.is_deleted for t in tenants)
    assert _tenant_count(client, h) == 0


def test_deleting_a_unit_takes_its_tenant_but_not_the_property(client, block):
    landlord, h, prop, units, tenants = block
    r = client.delete(f"/api/units/{units[0].id}", headers=h)
    assert r.status_code == 200 and r.get_json()["tenants_deleted"] == 1
    assert tenants[0].is_deleted and not prop.is_deleted
    assert not tenants[1].is_deleted and not units[1].is_deleted
    assert _tenant_count(client, h) == 2


def test_deleting_a_tenant_leaves_unit_and_property(client, block):
    landlord, h, prop, units, tenants = block
    assert client.delete(f"/api/tenants/{tenants[0].id}", headers=h).status_code == 200
    assert tenants[0].is_deleted
    assert not units[0].is_deleted and not prop.is_deleted
    assert units[0].is_occupied is False


def test_unit_delete_cancels_charges_queued_for_it(client, block, db_session):
    landlord, h, prop, units, tenants = block
    q = QueuedCharge(landlord_id=landlord.id, unit_id=units[0].id, item="Water",
                     amount=500, status=QueuedCharge.STATUS_QUEUED)
    db_session.add(q)
    db_session.flush()
    client.delete(f"/api/units/{units[0].id}", headers=h)
    db_session.refresh(q)
    assert q.status == QueuedCharge.STATUS_CANCELLED


def test_repair_removes_tenants_left_behind_by_old_property_deletes(client, block, db_session):
    """The live-data case: properties were deleted before the cascade existed."""
    landlord, h, prop, units, tenants = block
    prop.is_deleted = True               # the old behaviour: only the property flagged
    db_session.flush()
    assert not any(t.is_deleted for t in tenants)
    assert _tenant_count(client, h) == 0   # the list already refuses to show them

    fixed = repair_orphans(landlord.id)
    assert fixed == {"units": 3, "tenants": 3}
    db_session.expire_all()
    assert all(t.is_deleted for t in tenants) and all(u.is_deleted for u in units)
    assert repair_orphans(landlord.id) == {"units": 0, "tenants": 0}
