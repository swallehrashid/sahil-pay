"""
Phase 2 — rent-only gross basis and property-manager commission.

The rule these tests protect is a legal one, not a preference: in Kenya a
managing agent may charge commission on RENT COLLECTED only. A rent deposit is
the tenant's refundable money and utilities are collected on the owner's
behalf, so commissioning either would be charging for money that was never the
agent's to earn from.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant, Invoice,
    InvoiceLineItem, Payment, PaymentAllocation, InvoiceStatus, InvoiceType,
    PaymentStatus, PaymentSource,
)
from services.category_service import seed_default_categories, rent_category_id
from services.commission_service import (
    collections_breakdown, commission_for, gross_for, normalise_basis, resolve_basis,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def estate(db_session):
    """
    One property with a 10% commission and a tenant who, inside the window, paid:

        rent current   10,000   commissionable
        rent arrears    5,000   commissionable (still rent)
        deposit        15,000   NEVER commissionable, never income
        water           2,000   collected, but not commissionable
    """
    s = db_session
    n = _uniq()

    user = User(
        email=f"comm-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="property_manager", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Agent {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    seed_default_categories(landlord.id)
    s.flush()

    rent_cat = rent_category_id(landlord.id)
    from models import ChargeCategory
    water_cat = ChargeCategory.query.filter_by(landlord_id=landlord.id, name="Water").first()

    prop = Property(
        landlord_id=landlord.id, name=f"Block {n}", number_of_units=1,
        city="Nairobi", tax_rate=Decimal("0.00"), commission_rate=Decimal("10.00"),
    )
    s.add(prop)
    s.flush()
    unit = Unit(property_id=prop.id, name=f"U{n}", rent_amount=Decimal("10000"))
    s.add(unit)
    s.flush()
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id, first_name="Comm", last_name=n,
        phone=f"+25473{n[:7]}", account_number=f"C-{n}",
    )
    s.add(tenant)
    s.flush()

    today = date.today()
    invoice = Invoice(
        invoice_number=f"INV-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=prop.id, invoice_type=InvoiceType.monthly.value,
        issue_date=today, status=InvoiceStatus.open.value,
        total_amount=Decimal("32000"), amount_paid=Decimal("0"), balance=Decimal("32000"),
    )
    s.add(invoice)
    s.flush()

    def line(item, amount, category_id, subcategory):
        li = InvoiceLineItem(
            invoice_id=invoice.id, item=item, quantity=1,
            unit_price=amount, amount=amount,
            category_id=category_id, subcategory=subcategory,
        )
        s.add(li)
        s.flush()
        return li

    rent_current = line("Rent", Decimal("10000"), rent_cat, "current")
    rent_balance = line("Rent b/f", Decimal("5000"), rent_cat, "balance")
    deposit_line = line("Security deposit", Decimal("15000"), rent_cat, "deposit")
    water_line   = line("Water", Decimal("2000"), water_cat.id, "current")

    payment = Payment(
        payment_ref=f"PMT-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=prop.id, amount=Decimal("32000"),
        payment_date=today, status=PaymentStatus.confirmed.value,
        source=PaymentSource.mpesa.value, payment_method="M-Pesa",
    )
    s.add(payment)
    s.flush()

    for li, amount in (
        (rent_current, "10000"), (rent_balance, "5000"),
        (deposit_line, "15000"), (water_line, "2000"),
    ):
        s.add(PaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, line_item_id=li.id,
            amount_allocated=Decimal(amount),
        ))
    s.commit()

    return {"landlord": landlord, "property": prop, "tenant": tenant,
            "payment": payment, "today": today}


# ---------------------------------------------------------------------------

def test_breakdown_separates_rent_deposits_and_other(estate):
    b = collections_breakdown(
        estate["landlord"].id, estate["property"].id,
        estate["today"], estate["today"],
    )
    assert b["rent_collected"] == Decimal("15000.00"), (
        "rent collected must be current (10,000) + arrears (5,000)"
    )
    assert b["deposits_collected"] == Decimal("15000.00")
    assert b["other_collected"] == Decimal("2000.00"), "water is 'other', not rent"
    assert b["total_collected"] == Decimal("32000.00")


def test_commission_is_ten_percent_of_rent_only(estate):
    b = collections_breakdown(
        estate["landlord"].id, estate["property"].id, estate["today"], estate["today"],
    )
    commission = commission_for(b, estate["property"].commission_rate)
    assert commission == Decimal("1500.00"), (
        "10% of the 15,000 rent collected — NOT of the 32,000 banked, which "
        "would illegally charge on the deposit and the water"
    )


def test_deposit_never_enters_either_gross(estate):
    b = collections_breakdown(
        estate["landlord"].id, estate["property"].id, estate["today"], estate["today"],
    )
    assert gross_for(b, "rent_only") == Decimal("15000.00")
    assert gross_for(b, "all") == Decimal("17000.00"), (
        "'all' means every collection that is INCOME (rent + water); a held "
        "deposit is the tenant's money and is never income"
    )


def test_credit_reapplication_is_not_new_cash(estate, db_session):
    """A payment funded from the tenant's own held credit must not be counted
    again — otherwise the same shilling earns commission twice."""
    s = db_session
    from models import Invoice as Inv

    invoice = Inv.query.filter_by(landlord_id=estate["landlord"].id).first()
    line = invoice.line_items[0]

    credit_payment = Payment(
        payment_ref=f"CR-{_uniq()}", landlord_id=estate["landlord"].id,
        tenant_id=estate["tenant"].id, unit_id=estate["tenant"].unit_id,
        property_id=estate["property"].id, amount=Decimal("4000"),
        payment_date=estate["today"], status=PaymentStatus.confirmed.value,
        source=PaymentSource.credit.value, payment_method="Credit",
    )
    s.add(credit_payment)
    s.flush()
    s.add(PaymentAllocation(
        payment_id=credit_payment.id, invoice_id=invoice.id,
        line_item_id=line.id, amount_allocated=Decimal("4000"),
    ))
    s.commit()

    b = collections_breakdown(
        estate["landlord"].id, estate["property"].id, estate["today"], estate["today"],
    )
    assert b["rent_collected"] == Decimal("15000.00"), (
        "credit-sourced allocations are re-applied money, not new cash"
    )


def test_zero_or_missing_commission_rate_yields_nothing(estate):
    b = collections_breakdown(
        estate["landlord"].id, estate["property"].id, estate["today"], estate["today"],
    )
    assert commission_for(b, None) == Decimal("0.00")
    assert commission_for(b, Decimal("0")) == Decimal("0.00")


def test_basis_resolution_prefers_request_then_saved_preference(estate):
    landlord = estate["landlord"]
    landlord.landlord_settings.report_gross_basis = "rent_only"
    db.session.commit()

    assert resolve_basis(landlord) == "rent_only", "saved preference should stick"
    assert resolve_basis(landlord, "all") == "all", "an explicit request wins"
    # An unknown value falls back to the default basis, which is now
    # "rent_only": on a property statement "gross" means rent collected, and
    # folding utility and penalty income into it overstates what the block
    # earned in rent. Deposits are excluded from every basis regardless.
    assert normalise_basis("nonsense") == "rent_only", "unknown values fall back safely"


def test_property_statement_shows_commission_and_rent_only_gross(estate):
    from services.report_generators import build_property_statement

    doc = build_property_statement(
        estate["landlord"], estate["property"].id,
        estate["today"].isoformat(), estate["today"].isoformat(),
        gross_basis="rent_only",
    )
    summary = next(s for s in doc.sections if s.key == "summary")
    labels = {row["label"]: row["value"] for row in summary.rows}

    gross_label = next(k for k in labels if k.startswith("Gross — rent collected"))
    assert labels[gross_label] == 15000.0

    commission_label = next(k for k in labels if k.startswith("Commission ("))
    assert labels[commission_label] == 1500.0

    deposit_label = next(k for k in labels if k.startswith("Deposits held"))
    assert labels[deposit_label] == 15000.0, "deposits shown, but as an info line"

    assert doc.meta["gross_basis"] == "rent_only"


def test_all_basis_preserves_legacy_totals(estate):
    from services.report_generators import build_property_statement

    doc = build_property_statement(
        estate["landlord"], estate["property"].id,
        estate["today"].isoformat(), estate["today"].isoformat(),
        gross_basis="all",
    )
    summary = next(s for s in doc.sections if s.key == "summary")
    labels = {row["label"]: row["value"] for row in summary.rows}
    assert labels["Total amount collected"] == 17000.0
    assert doc.meta["gross_basis"] == "all"


# ---------------------------------------------------------------------------
# The tenant TABLE, not just the summary
# ---------------------------------------------------------------------------
# The summary read `subcategory` and was right. The table classified by the
# free-text line NAME, in an order that tested "rent" before "deposit" — so a
# line called "Rent Deposit" was counted as RENT in the printed statement while
# the summary underneath it correctly called the same money a held deposit.
# "Water Deposit" and "Security Deposit" were mis-filed the same way.

def _statement_rows(estate, basis="all"):
    from services.report_generators import build_property_statement

    doc = build_property_statement(
        estate["landlord"], estate["property"].id,
        estate["today"].isoformat(), estate["today"].isoformat(),
        gross_basis=basis,
    )
    return next(s for s in doc.sections if s.key == "tenants")


def test_a_deposit_never_lands_in_the_rent_column(estate):
    """
    The fixture's 15,000 deposit is a `rent_cat` line named "Security deposit".
    It must be reported as a deposit, leaving ONLY the 10,000 current-month rent
    charge in the rent column (the 5,000 arrears line is a carried-forward
    re-presentation and is excluded from charges by design — see below).
    """
    totals = _statement_rows(estate).totals

    assert totals["rent"] == Decimal("10000.00"), (
        "rent charged must be the current-month charge alone — no deposit in it"
    )
    assert totals["deposit_invoice"] >= Decimal("15000.00"), "the deposit is reported separately"


def test_the_deposit_is_not_hiding_in_any_income_column(estate):
    """
    The old name-first classifier sent "Security deposit" to the SECURITY column,
    "Water Deposit" to WATER and "Rent Deposit" to RENT. Whichever wording an
    account happens to use, held money must not appear as income anywhere.
    """
    totals = _statement_rows(estate).totals

    for column in ("rent", "water", "security", "garbage", "service_charge",
                   "penalties", "other_bills"):
        assert totals[column] < Decimal("15000.00"), (
            f"the 15,000 deposit leaked into the '{column}' column"
        )


def test_charged_and_collected_are_reported_as_different_measures(estate):
    """
    The table reports rent CHARGED (b/f excluded, so a rolled-over debt is not
    counted as a new charge twice); the summary reports rent COLLECTED (current
    + arrears, because collecting arrears is cash received now). They are
    legitimately different numbers, so the report must not call both "Rent".
    """
    from services.report_generators import build_property_statement

    doc = build_property_statement(
        estate["landlord"], estate["property"].id,
        estate["today"].isoformat(), estate["today"].isoformat(),
        gross_basis="rent_only",
    )
    table = next(s for s in doc.sections if s.key == "tenants")
    summary = next(s for s in doc.sections if s.key == "summary")
    labels = {row["label"]: row["value"] for row in summary.rows}

    rent_column = next(c for c in table.columns if c.key == "rent")
    assert rent_column.label == "Rent charged", "the column must not be ambiguous"

    gross_label = next(k for k in labels if k.startswith("Gross — rent collected"))
    assert labels[gross_label] == 15000.0, "collected = current 10,000 + arrears 5,000"
    assert float(table.totals["rent"]) == 10000.0, "charged = current 10,000"


@pytest.mark.parametrize("name", ["Rent Deposit", "Water Deposit", "Security Deposit",
                                  "rent deposit (refundable)", "Deposit"])
def test_every_spelling_of_a_deposit_classifies_as_a_deposit(name):
    """
    Each of these previously matched an income keyword first. The subcategory is
    the authority now, and the name fallback tests "deposit" before anything else.
    """
    from services.report_generators import _classify_line_item

    class Line:
        def __init__(self, item, subcategory):
            self.item, self.subcategory = item, subcategory

    assert _classify_line_item(Line(name, "deposit")) == "deposit"
    # ...and with no subcategory at all (legacy rows), still a deposit.
    assert _classify_line_item(Line(name, None)) == "deposit"


def test_real_charges_still_classify_correctly():
    """The fix must not send ordinary rent or water into the deposit bucket."""
    from services.report_generators import _classify_line_item

    class Line:
        def __init__(self, item, subcategory):
            self.item, self.subcategory = item, subcategory

    assert _classify_line_item(Line("Rent — August 2026", "current")) == "rent"
    assert _classify_line_item(Line("Rent b/f", "balance")) == "rent"
    assert _classify_line_item(Line("Water — August", "current")) == "water"
    assert _classify_line_item(Line("Security guard levy", "current")) == "security"
    assert _classify_line_item(Line("Late payment penalty", "current")) == "penalties"
