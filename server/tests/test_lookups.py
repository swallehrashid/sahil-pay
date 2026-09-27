"""Dropdown option lists return every row, not the first page of 20."""

import pytest

from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_team_member, _make_tenant,
    _make_unit, _token,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def estate(app, db_session):
    landlord, user = _make_landlord(db_session, "lk")
    props = [_make_property(db_session, landlord, f"Block{i:02d}") for i in range(30)]
    units, tenants = [], []
    for p in props[:25]:
        u = _make_unit(db_session, p, "U")
        units.append(u)
        tenants.append(_make_tenant(db_session, landlord, u))
    return landlord, user, props, units, tenants


def test_every_property_unit_and_tenant_is_offered(app, client, estate):
    landlord, user, props, units, tenants = estate
    h = _auth(_token(app, user, landlord_id=landlord.id))

    got = client.get("/api/lookups/properties", headers=h).get_json()
    assert got["total"] == 30 and len(got["properties"]) == 30

    got = client.get("/api/lookups/units", headers=h).get_json()
    assert len(got["units"]) == 25
    assert all(u["property_name"] for u in got["units"])

    got = client.get("/api/lookups/tenants", headers=h).get_json()
    assert len(got["tenants"]) == 25
    row = got["tenants"][0]
    assert row["unit_name"] and row["property_name"] and row["property_id"]


def test_deleted_and_orphaned_rows_are_not_offered(app, client, estate, db_session):
    landlord, user, props, units, tenants = estate
    h = _auth(_token(app, user, landlord_id=landlord.id))
    props[0].is_deleted = True          # its unit and tenant must disappear with it
    tenants[1].is_deleted = True
    db_session.flush()

    ids = {t["id"] for t in client.get("/api/lookups/tenants", headers=h).get_json()["tenants"]}
    assert tenants[0].id not in ids and tenants[1].id not in ids
    assert len(ids) == 23
    unit_ids = {u["id"] for u in client.get("/api/lookups/units", headers=h).get_json()["units"]}
    assert units[0].id not in unit_ids


def test_scoped_team_member_only_sees_their_properties(app, client, estate, db_session):
    landlord, user, props, units, tenants = estate
    tm, tm_user = _make_team_member(db_session, landlord, property_ids=[props[0].id, props[1].id],
                                    modules=["utilities"])
    h = _auth(_token(app, tm_user, landlord_id=landlord.id, team_member_id=tm.id))

    got = client.get("/api/lookups/properties", headers=h).get_json()
    assert {p["id"] for p in got["properties"]} == {props[0].id, props[1].id}
    got = client.get("/api/lookups/tenants", headers=h).get_json()
    assert {t["id"] for t in got["tenants"]} == {tenants[0].id, tenants[1].id}


def test_team_member_with_no_modules_is_refused(app, client, estate, db_session):
    landlord, user, props, *_ = estate
    tm, tm_user = _make_team_member(db_session, landlord, property_ids=[props[0].id], modules=["reports"])
    for perm in tm.permissions:
        perm.can_view = perm.can_edit = False
    db_session.flush()
    h = _auth(_token(app, tm_user, landlord_id=landlord.id, team_member_id=tm.id))
    assert client.get("/api/lookups/properties", headers=h).status_code == 403
