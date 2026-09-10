"""
What a list endpoint tells you when the account is big.

Two defects, both invisible on a seed database and both certain on a real one:

  1. NO SEARCH. Units, expenses and payments could only be paged through. A
     property manager here has 1,000 units; finding "B12" meant clicking Next
     fifty times. Tenants and team members had a `search` parameter the client
     never passed, which is the same thing with extra steps.

  2. THE SUMMARY DESCRIBED A DIFFERENT SET FROM THE TABLE. Every list endpoint
     returns aggregates under `summary`, and every one of them was computed
     from a SEPARATE, UNFILTERED query. Search for one property and the table
     showed one row while the card above it still read 100 — two numbers on the
     same screen disagreeing about the same question. (The client compounded
     this by reading the aggregates from the wrong place entirely and falling
     back to counting the rows on the current page, which is the page size.)

These assert both: that filtering works, and that the summary follows it.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    Expense, Landlord, LandlordSettings, Property, Tenant, Unit, User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def estate(db_session):
    """Two blocks with distinct names, so a search can tell them apart."""
    n = _uniq()
    user = User(email=f"list-{n}@test.sahilpay", phone=f"2547{n}01",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True, is_active=True)
    db_session.add(user)
    db_session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"List Test {n}", currency="KES")
    db_session.add(landlord)
    db_session.flush()
    db_session.add(LandlordSettings(landlord_id=landlord.id))

    riverside = Property(landlord_id=landlord.id, name=f"Riverside {n}", city="Nairobi")
    hilltop = Property(landlord_id=landlord.id, name=f"Hilltop {n}", city="Nakuru")
    db_session.add_all([riverside, hilltop])
    db_session.flush()

    units = []
    for prop, count, prefix in ((riverside, 6, "RV"), (hilltop, 4, "HT")):
        for i in range(count):
            u = Unit(landlord_id=landlord.id, property_id=prop.id,
                     name=f"{prefix}{i:02d}", rent_amount=Decimal("20000"),
                     is_occupied=i % 2 == 0)
            db_session.add(u)
            units.append(u)
    db_session.flush()

    # One tenant per occupied unit, half of them in arrears.
    tenants = []
    for i, u in enumerate(units):
        if not u.is_occupied:
            continue
        # Alternate on the TENANT index, not the unit index: only even-numbered
        # units are occupied, so keying off `i` gave every tenant the same name
        # and a name search matched all of them.
        t = Tenant(landlord_id=landlord.id, unit_id=u.id,
                   first_name="Amina" if len(tenants) % 2 == 0 else "Brian",
                   last_name=f"Ochieng{i}", phone=f"25471{n[:6]}{i}",
                   account_number=f"ACC{n}{i}", balance=Decimal("-5000"),
                   lease_start_date=date.today() - timedelta(days=200),
                   lease_expiry_date=date.today() + timedelta(days=10 if i == 0 else 400),
                   deposit_amount=Decimal("20000"))
        db_session.add(t)
        tenants.append(t)

    db_session.add(Expense(landlord_id=landlord.id, property_id=riverside.id,
                           category="plumbing", amount=Decimal("4500"),
                           expense_date=date.today(), notes="Fixed the riser"))
    db_session.add(Expense(landlord_id=landlord.id, property_id=hilltop.id,
                           category="security", amount=Decimal("9000"),
                           expense_date=date.today(), notes="Gate motor"))
    db_session.commit()

    from services.unit_counts import recount
    recount(landlord_id=landlord.id)
    db_session.commit()

    return {"user": user, "landlord": landlord, "riverside": riverside,
            "hilltop": hilltop, "units": units, "tenants": tenants, "n": n}


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token(identity=str(user.id), additional_claims={'role': user.role})}"}


def _get(client, estate, path, **params):
    from urllib.parse import urlencode

    qs = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    response = client.get(f"{path}?{qs}", headers=_auth(estate["user"]))
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _rows(body):
    return next(v for v in body.values() if isinstance(v, list))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_units_can_be_searched_by_unit_name(client, estate):
    body = _get(client, estate, "/api/units/", search="RV0")

    names = [u["name"] for u in _rows(body)]
    assert names, "no units matched"
    assert all(name.startswith("RV") for name in names)


def test_units_can_be_searched_by_their_property(client, estate):
    """
    At 1,000 units nobody remembers which block a unit is in — narrowing by the
    block name is the other half of the same search.
    """
    body = _get(client, estate, "/api/units/", search=f"Riverside {estate['n']}")

    assert len(_rows(body)) == 6
    assert body["summary"]["total_units"] == 6


def test_expenses_can_be_searched_by_category_and_note(client, estate):
    by_category = _get(client, estate, "/api/expenses/", search="plumbing")
    by_note = _get(client, estate, "/api/expenses/", search="Gate motor")

    assert len(_rows(by_category)) == 1
    assert len(_rows(by_note)) == 1
    assert _rows(by_category)[0]["category"] == "plumbing"


def test_expenses_can_be_searched_by_property(client, estate):
    body = _get(client, estate, "/api/expenses/", search=f"Hilltop {estate['n']}")

    assert len(_rows(body)) == 1


def test_tenants_can_be_searched_by_name(client, estate):
    body = _get(client, estate, "/api/tenants/", search="Amina")

    rows = _rows(body)
    assert rows
    assert all(t["first_name"] == "Amina" for t in rows)


def test_a_search_that_matches_nothing_returns_an_empty_list_not_everything(client, estate):
    """
    The failure that hurts: an unmatched filter silently ignored, so the table
    shows the whole book and looks like the search is broken in the other
    direction.
    """
    body = _get(client, estate, "/api/units/", search="zzz-no-such-unit-zzz")

    assert _rows(body) == []
    assert body["summary"]["total_units"] == 0


# ---------------------------------------------------------------------------
# The summary describes what the table is showing
# ---------------------------------------------------------------------------

def test_the_property_summary_follows_the_filter(client, estate):
    everything = _get(client, estate, "/api/properties/")
    filtered = _get(client, estate, "/api/properties/", name=f"Riverside {estate['n']}")

    assert everything["summary"]["total_properties"] == 2
    assert everything["summary"]["total_units"] == 10

    # One block, and ONLY that block's units.
    assert filtered["summary"]["total_properties"] == 1
    assert filtered["summary"]["total_units"] == 6
    assert filtered["summary"]["total_vacancies"] == 3


def test_the_unit_summary_follows_the_filter(client, estate):
    filtered = _get(client, estate, "/api/units/", search=f"Hilltop {estate['n']}")

    assert filtered["summary"]["total_units"] == 4
    assert filtered["summary"]["total_vacancies"] == 2


def test_the_unit_summary_counts_the_properties_the_matches_belong_to(client, estate):
    """
    All three cards on the Units page have to describe the same set. Taking the
    property count from a separate properties query left it reading "2
    properties" beside "8 units" that were all in one of them.
    """
    everything = _get(client, estate, "/api/units/")
    filtered = _get(client, estate, "/api/units/", search=f"Hilltop {estate['n']}")

    assert everything["summary"]["total_properties"] == 2
    assert filtered["summary"]["total_properties"] == 1


def test_the_tenant_summary_follows_the_filter(client, estate):
    everything = _get(client, estate, "/api/tenants/")
    filtered = _get(client, estate, "/api/tenants/", search="Amina")

    assert filtered["summary"]["total_tenants"] == len(_rows(filtered))
    assert filtered["summary"]["total_tenants"] < everything["summary"]["total_tenants"]
    # Arrears must describe the filtered set too, not the whole book.
    assert filtered["summary"]["total_arrears"] < everything["summary"]["total_arrears"]


def test_arrears_are_owed_money_only_and_advances_do_not_net_them_off(client, estate, db_session):
    """
    A tenant in credit must not cancel out a tenant in arrears. "Total arrears"
    is what is owed, not the net position of the book.
    """
    before = _get(client, estate, "/api/tenants/")["summary"]["total_arrears"]

    in_credit = estate["tenants"][0]
    in_credit.balance = Decimal("50000")     # a large advance
    db_session.commit()

    after = _get(client, estate, "/api/tenants/")["summary"]["total_arrears"]

    assert after == before - 5000, "an advance was netted against arrears"
    assert after >= 0


def test_leases_expiring_uses_the_key_the_client_reads(client, estate):
    """
    The server sends `leases_expiring`; the page asked for
    `leases_expiring_soon` and so displayed 0 forever. Pin the name.
    """
    summary = _get(client, estate, "/api/tenants/")["summary"]

    assert "leases_expiring" in summary
    assert summary["leases_expiring"] >= 1     # one lease was seeded 10 days out


def test_the_summary_is_not_the_page(client, estate):
    """
    The heart of it: ask for two rows a page and the summary must still describe
    all ten units. Counting the rows on screen is what produced "20" on an
    account with a thousand.
    """
    body = _get(client, estate, "/api/units/", per_page=2)

    assert len(_rows(body)) == 2
    assert body["total"] == 10
    assert body["summary"]["total_units"] == 10


def test_the_response_says_which_page_it_is(client, estate):
    """`current_page` — the client read `page`, which does not exist, so the
    pager reported page 1 whichever page you were on."""
    body = _get(client, estate, "/api/units/", per_page=3, page=2)

    assert body["current_page"] == 2
    assert body["pages"] == 4


# ---------------------------------------------------------------------------
# Unit counts are derived, not typed
# ---------------------------------------------------------------------------

def test_a_property_reports_the_units_that_actually_exist(client, estate):
    body = _get(client, estate, "/api/properties/")
    by_name = {p["name"]: p for p in _rows(body)}

    assert by_name[estate["riverside"].name]["number_of_units"] == 6
    assert by_name[estate["hilltop"].name]["number_of_units"] == 4


def test_creating_a_unit_updates_the_count(client, estate, db_session):
    prop = estate["riverside"]
    response = client.post("/api/units/", headers=_auth(estate["user"]),
                           json={"property_id": prop.id, "name": f"NEW{_uniq()[:4]}",
                                 "rent_amount": 15000})
    assert response.status_code == 201, response.get_data(as_text=True)

    db_session.refresh(prop)
    assert prop.number_of_units == 7


def test_deleting_a_unit_updates_the_count(client, estate, db_session):
    """Without this the number only ever went up."""
    prop = estate["riverside"]
    victim = next(u for u in estate["units"] if u.property_id == prop.id and not u.is_occupied)

    response = client.delete(f"/api/units/{victim.id}", headers=_auth(estate["user"]))
    assert response.status_code == 200

    db_session.refresh(prop)
    assert prop.number_of_units == 5


def test_a_property_can_be_created_without_saying_how_many_units(client, estate, db_session):
    """
    It was REQUIRED, which is a question nobody can answer correctly at that
    moment and which is wrong the first time a unit is added.
    """
    response = client.post("/api/properties/", headers=_auth(estate["user"]),
                           json={"name": f"Newblock {_uniq()}", "city": "Nairobi"})

    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["number_of_units"] == 0


def test_recount_repairs_a_count_that_has_drifted(estate, db_session):
    """The backfill: a stored figure that disagrees with reality is corrected."""
    from services.unit_counts import recount

    prop = estate["riverside"]
    prop.number_of_units = 999
    db_session.commit()

    recount([prop.id])
    db_session.commit()
    db_session.refresh(prop)

    assert prop.number_of_units == 6


def test_recount_covers_a_whole_account_in_one_go(estate, db_session):
    """What a bulk import needs: one statement, however many properties."""
    from services.unit_counts import recount

    for prop in (estate["riverside"], estate["hilltop"]):
        prop.number_of_units = 0
    db_session.commit()

    recount(landlord_id=estate["landlord"].id)
    db_session.commit()

    db_session.refresh(estate["riverside"])
    db_session.refresh(estate["hilltop"])
    assert estate["riverside"].number_of_units == 6
    assert estate["hilltop"].number_of_units == 4


def test_a_deleted_unit_does_not_count(estate, db_session):
    from services.unit_counts import recount

    victim = next(u for u in estate["units"] if u.property_id == estate["riverside"].id)
    victim.is_deleted = True
    db_session.commit()

    recount([estate["riverside"].id])
    db_session.commit()
    db_session.refresh(estate["riverside"])

    assert estate["riverside"].number_of_units == 5
