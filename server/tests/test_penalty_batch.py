"""
Manual batch penalty runs — "charge these people, now".

The automatic engine applies a standing POLICY on a schedule. This is the other
half: a decision a manager takes on a Tuesday, against a filtered list they can
see and edit first. The parts worth pinning are the ones where being wrong costs
a tenant money:

  THE FILTERS actually filter, and compose.
  DAYS OVERDUE is measured from the OLDEST unpaid invoice — dating it from the
    newest would let the worst debtors slip under a "more than 10 days" filter.
  THE SIGN of the ledger effect. penalty_service.arrears_of() warns that getting
    it backwards "silently penalises the wrong people".
  RUNNING TWICE does not charge twice.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Invoice, InvoiceStatus, Landlord, LandlordSettings,
    PenaltyCharge, Property, Tenant, Unit, User,
)
from services import penalty_batch_service as batch


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def book(app, db_session):
    """
    Two blocks. Three tenants owing different amounts, late by different
    numbers of days, plus one who owes nothing.
    """
    s = db_session
    n = _uniq()

    owner = User(email=f"pb-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Pen {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Penalty",
                         kind="invoice", is_metered=False))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Rent",
                         kind="invoice", is_metered=False))
    s.flush()

    today = date.today()
    blocks, tenants = {}, {}

    # (block, name, owes, days late)
    spec = [
        ("Alpha", "Deep",    Decimal("30000"), 40),
        ("Alpha", "Shallow", Decimal("2000"),  3),
        ("Beta",  "Middle",  Decimal("12000"), 15),
        ("Beta",  "Settled", Decimal("0"),     0),
    ]

    for block, who, owes, late in spec:
        if block not in blocks:
            prop = Property(landlord_id=landlord.id, name=f"{block}-{n}",
                            city="Nairobi", street_name="Road")
            s.add(prop)
            s.flush()
            blocks[block] = prop
        prop = blocks[block]

        unit = Unit(landlord_id=landlord.id, property_id=prop.id,
                    name=f"{who[:2]}{n[:3]}", rent_amount=Decimal("25000"))
        s.add(unit)
        s.flush()

        tenant = Tenant(
            landlord_id=landlord.id, unit_id=unit.id,
            first_name=who, last_name=n[:4],
            phone=f"2547{abs(hash(who)) % 10000000:07d}",
            account_number=f"{who[:2]}{n}",
            # NEGATIVE when owed — see penalty_service.arrears_of().
            balance=-owes,
        )
        s.add(tenant)
        s.flush()
        tenants[who] = tenant

        if owes > 0:
            invoice = Invoice(
                landlord_id=landlord.id, tenant_id=tenant.id, unit_id=unit.id,
                property_id=prop.id, invoice_number=f"INV-{who}-{n}",
                invoice_type="rent", title="Rent",
                issue_date=today - timedelta(days=late),
                due_date=today - timedelta(days=late),
                total_amount=owes, amount_paid=Decimal("0"),
                balance=owes, status=InvoiceStatus.open.value,
            )
            s.add(invoice)
            s.flush()

    return {"landlord": landlord, "blocks": blocks, "tenants": tenants}


def _names(rows):
    return {r["tenant_name"].split()[0] for r in rows}


# ---------------------------------------------------------------------------
# Who is on the list
# ---------------------------------------------------------------------------

def test_only_tenants_who_owe_are_candidates(app, book):
    rows = batch.candidates(book["landlord"].id)

    assert _names(rows) == {"Deep", "Shallow", "Middle"}
    assert "Settled" not in _names(rows)


def test_a_balance_range_narrows_the_list(app, book):
    rows = batch.candidates(book["landlord"].id, min_balance=10000, max_balance=25000)

    assert _names(rows) == {"Middle"}


def test_days_overdue_is_measured_from_the_oldest_unpaid_invoice(app, book):
    """
    Dating lateness from the NEWEST invoice would let a tenant three months
    behind look a week late, which is exactly backwards.
    """
    rows = batch.candidates(book["landlord"].id, min_days_overdue=30)

    assert _names(rows) == {"Deep"}
    deep = next(r for r in rows if r["tenant_name"].startswith("Deep"))
    assert deep["days_overdue"] >= 40


def test_filtering_by_property_works(app, book):
    alpha = book["blocks"]["Alpha"].id
    rows = batch.candidates(book["landlord"].id, property_ids=[alpha])

    assert _names(rows) == {"Deep", "Shallow"}


def test_filters_compose(app, book):
    """The real question is always a combination."""
    rows = batch.candidates(
        book["landlord"].id,
        property_ids=[book["blocks"]["Alpha"].id],
        min_balance=10000,
        min_days_overdue=10,
    )

    assert _names(rows) == {"Deep"}


def test_property_scope_is_enforced_not_merely_offered(app, book):
    """
    A block-scoped member must not reach another block's tenants by passing its
    id — the scope has to win over the filter.
    """
    alpha = book["blocks"]["Alpha"].id
    beta = book["blocks"]["Beta"].id

    rows = batch.candidates(book["landlord"].id, property_ids=[beta],
                            allowed_property_ids={alpha})

    assert rows == []


def test_the_worst_debtors_are_listed_first(app, book):
    """The list is read top-down before money is charged on it."""
    rows = batch.candidates(book["landlord"].id)

    assert rows[0]["tenant_name"].startswith("Deep")


# ---------------------------------------------------------------------------
# Charging
# ---------------------------------------------------------------------------

def test_a_flat_charge_lands_on_a_new_invoice(app, book):
    deep = book["tenants"]["Deep"]
    before = deep.balance

    result = batch.run(book["landlord"], [deep.id], flat=500, target="new")

    assert len(result["charged"]) == 1
    assert result["total_charged"] == 500.0
    db.session.refresh(deep)
    # Charges make the balance MORE negative.
    assert deep.balance == before - Decimal("500")


def test_a_percentage_charge_is_proportional_to_what_is_owed(app, book):
    """
    5% of 2,000 and 5% of 30,000 are proportionate, where a flat fee is punitive
    on one and trivial on the other.
    """
    deep = book["tenants"]["Deep"]          # owes 30,000
    shallow = book["tenants"]["Shallow"]    # owes 2,000

    result = batch.run(book["landlord"], [deep.id, shallow.id], percentage=5,
                       target="new")

    charged = {c["tenant_name"].split()[0]: c["amount"] for c in result["charged"]}
    assert charged["Deep"] == 1500.0
    assert charged["Shallow"] == 100.0


def test_charging_onto_an_existing_invoice_appends_a_line(app, book):
    """One bill rather than two in the same month."""
    middle = book["tenants"]["Middle"]
    invoice = Invoice.query.filter_by(tenant_id=middle.id).first()
    before_total = invoice.total_amount
    before_lines = len(invoice.line_items)

    batch.run(book["landlord"], [middle.id], flat=500, target="existing")

    db.session.refresh(invoice)
    assert invoice.total_amount == before_total + Decimal("500")
    assert len(invoice.line_items) == before_lines + 1
    assert "Penalty" in (invoice.title or "")


def test_appending_falls_back_to_a_new_invoice_when_nothing_is_open(app, book, db_session):
    """
    A tenant with no current bill still has to be charged somehow — silently
    skipping them would make the run's totals wrong.
    """
    middle = book["tenants"]["Middle"]
    Invoice.query.filter_by(tenant_id=middle.id).update({"status": InvoiceStatus.paid.value})
    db_session.flush()

    result = batch.run(book["landlord"], [middle.id], flat=500, target="existing")

    assert len(result["charged"]) == 1
    assert result["charged"][0]["invoice_id"] is not None


def test_a_manual_charge_is_recorded_like_an_automatic_one(app, book):
    """
    So the penalties report and the month guard see it. A charge that only
    existed as an invoice line would be invisible to both.
    """
    deep = book["tenants"]["Deep"]
    batch.run(book["landlord"], [deep.id], flat=500, target="existing")

    charge = PenaltyCharge.query.filter_by(tenant_id=deep.id).first()
    assert charge is not None
    assert charge.source == "manual"
    assert charge.amount == Decimal("500.00")
    assert charge.basis_balance == Decimal("30000.00")


def test_running_the_same_batch_twice_does_not_charge_twice(app, book):
    """The mistake this guard exists for."""
    deep = book["tenants"]["Deep"]

    first = batch.run(book["landlord"], [deep.id], flat=500, target="new")
    second = batch.run(book["landlord"], [deep.id], flat=500, target="new")

    assert len(first["charged"]) == 1
    assert second["charged"] == []
    assert "already penalised this month" in second["skipped"][0]["reason"]


def test_the_guard_can_be_overridden_deliberately(app, book):
    """A second, intentional charge in one month is a real thing to want."""
    deep = book["tenants"]["Deep"]
    batch.run(book["landlord"], [deep.id], flat=500, target="new")

    second = batch.run(book["landlord"], [deep.id], flat=500, target="new",
                       skip_already_charged=False)

    assert len(second["charged"]) == 1


def test_a_tenant_who_owes_nothing_is_skipped_with_a_reason(app, book):
    settled = book["tenants"]["Settled"]

    result = batch.run(book["landlord"], [settled.id], flat=500, target="new")

    assert result["charged"] == []
    assert result["skipped"][0]["reason"] == "owes nothing"


def test_one_bad_tenant_does_not_abandon_the_run(app, book):
    """
    Errors are collected per tenant. A run that stops half way leaves a manager
    unable to tell who was charged.
    """
    deep = book["tenants"]["Deep"]

    result = batch.run(book["landlord"], [999999, deep.id], flat=500, target="new")

    assert len(result["charged"]) == 1
    assert len(result["skipped"]) == 1


def test_a_tenant_from_another_account_is_refused(app, book, db_session):
    n = _uniq()
    other_user = User(email=f"pbx-{n}@test.sahilpay", phone=f"2546{n[:7]}",
                      password_hash=generate_password_hash("Testpass1"),
                      role="landlord", is_verified=True, is_active=True)
    db_session.add(other_user)
    db_session.flush()
    other = Landlord(user_id=other_user.id, company_name=f"Other {n}", currency="KES")
    db_session.add(other)
    db_session.flush()
    prop = Property(landlord_id=other.id, name=f"X-{n}", city="Nairobi")
    db_session.add(prop)
    db_session.flush()
    unit = Unit(landlord_id=other.id, property_id=prop.id, name=f"X{n[:3]}",
                rent_amount=Decimal("1000"))
    db_session.add(unit)
    db_session.flush()
    stranger = Tenant(landlord_id=other.id, unit_id=unit.id, first_name="Stranger",
                      last_name=n[:4], phone=f"2545{n[:7]}",
                      account_number=f"X{n}", balance=Decimal("-9000"))
    db_session.add(stranger)
    db_session.flush()

    result = batch.run(book["landlord"], [stranger.id], flat=500, target="new")

    assert result["charged"] == []
    assert "not found on this account" in result["skipped"][0]["reason"]


def test_zero_amount_is_refused_rather_than_written(app, book):
    deep = book["tenants"]["Deep"]

    result = batch.run(book["landlord"], [deep.id], flat=0, target="new")

    assert result["charged"] == []
    assert "zero" in result["skipped"][0]["reason"]
