"""
Phase 4 — the tenant payment score.

The score is evidence a landlord may extend credit on, so the bands, the
"not enough history" case and the exclusions (deposits, utilities) all have to
behave exactly as specified — a flattering default would be worse than no score.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant, Invoice,
    InvoiceLineItem, Payment, PaymentAllocation, ChargeCategory,
    InvoiceStatus, InvoiceType, PaymentStatus, PaymentSource,
)
from services.category_service import seed_default_categories, rent_category_id
from services.tenant_score_service import band_for_day, compute_tenant_score


def _uniq():
    return uuid.uuid4().hex[:8]


def _month(months_ago: int) -> date:
    return (date.today().replace(day=1) - relativedelta(months=months_ago))


@pytest.fixture()
def estate(db_session):
    s = db_session
    n = _uniq()
    user = User(
        email=f"score-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()
    landlord = Landlord(user_id=user.id, company_name=f"Score {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    seed_default_categories(landlord.id)
    s.flush()
    prop = Property(landlord_id=landlord.id, name=f"P{n}", number_of_units=1, city="Nairobi")
    s.add(prop)
    s.flush()
    s.commit()
    return {"landlord": landlord, "property": prop}


def _make_tenant(s, estate, months_history: int):
    n = _uniq()
    unit = Unit(property_id=estate["property"].id, name=f"U{n}", rent_amount=Decimal("10000"))
    s.add(unit)
    s.flush()
    move_in = _month(months_history)
    tenant = Tenant(
        landlord_id=estate["landlord"].id, unit_id=unit.id,
        first_name="Score", last_name=n, phone=f"+25474{n[:7]}",
        account_number=f"S-{n}", move_in_date=move_in, lease_start_date=move_in,
    )
    s.add(tenant)
    s.flush()
    return tenant


def _bill_rent(s, estate, tenant, month, amount="10000", *, arrears=None):
    """Issue a rent invoice for `month`; optionally add a rent-arrears line."""
    rent_cat = rent_category_id(estate["landlord"].id)
    invoice = Invoice(
        invoice_number=f"INV-{_uniq()}", landlord_id=estate["landlord"].id,
        tenant_id=tenant.id, unit_id=tenant.unit_id, property_id=estate["property"].id,
        invoice_type=InvoiceType.monthly.value, issue_date=month,
        status=InvoiceStatus.open.value, total_amount=Decimal(amount),
        amount_paid=Decimal("0"), balance=Decimal(amount),
    )
    s.add(invoice)
    s.flush()
    line = InvoiceLineItem(
        invoice_id=invoice.id, item="Rent", quantity=1,
        unit_price=Decimal(amount), amount=Decimal(amount),
        category_id=rent_cat, subcategory="current",
    )
    s.add(line)
    if arrears:
        s.add(InvoiceLineItem(
            invoice_id=invoice.id, item="Rent b/f", quantity=1,
            unit_price=Decimal(arrears), amount=Decimal(arrears),
            category_id=rent_cat, subcategory="balance",
        ))
    s.flush()
    return invoice, line


def _pay(s, estate, tenant, invoice, line, when, amount="10000"):
    payment = Payment(
        payment_ref=f"PMT-{_uniq()}", landlord_id=estate["landlord"].id,
        tenant_id=tenant.id, unit_id=tenant.unit_id, property_id=estate["property"].id,
        amount=Decimal(amount), payment_date=when,
        status=PaymentStatus.confirmed.value, source=PaymentSource.mpesa.value,
    )
    s.add(payment)
    s.flush()
    s.add(PaymentAllocation(
        payment_id=payment.id, invoice_id=invoice.id,
        line_item_id=line.id, amount_allocated=Decimal(amount),
    ))
    s.flush()
    return payment


# ---------------------------------------------------------------------------

def test_bands_match_the_specified_five_day_steps():
    assert band_for_day(1) == 100
    assert band_for_day(5) == 100
    assert band_for_day(6) == 90
    assert band_for_day(10) == 90
    assert band_for_day(11) == 80
    assert band_for_day(15) == 80
    assert band_for_day(16) == 70
    assert band_for_day(21) == 60
    assert band_for_day(26) == 50
    assert band_for_day(31) == 50


def test_always_pays_by_the_third_scores_100(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 4)
    for ago in (3, 2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month)
        _pay(s, estate, tenant, inv, line, month.replace(day=3))
    s.commit()

    result = compute_tenant_score(tenant)
    assert result["score"] == 100
    assert result["on_time_rate"] == 100.0
    assert result["avg_pay_day"] == 3.0


def test_always_pays_on_the_twelfth_scores_80(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 4)
    for ago in (3, 2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month)
        _pay(s, estate, tenant, inv, line, month.replace(day=12))
    s.commit()

    assert compute_tenant_score(tenant)["score"] == 80


def test_a_month_paid_late_next_month_scores_zero_for_that_month(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 4)

    # Month A: paid, but not until the following month → 0 for A.
    month_a = _month(3)
    inv_a, line_a = _bill_rent(s, estate, tenant, month_a)
    _pay(s, estate, tenant, inv_a, line_a, (month_a + relativedelta(months=1)).replace(day=4))

    # Months B and C: paid on the 2nd → 100 each.
    for ago in (2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month)
        _pay(s, estate, tenant, inv, line, month.replace(day=2))
    s.commit()

    result = compute_tenant_score(tenant)
    months = {m["month"]: m["band_score"] for m in result["months"]}
    assert months[month_a.strftime("%Y-%m")] == 0, "cleared in a later month scores 0"
    assert result["score"] == round((0 + 100 + 100) / 3)


def test_never_paying_scores_zero(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 4)
    for ago in (3, 2, 1):
        _bill_rent(s, estate, tenant, _month(ago))
    s.commit()

    assert compute_tenant_score(tenant)["score"] == 0


def test_carried_arrears_apply_a_penalty_capped_at_twenty(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 7)

    # Six months, each paid on the 2nd (band 100), but each invoice carries a
    # rent-arrears line meaning the PREVIOUS month closed unpaid.
    for ago in (6, 5, 4, 3, 2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month, arrears="4000")
        _pay(s, estate, tenant, inv, line, month.replace(day=2))
    s.commit()

    result = compute_tenant_score(tenant)
    assert result["penalty"] == 20, "penalty is capped at 20 points"
    assert result["score"] == 80, "100 average minus the capped 20-point penalty"


def test_fewer_than_two_months_is_new_not_a_perfect_score(db_session, estate):
    s = db_session
    tenant = _make_tenant(s, estate, 1)
    month = _month(1)
    inv, line = _bill_rent(s, estate, tenant, month)
    _pay(s, estate, tenant, inv, line, month.replace(day=1))
    s.commit()

    result = compute_tenant_score(tenant)
    assert result["score"] is None, "one month of history cannot justify a score"
    assert result["reason"] == "new_tenant"


def test_deposits_and_utilities_do_not_affect_the_score(db_session, estate):
    """A tenant who pays rent late but clears a big deposit early stays low."""
    s = db_session
    tenant = _make_tenant(s, estate, 4)
    rent_cat = rent_category_id(estate["landlord"].id)
    water = ChargeCategory.query.filter_by(
        landlord_id=estate["landlord"].id, name="Water"
    ).first()

    for ago in (3, 2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month)

        # A deposit line and a water line, both paid on day 1 — neither counts.
        deposit = InvoiceLineItem(
            invoice_id=inv.id, item="Deposit", quantity=1,
            unit_price=Decimal("20000"), amount=Decimal("20000"),
            category_id=rent_cat, subcategory="deposit",
        )
        water_line = InvoiceLineItem(
            invoice_id=inv.id, item="Water", quantity=1,
            unit_price=Decimal("1500"), amount=Decimal("1500"),
            category_id=water.id, subcategory="current",
        )
        s.add_all([deposit, water_line])
        s.flush()

        early = _pay(s, estate, tenant, inv, deposit, month.replace(day=1), amount="20000")
        s.add(PaymentAllocation(
            payment_id=early.id, invoice_id=inv.id,
            line_item_id=water_line.id, amount_allocated=Decimal("1500"),
        ))
        # Rent itself only paid on the 24th → band 60.
        _pay(s, estate, tenant, inv, line, month.replace(day=24))
    s.commit()

    assert compute_tenant_score(tenant)["score"] == 60, (
        "an early deposit payment must not flatter a tenant who pays rent late"
    )


def test_refresh_persists_the_score_on_the_tenant_row(db_session, estate):
    from services.tenant_score_service import refresh_tenant_score

    s = db_session
    tenant = _make_tenant(s, estate, 4)
    for ago in (3, 2, 1):
        month = _month(ago)
        inv, line = _bill_rent(s, estate, tenant, month)
        _pay(s, estate, tenant, inv, line, month.replace(day=2))
    s.commit()

    refresh_tenant_score(tenant, commit=True)
    assert tenant.tenant_score == 100
    assert tenant.tenant_score_updated_at is not None
    assert tenant.to_dict()["tenant_score_label"] == "Excellent"
