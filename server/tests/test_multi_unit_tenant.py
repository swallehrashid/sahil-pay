"""
Phase 5 — one person, several tenancies.

The scenario that motivated this: a tenant holds two units in Block A and one in
Block B, all managed by different landlords who don't know about each other.
Each unit must keep its own account number, its own invoices and its own
balance — that separation is what makes payments impossible to mix up — while
their single phone signs in once and sees all three.
"""

import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant,
)
from services.tenant_identity_service import (
    normalise_phone, occupancy_summary, same_landlord_siblings,
    sibling_tenant_ids, sibling_tenants,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


def _landlord(s, label):
    n = _uniq()
    u = User(
        email=f"mu-{label}-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    s.add(u)
    s.flush()
    ll = Landlord(user_id=u.id, company_name=f"MU {label} {n}", currency="KES")
    s.add(ll)
    s.flush()
    s.add(LandlordSettings(landlord_id=ll.id))
    s.flush()
    return ll


def _unit(s, landlord, label):
    n = _uniq()
    p = Property(landlord_id=landlord.id, name=f"{label}-{n}", number_of_units=5, city="Nairobi")
    s.add(p)
    s.flush()
    u = Unit(property_id=p.id, name=f"{label}U-{n}", rent_amount=Decimal("10000"))
    s.add(u)
    s.flush()
    return u


def _tenant(s, landlord, unit, phone, *, email=None, user_id=None):
    n = _uniq()
    t = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Multi", last_name="Unit",
        phone=phone, email=email, account_number=f"ACC-{n}",
        user_id=user_id, balance=Decimal("0"),
    )
    s.add(t)
    s.flush()
    return t


@pytest.fixture()
def phone_set():
    """
    One person's number in three stored formats.

    Generated per run: the suite shares a database, so a hardcoded number would
    match tenants left behind by earlier runs and the "who is this person"
    assertions would drift.
    """
    subscriber = f"7{uuid.uuid4().int % 10**8:08d}"   # 9 digits, 7XXXXXXXX
    return {
        "intl":  f"+254{subscriber}",
        "local": f"0{subscriber}",
        "bare":  f"254{subscriber}",
        "other": f"+2547{(uuid.uuid4().int % 10**8):08d}",
    }


@pytest.fixture()
def multi(app, db_session, phone_set):
    """
    One person with:
      * two units under landlord A — stored in two different phone formats,
      * one unit under landlord B, who has never heard of landlord A.
    Plus an unrelated tenant who must never appear in any of it.
    """
    s = db_session

    a = _landlord(s, "A")
    b = _landlord(s, "B")

    a1 = _tenant(s, a, _unit(s, a, "ABlock"), phone_set["intl"])
    # Deliberately a different stored format for the same human.
    a2 = _tenant(s, a, _unit(s, a, "ABlock2"), phone_set["local"])
    b1 = _tenant(s, b, _unit(s, b, "BBlock"), phone_set["bare"])

    other = _tenant(s, a, _unit(s, a, "AOther"), phone_set["other"])
    s.commit()

    with app.app_context():
        token = create_access_token(
            identity=f"tenant:{a1.id}",
            additional_claims={"role": "tenant", "tenant_id": a1.id,
                               "landlord_id": a.id},
        )
    return {"a": a, "b": b, "a1": a1, "a2": a2, "b1": b1,
            "other": other, "token": token, "phones": phone_set}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------

def test_phone_formats_normalise_to_one_person():
    assert normalise_phone("+254712345678") == normalise_phone("0712345678")
    assert normalise_phone("254712345678") == normalise_phone("0712 345 678")
    assert normalise_phone("+254712345678") != normalise_phone("+254799999999")
    assert normalise_phone(None) is None


def test_siblings_span_landlords_but_exclude_strangers(multi):
    ids = sibling_tenant_ids(multi["a1"])
    assert ids == {multi["a1"].id, multi["a2"].id, multi["b1"].id}, (
        "all three tenancies of this person, across both landlords"
    )
    assert multi["other"].id not in ids


def test_landlord_only_told_about_their_own_units(multi):
    """Landlord A must not learn their tenant also rents from landlord B."""
    same = same_landlord_siblings(multi["a1"])
    assert [t.id for t in same] == [multi["a2"].id]

    summary = occupancy_summary(multi["a1"])
    assert summary["unit_count"] == 2, "two units with THIS landlord"
    assert all(u["tenant_id"] != multi["b1"].id for u in summary["other_units"]), (
        "another landlord's tenancy leaked into the landlord-facing summary"
    )


def test_each_unit_keeps_its_own_account_number(multi):
    numbers = {t.account_number for t in sibling_tenants(multi["a1"])}
    assert len(numbers) == 3, (
        "three units must have three distinct account numbers — this is what "
        "stops M-Pesa payments from landing on the wrong unit"
    )


def test_portal_context_lists_every_unit_separately(client, multi):
    resp = client.get("/api/portal/context", headers=_auth(multi["token"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body["unit_count"] == 3
    assert body["current_tenant_id"] == multi["a1"].id
    listed = {u["tenant_id"] for u in body["units"]}
    assert listed == {multi["a1"].id, multi["a2"].id, multi["b1"].id}

    # Grouped by landlord, each with its own account number and balance.
    landlord_ids = {u["landlord_id"] for u in body["units"]}
    assert landlord_ids == {multi["a"].id, multi["b"].id}
    assert all(u["account_number"] for u in body["units"])
    assert body["note"], "a multi-unit tenant is told each unit is paid separately"


def test_switcher_reaches_own_units(client, multi):
    """Asking for another of their own units returns that unit's data."""
    resp = client.get(
        f"/api/portal/dashboard?tenant_id={multi['b1'].id}",
        headers=_auth(multi["token"]),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_switcher_refuses_somebody_elses_unit(client, multi):
    """
    SECURITY: the switcher must not become a way to read any tenant by id.
    """
    resp = client.get(
        f"/api/portal/dashboard?tenant_id={multi['other'].id}",
        headers=_auth(multi["token"]),
    )
    assert resp.status_code == 403, (
        f"expected 403, got {resp.status_code} — the unit switcher let a tenant "
        "read a stranger's account"
    )


def test_switcher_refuses_a_nonexistent_id(client, multi):
    resp = client.get(
        "/api/portal/dashboard?tenant_id=99999999", headers=_auth(multi["token"])
    )
    assert resp.status_code in (403, 404)


def test_one_user_can_own_many_tenant_profiles(db_session, multi):
    """The ORM relationship must be 1:N, not 1:1."""
    s = db_session
    n = _uniq()
    user = User(
        email=f"mu-login-{n}@test.sahilpay", phone=multi["phones"]["intl"],
        role="tenant", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    for tenant in (multi["a1"], multi["a2"], multi["b1"]):
        tenant.user_id = user.id
    s.commit()

    assert len(user.tenant_profiles) == 3, (
        "one login must hold every tenancy the person has"
    )


def test_new_tenant_links_to_an_existing_tenant_login(db_session, multi):
    from services.tenant_identity_service import link_tenant_to_user

    s = db_session
    n = _uniq()
    user = User(
        email=f"mu-link-{n}@test.sahilpay", phone=multi["phones"]["intl"],
        role="tenant", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    fresh = _tenant(s, multi["a"], _unit(s, multi["a"], "ANew"), multi["phones"]["local"])
    s.commit()

    link_tenant_to_user(fresh)
    assert fresh.user_id == user.id, (
        "a new tenancy for a person who already has a login should attach to it"
    )
