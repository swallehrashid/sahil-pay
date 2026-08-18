"""
Penalty API — permissions, property scoping, and the report.

The scoping tests matter more than the happy paths. A property manager's team
ranges from accountants to caretakers, each restricted to their own blocks, and
a penalty is money taken off a tenant — so "can this person see or change THIS
block's fines?" has to be answered by the server on every route, not by hiding
a nav item.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Landlord, LandlordSettings, PenaltySource, Property,
    TeamMember, TeamMemberPermission, TeamMemberPropertyAccess, Tenant, Unit,
    User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def world(app, db_session):
    """
    One landlord, TWO properties each with a tenant in arrears, plus a team
    member scoped to the first property only.
    """
    s = db_session
    n = _uniq()

    owner = User(email=f"pr-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()

    landlord = Landlord(user_id=owner.id, company_name=f"PR {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Penalty",
                         kind="invoice", is_metered=False))
    s.flush()

    props, tenants = [], []
    for i in range(2):
        prop = Property(landlord_id=landlord.id, name=f"Block {i}-{n}", city="Nairobi")
        s.add(prop)
        s.flush()
        unit = Unit(property_id=prop.id, name=f"U{i}{n[:3]}", rent_amount=Decimal("20000"))
        s.add(unit)
        s.flush()
        tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id,
                        first_name=f"T{i}", last_name=n[:4],
                        phone=f"25470{i}{n[:6]}", account_number=f"A{i}{n}",
                        balance=Decimal("-12000"))
        s.add(tenant)
        s.flush()
        props.append(prop)
        tenants.append(tenant)

    # Team member restricted to props[0] only.
    tm_user = User(email=f"tm-{n}@test.sahilpay", phone=f"2549{n[:7]}",
                   password_hash=generate_password_hash("Testpass1"),
                   role="team_member", is_verified=True, is_active=True)
    s.add(tm_user)
    s.flush()
    member = TeamMember(user_id=tm_user.id, landlord_id=landlord.id,
                        username=f"scoped-{n}", first_name="Scoped",
                        last_name="Member", is_active=True,
                        property_access_all=False)
    s.add(member)
    s.flush()
    s.add(TeamMemberPropertyAccess(team_member_id=member.id, property_id=props[0].id))
    # `penalties` is its own module now — a late fee is not an invoice, and
    # setting a block's penalty POLICY is no longer something anyone who can
    # rename the block can do. These tests are about property scoping, so grant
    # the module and let scope be the only restriction under test.
    for module in ("invoices", "properties", "reports", "penalties"):
        s.add(TeamMemberPermission(team_member_id=member.id, module=module,
                                   can_view=True, can_edit=True))
    s.flush()

    with app.app_context():
        landlord_token = create_access_token(
            identity=str(owner.id),
            additional_claims={"role": "landlord", "landlord_id": landlord.id})
        member_token = create_access_token(
            identity=str(tm_user.id),
            additional_claims={"role": "team_member", "landlord_id": landlord.id,
                               "team_member_id": member.id})

    return {"landlord": landlord, "properties": props, "tenants": tenants,
            "landlord_token": landlord_token, "member_token": member_token,
            "member": member}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_unset_policy_reads_as_off(client, world):
    prop = world["properties"][0]
    res = client.get(f"/api/properties/{prop.id}/penalty-policy",
                     headers=_auth(world["landlord_token"]))
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["is_enabled"] is False
    assert data["tiers"] == []


def test_saving_and_reading_a_tiered_policy(client, world):
    prop = world["properties"][0]
    res = client.put(
        f"/api/properties/{prop.id}/penalty-policy",
        headers=_auth(world["landlord_token"]),
        json={
            "is_enabled": True, "mode": "tiered",
            "trigger_type": "day_of_month", "trigger_day": 6,
            "min_balance": 1000,
            "tiers": [
                {"min_balance": 5000,  "max_balance": 7000, "amount": 400},
                {"min_balance": 10000, "max_balance": None, "amount": 500},
            ],
        },
    )
    assert res.status_code == 200, res.get_data(as_text=True)

    read = client.get(f"/api/properties/{prop.id}/penalty-policy",
                      headers=_auth(world["landlord_token"]))
    data = read.get_json()["data"]
    assert data["is_enabled"] is True
    assert data["mode"] == "tiered"
    assert len(data["tiers"]) == 2


def test_an_invalid_policy_is_refused_with_a_reason(client, world):
    prop = world["properties"][0]
    res = client.put(f"/api/properties/{prop.id}/penalty-policy",
                     headers=_auth(world["landlord_token"]),
                     json={"is_enabled": True, "mode": "fixed",
                           "trigger_type": "day_of_month", "trigger_day": 31})
    assert res.status_code == 422


def test_policies_are_per_property(client, world):
    """Switching one block on must leave the other alone."""
    first, second = world["properties"]
    client.put(f"/api/properties/{first.id}/penalty-policy",
               headers=_auth(world["landlord_token"]),
               json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
                     "trigger_type": "day_of_month", "trigger_day": 6})

    other = client.get(f"/api/properties/{second.id}/penalty-policy",
                       headers=_auth(world["landlord_token"]))
    assert other.get_json()["data"]["is_enabled"] is False


# ---------------------------------------------------------------------------
# Property scoping
# ---------------------------------------------------------------------------

def test_scoped_member_can_read_their_own_property(client, world):
    prop = world["properties"][0]
    res = client.get(f"/api/properties/{prop.id}/penalty-policy",
                     headers=_auth(world["member_token"]))
    assert res.status_code == 200


def test_scoped_member_cannot_read_another_block(client, world):
    """404, not 403 — whether that block exists is not theirs to learn."""
    other = world["properties"][1]
    res = client.get(f"/api/properties/{other.id}/penalty-policy",
                     headers=_auth(world["member_token"]))
    assert res.status_code == 404


def test_scoped_member_cannot_change_another_blocks_policy(client, world):
    other = world["properties"][1]
    res = client.put(f"/api/properties/{other.id}/penalty-policy",
                     headers=_auth(world["member_token"]),
                     json={"is_enabled": True, "mode": "fixed",
                           "fixed_amount": 9999,
                           "trigger_type": "day_of_month", "trigger_day": 6})
    assert res.status_code == 404


def test_endpoints_require_authentication(client, world):
    prop = world["properties"][0]
    assert client.get(f"/api/properties/{prop.id}/penalty-policy").status_code == 401
    assert client.get("/api/reports/penalties").status_code == 401
    assert client.get("/api/penalties/preview").status_code == 401


# ---------------------------------------------------------------------------
# Preview and run
# ---------------------------------------------------------------------------

def test_preview_writes_nothing(client, world):
    from models import PenaltyCharge

    prop = world["properties"][0]
    client.put(f"/api/properties/{prop.id}/penalty-policy",
               headers=_auth(world["landlord_token"]),
               json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
                     "trigger_type": "day_of_month", "trigger_day": 6})

    res = client.get("/api/penalties/preview?date=2026-08-06",
                     headers=_auth(world["landlord_token"]))
    assert res.status_code == 200
    assert res.get_json()["data"]["charged"] == 1

    # Scoped to THIS account: the routes under test commit, so rows written by
    # other tests in the same database survive the fixture's rollback. A global
    # count would pass alone and fail in a full run.
    written = (db.session.query(PenaltyCharge)
               .filter_by(landlord_id=world["landlord"].id).count())
    assert written == 0


def test_run_charges_and_is_idempotent_within_the_month(client, world):
    prop = world["properties"][0]
    client.put(f"/api/properties/{prop.id}/penalty-policy",
               headers=_auth(world["landlord_token"]),
               json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
                     "trigger_type": "day_of_month", "trigger_day": 6})

    first = client.post("/api/penalties/run", headers=_auth(world["landlord_token"]),
                        json={"date": "2026-08-06"})
    assert first.status_code == 200, first.get_data(as_text=True)
    assert first.get_json()["data"]["charged"] == 1

    second = client.post("/api/penalties/run", headers=_auth(world["landlord_token"]),
                         json={"date": "2026-08-06"})
    assert second.get_json()["data"]["charged"] == 0


def test_manual_charge_records_its_source(client, world):
    tenant = world["tenants"][0]
    res = client.post("/api/penalties/charge", headers=_auth(world["landlord_token"]),
                      json={"tenant_id": tenant.id, "amount": 250,
                            "note": "Second notice", "date": "2026-08-10"})
    assert res.status_code == 201, res.get_data(as_text=True)
    assert res.get_json()["data"]["source"] == PenaltySource.manual.value


def test_manual_charge_refuses_a_tenant_outside_the_account(client, world, db_session):
    res = client.post("/api/penalties/charge", headers=_auth(world["landlord_token"]),
                      json={"tenant_id": 99999999, "amount": 250})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_report_lists_charges_with_names_and_a_total(client, world):
    prop = world["properties"][0]
    client.put(f"/api/properties/{prop.id}/penalty-policy",
               headers=_auth(world["landlord_token"]),
               json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
                     "trigger_type": "day_of_month", "trigger_day": 6})
    client.post("/api/penalties/run", headers=_auth(world["landlord_token"]),
                json={"date": "2026-08-06"})

    res = client.get("/api/reports/penalties", headers=_auth(world["landlord_token"]))
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["count"] == 1
    assert data["total"] == 500.0
    row = data["items"][0]
    assert row["property_name"] == prop.name
    assert row["tenant_name"]
    assert row["basis_balance"] == "12000.00"
    assert "not commissionable" in data["note"]


def test_report_filters_by_source_and_amount(client, world):
    tenant = world["tenants"][0]
    client.post("/api/penalties/charge", headers=_auth(world["landlord_token"]),
                json={"tenant_id": tenant.id, "amount": 250})

    manual = client.get("/api/reports/penalties?source=manual",
                        headers=_auth(world["landlord_token"]))
    assert manual.get_json()["data"]["count"] == 1

    auto = client.get("/api/reports/penalties?source=auto",
                      headers=_auth(world["landlord_token"]))
    assert auto.get_json()["data"]["count"] == 0

    too_high = client.get("/api/reports/penalties?min_amount=1000",
                          headers=_auth(world["landlord_token"]))
    assert too_high.get_json()["data"]["count"] == 0


def test_a_scoped_members_report_covers_only_their_blocks(client, world):
    """
    Both properties are charged; the scoped member must see exactly one row,
    even though they asked for everything.
    """
    for prop in world["properties"]:
        client.put(f"/api/properties/{prop.id}/penalty-policy",
                   headers=_auth(world["landlord_token"]),
                   json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
                         "trigger_type": "day_of_month", "trigger_day": 6})
    client.post("/api/penalties/run", headers=_auth(world["landlord_token"]),
                json={"date": "2026-08-06"})

    everything = client.get("/api/reports/penalties",
                            headers=_auth(world["landlord_token"]))
    assert everything.get_json()["data"]["count"] == 2

    scoped = client.get("/api/reports/penalties", headers=_auth(world["member_token"]))
    assert scoped.status_code == 200
    rows = scoped.get_json()["data"]["items"]
    assert len(rows) == 1
    assert rows[0]["property_id"] == world["properties"][0].id
