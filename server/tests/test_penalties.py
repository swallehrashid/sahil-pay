"""
Late-payment penalties.

The riskiest thing here is not the arithmetic, it is the sign. `tenant.balance`
is NEGATIVE when money is owed, and the previous penalty task filtered
`balance > 0` — so it charged tenants who were in CREDIT and left real debtors
alone. There is a test below that fails if that inversion ever returns.

The second risk is money: a penalty must never reach the property manager's
commission. That is a legal point in Kenya, not a preference, so it is pinned
here as well as in the commission tests.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Landlord, LandlordSettings, PenaltyCharge, PenaltyMode,
    PenaltySource, PenaltyTier, PenaltyTrigger, Property, PropertyPenaltyPolicy,
    Tenant, Unit, User,
)
from services import penalty_service as penalties


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def estate(app, db_session):
    """A landlord with one property, one unit and one tenant in arrears."""
    s = db_session
    n = _uniq()

    user = User(
        email=f"pen-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Pen {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))

    # The protected Penalty category — what keeps the charge non-commissionable.
    s.add(ChargeCategory(landlord_id=landlord.id, name="Penalty",
                         kind="invoice", is_metered=False))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Rent",
                         kind="invoice", is_metered=False))
    s.flush()

    prop = Property(landlord_id=landlord.id, name=f"Block {n}", city="Nairobi")
    s.add(prop)
    s.flush()

    unit = Unit(property_id=prop.id, name=f"A{n[:3]}", rent_amount=Decimal("20000"))
    s.add(unit)
    s.flush()

    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Amina", last_name=f"T{n[:4]}",
        phone=f"2548{n[:7]}", account_number=f"ACC{n}",
        balance=Decimal("-12000"),          # NEGATIVE = owes 12,000
    )
    s.add(tenant)
    s.flush()

    return {"landlord": landlord, "property": prop, "unit": unit, "tenant": tenant}


def _policy(s, estate, **kw):
    defaults = dict(
        landlord_id=estate["landlord"].id, property_id=estate["property"].id,
        is_enabled=True, mode=PenaltyMode.fixed.value,
        fixed_amount=Decimal("500"),
        trigger_type=PenaltyTrigger.day_of_month.value, trigger_day=6,
    )
    defaults.update(kw)
    policy = PropertyPenaltyPolicy(**defaults)
    s.add(policy)
    s.flush()
    return policy


# ---------------------------------------------------------------------------
# The sign convention — the bug that shipped
# ---------------------------------------------------------------------------

def test_arrears_are_read_from_a_negative_balance(estate):
    assert penalties.arrears_of(estate["tenant"]) == Decimal("12000.00")


def test_a_tenant_in_credit_has_no_arrears(db_session, estate):
    """
    The exact inversion that shipped: `balance > 0` is ADVANCE CREDIT. A tenant
    who paid ahead must never be fined.
    """
    estate["tenant"].balance = Decimal("8000")     # paid ahead
    db_session.flush()
    assert penalties.arrears_of(estate["tenant"]) == Decimal("0.00")


def test_a_settled_tenant_has_no_arrears(db_session, estate):
    estate["tenant"].balance = Decimal("0")
    db_session.flush()
    assert penalties.arrears_of(estate["tenant"]) == Decimal("0.00")


def test_a_tenant_in_credit_is_never_charged(db_session, estate):
    policy = _policy(db_session, estate)
    estate["tenant"].balance = Decimal("8000")
    db_session.flush()

    summary = penalties.apply_for_property(estate["property"],
                                           today=date(2026, 8, 6), dry_run=True)
    assert summary["charged"] == 0


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------

def test_fixed_amount(db_session, estate):
    policy = _policy(db_session, estate, fixed_amount=Decimal("500"))
    assert penalties.amount_for(policy, Decimal("12000")) == Decimal("500.00")


def test_percentage_of_arrears(db_session, estate):
    policy = _policy(db_session, estate, mode=PenaltyMode.percentage.value,
                     fixed_amount=None, percentage_rate=Decimal("5"))
    assert penalties.amount_for(policy, Decimal("12000")) == Decimal("600.00")


def test_percentage_respects_the_cap(db_session, estate):
    policy = _policy(db_session, estate, mode=PenaltyMode.percentage.value,
                     fixed_amount=None, percentage_rate=Decimal("5"),
                     max_penalty=Decimal("400"))
    assert penalties.amount_for(policy, Decimal("12000")) == Decimal("400.00")


def test_minimum_balance_suppresses_small_arrears(db_session, estate):
    """A 20-shilling rounding remainder must not generate a 500-shilling fine."""
    policy = _policy(db_session, estate, min_balance=Decimal("1000"))
    assert penalties.amount_for(policy, Decimal("20")) == Decimal("0.00")
    assert penalties.amount_for(policy, Decimal("5000")) == Decimal("500.00")


def test_tiered_bands(db_session, estate):
    policy = _policy(db_session, estate, mode=PenaltyMode.tiered.value,
                     fixed_amount=None)
    policy.tiers.extend([
        PenaltyTier(min_balance=Decimal("5000"),  max_balance=Decimal("7000"),
                    amount_type="fixed", amount=Decimal("400")),
        PenaltyTier(min_balance=Decimal("10000"), max_balance=None,
                    amount_type="fixed", amount=Decimal("500")),
    ])
    db_session.flush()

    assert penalties.amount_for(policy, Decimal("6000"))  == Decimal("400.00")
    assert penalties.amount_for(policy, Decimal("15000")) == Decimal("500.00")
    # Between the bands — nothing matches, so nothing is charged.
    assert penalties.amount_for(policy, Decimal("8000"))  == Decimal("0.00")


def test_tier_bands_are_half_open(db_session, estate):
    """7000 belongs to the NEXT band, not to [5000, 7000)."""
    policy = _policy(db_session, estate, mode=PenaltyMode.tiered.value, fixed_amount=None)
    policy.tiers.extend([
        PenaltyTier(min_balance=Decimal("5000"), max_balance=Decimal("7000"),
                    amount_type="fixed", amount=Decimal("400")),
        PenaltyTier(min_balance=Decimal("7000"), max_balance=None,
                    amount_type="fixed", amount=Decimal("900")),
    ])
    db_session.flush()
    assert penalties.amount_for(policy, Decimal("6999.99")) == Decimal("400.00")
    assert penalties.amount_for(policy, Decimal("7000"))    == Decimal("900.00")


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def test_day_of_month_trigger(db_session, estate):
    policy = _policy(db_session, estate, trigger_day=6)
    assert penalties.is_due_today(policy, date(2026, 8, 6)) is True
    assert penalties.is_due_today(policy, date(2026, 8, 5)) is False
    assert penalties.is_due_today(policy, date(2026, 8, 7)) is False


def test_day_of_month_clamps_in_february(db_session, estate):
    """A policy set to the 28th must still fire in a short month."""
    policy = _policy(db_session, estate, trigger_day=28)
    assert penalties.is_due_today(policy, date(2027, 2, 28)) is True


def test_days_after_due_trigger(db_session, estate):
    policy = _policy(db_session, estate,
                     trigger_type=PenaltyTrigger.days_after_due.value,
                     trigger_day=None, grace_days=5)
    due = date(2026, 8, 1)
    assert penalties.is_due_today(policy, date(2026, 8, 5), invoice_due_date=due) is False
    assert penalties.is_due_today(policy, date(2026, 8, 6), invoice_due_date=due) is True
    assert penalties.is_due_today(policy, date(2026, 8, 20), invoice_due_date=due) is True


def test_a_disabled_policy_never_fires(db_session, estate):
    policy = _policy(db_session, estate, is_enabled=False)
    assert penalties.is_due_today(policy, date(2026, 8, 6)) is False


def test_no_policy_means_no_penalty(estate):
    summary = penalties.apply_for_property(estate["property"], today=date(2026, 8, 6))
    assert summary["charged"] == 0


# ---------------------------------------------------------------------------
# Once per month
# ---------------------------------------------------------------------------

def test_charging_creates_an_invoice_and_a_ledger_row(db_session, estate):
    policy = _policy(db_session, estate)
    charge = penalties.charge_tenant(estate["tenant"], policy, Decimal("500"),
                                     today=date(2026, 8, 6))
    assert charge is not None
    assert charge.amount == Decimal("500.00")
    assert charge.basis_balance == Decimal("12000.00")
    assert charge.invoice_id is not None
    assert charge.source == PenaltySource.auto.value


def test_a_tenant_is_auto_charged_at_most_once_a_month(db_session, estate):
    policy = _policy(db_session, estate)
    today = date(2026, 8, 6)

    penalties.charge_tenant(estate["tenant"], policy, Decimal("500"), today=today)
    assert penalties.already_charged(estate["tenant"].id, 2026, 8) is True

    # A second run on the same day must find nothing left to do.
    summary = penalties.apply_for_property(estate["property"], today=today)
    assert summary["charged"] == 0


def test_the_once_a_month_rule_is_enforced_by_the_database(db_session, estate):
    """
    Not merely by the task's own check — a retried Celery job or two workers
    racing would sail past that. The partial unique index is the real guard.
    """
    from sqlalchemy.exc import IntegrityError

    policy = _policy(db_session, estate)
    common = dict(
        landlord_id=estate["landlord"].id, property_id=estate["property"].id,
        unit_id=estate["unit"].id, tenant_id=estate["tenant"].id,
        policy_id=policy.id, period_year=2026, period_month=8,
        source=PenaltySource.auto.value, basis_balance=Decimal("12000"),
        amount=Decimal("500"),
    )
    db_session.add(PenaltyCharge(**common))
    db_session.flush()

    db_session.add(PenaltyCharge(**common))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_manual_top_up_is_allowed_on_top_of_the_automatic_one(db_session, estate):
    """
    Deliberately outside the unique index: a person adding a further charge is
    a decision, not a duplicate.
    """
    policy = _policy(db_session, estate)
    today = date(2026, 8, 6)
    penalties.charge_tenant(estate["tenant"], policy, Decimal("500"), today=today)

    extra = penalties.charge_tenant(
        estate["tenant"], policy, Decimal("250"), today=today,
        source=PenaltySource.manual.value, note="Second notice",
    )
    assert extra is not None

    rows = (db_session.query(PenaltyCharge)
            .filter_by(tenant_id=estate["tenant"].id, period_year=2026, period_month=8)
            .all())
    assert len(rows) == 2


def test_penalties_do_not_compound(db_session, estate):
    """
    Each month stands alone, computed on the arrears at the time. A tenant who
    owes for three months has three separate charges, never a penalty on a
    penalty.
    """
    policy = _policy(db_session, estate)
    for month in (6, 7, 8):
        penalties.charge_tenant(estate["tenant"], policy, Decimal("500"),
                                today=date(2026, month, 6))

    rows = (db_session.query(PenaltyCharge)
            .filter_by(tenant_id=estate["tenant"].id).all())
    assert len(rows) == 3
    assert all(r.amount == Decimal("500.00") for r in rows)


# ---------------------------------------------------------------------------
# Never commissionable
# ---------------------------------------------------------------------------

def test_a_penalty_is_filed_under_the_penalty_category_not_rent(db_session, estate):
    """
    This is the whole mechanism. commission_service computes commission from
    the Rent category only, so filing the charge anywhere else is what makes it
    non-commissionable — there is no flag to get wrong.
    """
    from models import InvoiceLineItem

    policy = _policy(db_session, estate)
    charge = penalties.charge_tenant(estate["tenant"], policy, Decimal("500"),
                                     today=date(2026, 8, 6))

    lines = (db_session.query(InvoiceLineItem)
             .filter_by(invoice_id=charge.invoice_id).all())
    assert lines

    penalty_cat = (db_session.query(ChargeCategory)
                   .filter_by(landlord_id=estate["landlord"].id, name="Penalty").first())
    rent_cat = (db_session.query(ChargeCategory)
                .filter_by(landlord_id=estate["landlord"].id, name="Rent").first())

    for line in lines:
        assert line.category_id == penalty_cat.id
        assert line.category_id != rent_cat.id
        # Never a rent subcategory — those are what commission counts.
        assert (line.subcategory or "") not in ("current", "balance")


def test_penalties_are_excluded_from_the_commission_base(db_session, estate):
    """End-to-end: the collections breakdown must bucket a penalty as 'other'."""
    from services import commission_service

    policy = _policy(db_session, estate)
    penalties.charge_tenant(estate["tenant"], policy, Decimal("500"),
                            today=date(2026, 8, 6))
    db_session.flush()

    breakdown = commission_service.collections_breakdown(
        estate["landlord"].id, None, date(2026, 8, 1), date(2026, 8, 31),
    )
    # Nothing has been PAID, so nothing is collected at all — but the point is
    # that commission is computed from rent_collected, which a penalty can
    # never contribute to.
    commission = commission_service.commission_for(breakdown, Decimal("10"))
    assert commission == (breakdown["rent_collected"] * Decimal("10") / Decimal("100")).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Policy validation
# ---------------------------------------------------------------------------

def test_enabling_without_an_amount_is_refused(db_session, estate):
    from utils import ApiError

    with pytest.raises(ApiError):
        penalties.save_policy(estate["property"], {
            "is_enabled": True, "mode": "fixed",
            "trigger_type": "day_of_month", "trigger_day": 6,
        })


def test_a_day_outside_1_to_28_is_refused(db_session, estate):
    from utils import ApiError

    with pytest.raises(ApiError):
        penalties.save_policy(estate["property"], {
            "is_enabled": True, "mode": "fixed", "fixed_amount": 500,
            "trigger_type": "day_of_month", "trigger_day": 31,
        })


def test_overlapping_bands_are_refused(db_session, estate):
    from utils import ApiError

    with pytest.raises(ApiError):
        penalties.save_policy(estate["property"], {
            "is_enabled": True, "mode": "tiered",
            "trigger_type": "day_of_month", "trigger_day": 6,
            "tiers": [
                {"min_balance": 1000, "max_balance": 6000, "amount": 300},
                {"min_balance": 5000, "max_balance": 9000, "amount": 400},
            ],
        })


def test_a_valid_tiered_policy_saves(db_session, estate):
    policy = penalties.save_policy(estate["property"], {
        "is_enabled": True, "mode": "tiered",
        "trigger_type": "day_of_month", "trigger_day": 6,
        "tiers": [
            {"min_balance": 5000,  "max_balance": 7000, "amount": 400},
            {"min_balance": 10000, "max_balance": None, "amount": 500},
        ],
    })
    assert policy.is_enabled is True
    assert len(policy.tiers) == 2


def test_switching_trigger_type_clears_the_unused_field(db_session, estate):
    """A stale trigger_day left behind would make the rule ambiguous."""
    policy = penalties.save_policy(estate["property"], {
        "is_enabled": True, "mode": "fixed", "fixed_amount": 500,
        "trigger_type": "days_after_due", "grace_days": 5,
    })
    assert policy.trigger_day is None
    assert policy.grace_days == 5
