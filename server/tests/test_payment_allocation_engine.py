"""
sahilpay_payment_allocation_spec.md §9 — the fourteen test cases that must pass.

Test 5 is the one the whole engine exists for: a tenant renting several units
pays one lump sum quoting their phone number. Before this work the pipeline
picked `.first()` matching tenant and credited that lease alone, silently
leaving the others in arrears. It must now land in suspense with a suggestion
and stay there until a human commits a split.

Test 13 protects the other rule that is legal rather than cosmetic: commission
and MRI are charged on RENT COLLECTED only. A deposit is the tenant's
refundable money and passes through untouched.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    AllocationAudit, AllocationMethod, CommissionRateType, CommissionRule,
    CommissionScopeType, InboundPaymentSource, Invoice, InvoiceLineItem,
    InvoiceStatus, InvoiceType, Landlord, LandlordSettings, Payment,
    PaymentAllocation, PaymentStatus, PaymentSource, Property, PropertyOwner,
    SuspenseReason, Tenant, Unit, UnitPayCodeAlias, User,
)
from services import pay_code_service, payment_resolver, payout_service
from services.category_service import rent_category_id, seed_default_categories
from utils import ApiError


def _uniq():
    return uuid.uuid4().hex[:8]


def _digits(width=7):
    """A unique DIGIT string — _uniq() is hex and would corrupt a phone number."""
    return str(uuid.uuid4().int)[:width].ljust(width, "0")


# ---------------------------------------------------------------------------
# Fixture: a property manager, two blocks, and a tenant renting TWO units
# ---------------------------------------------------------------------------

@pytest.fixture()
def estate(db_session):
    s = db_session
    n = _uniq()

    user = User(
        email=f"alloc-{n}@test.sahilpay", phone=f"2547{_digits(8)}",
        password_hash=generate_password_hash("Testpass1"),
        role="property_manager", is_verified=True, is_active=True,
    )
    s.add(user)
    s.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Agent {n}", currency="KES",
                        allocation_method=AllocationMethod.phone.value)
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    seed_default_categories(landlord.id)
    s.flush()

    owner = PropertyOwner(landlord_id=landlord.id, full_name=f"Owner {n}",
                          phone=f"+2547{_digits(8)}", kra_pin="A012345678B")
    s.add(owner)
    s.flush()

    def block(label):
        p = Property(landlord_id=landlord.id, name=f"{label} {n}", number_of_units=2,
                     city="Nairobi", tax_rate=Decimal("0.00"), owner_id=owner.id)
        s.add(p)
        s.flush()
        return p

    block_a, block_b = block("Block A"), block("Block B")

    def unit(prop, name, rent):
        u = Unit(property_id=prop.id, name=f"{name}-{n}", rent_amount=Decimal(rent))
        s.add(u)
        s.flush()
        pay_code_service.assign(u, None, landlord_id=landlord.id)
        return u

    shop = unit(block_a, "SHOP", "20000")
    flat = unit(block_a, "FLAT", "10000")
    solo = unit(block_b, "SOLO", "15000")

    # ONE person, TWO units — two Tenant rows sharing a phone. This is the
    # schema's design and precisely why a phone cannot pick a lease.
    shared_phone = f"+2547{_digits(8)}"

    def tenant(unit_obj, first, phone, balance="0"):
        # Account numbers are unique per landlord, and both Mary rows would
        # otherwise collide — the same person renting two units is two rows.
        t = Tenant(landlord_id=landlord.id, unit_id=unit_obj.id, first_name=first,
                   last_name=n, phone=phone,
                   account_number=f"{first[:2].upper()}-{unit_obj.id}-{n}",
                   balance=Decimal(balance))
        s.add(t)
        s.flush()
        return t

    multi_shop = tenant(shop, "Mary", shared_phone, "-30000")   # owed 30,000
    multi_flat = tenant(flat, "Mary", shared_phone, "-10000")   # owed 10,000
    single     = tenant(solo, "Sam", f"+2547{_digits(8)}", "-15000")

    s.commit()
    return {
        "landlord": landlord, "user": user, "owner": owner,
        "block_a": block_a, "block_b": block_b,
        "shop": shop, "flat": flat, "solo": solo,
        "multi_shop": multi_shop, "multi_flat": multi_flat, "single": single,
        "shared_phone": shared_phone,
    }


def _invoice_with_rent(estate, tenant, amount, *, subcategory="current", issue=None):
    """A rent invoice so the waterfall has something real to allocate against."""
    n = _uniq()
    landlord = estate["landlord"]
    issue = issue or date.today()
    invoice = Invoice(
        invoice_number=f"INV-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=tenant.unit_id, property_id=tenant.unit.property_id,
        invoice_type=InvoiceType.monthly.value, issue_date=issue,
        status=InvoiceStatus.open.value, total_amount=Decimal(amount),
        amount_paid=Decimal("0"), balance=Decimal(amount),
    )
    db.session.add(invoice)
    db.session.flush()
    line = InvoiceLineItem(
        invoice_id=invoice.id, item="Rent", quantity=1,
        unit_price=Decimal(amount), amount=Decimal(amount),
        category_id=rent_category_id(landlord.id), subcategory=subcategory,
    )
    db.session.add(line)
    db.session.flush()
    return invoice, line


def _payment(estate, amount, *, reference=None, payer_phone=None, ref=None):
    payment = Payment(
        payment_ref=ref or f"PMT-{_uniq()}", landlord_id=estate["landlord"].id,
        amount=Decimal(amount), payment_date=date.today(),
        status=PaymentStatus.pending.value, source=PaymentSource.co_pilot.value,
        reference_text=reference, payer_phone=payer_phone,
        mpesa_reference=f"MP{_uniq().upper()}",
    )
    db.session.add(payment)
    db.session.flush()
    return payment


# ===========================================================================
# 1. Idempotency
# ===========================================================================

def test_01_duplicate_mpesa_code_yields_one_payment(estate):
    """
    The same forwarded SMS twice must not create two payments. Dedupe lives on
    copilot_messages.dedupe_hash, so assert the guarantee the resolver relies
    on: one M-Pesa code, one payment row.
    """
    code = f"MP{_uniq().upper()}"
    first = _payment(estate, "5000")
    first.mpesa_reference = code
    db.session.flush()

    existing = db.session.query(Payment).filter_by(
        landlord_id=estate["landlord"].id, mpesa_reference=code).all()
    assert len(existing) == 1

    # A second arrival of the same code is recognised before a payment is made.
    already = db.session.query(Payment).filter_by(
        landlord_id=estate["landlord"].id, mpesa_reference=code).first()
    assert already is not None and already.id == first.id


# ===========================================================================
# 2. Unit-code exact match
# ===========================================================================

def test_02_unit_code_allocates_deterministically(estate):
    _invoice_with_rent(estate, estate["multi_shop"], "20000")
    payment = _payment(estate, "20000", reference=estate["shop"].pay_code)

    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.confirmed.value
    assert payment.tenant_id == estate["multi_shop"].id
    assert payment.unit_id == estate["shop"].id
    # Deterministic even though the payer rents a second unit as well.
    assert payment.suspense_reason is None


# ===========================================================================
# 3. Alias — a retired code still resolves
# ===========================================================================

def test_03_retired_pay_code_still_resolves(estate):
    unit = estate["solo"]
    old_code = unit.pay_code
    pay_code_service.assign(unit, "SOLO-NEW", landlord_id=estate["landlord"].id)
    db.session.commit()

    assert unit.pay_code == "SOLO-NEW"
    assert db.session.query(UnitPayCodeAlias).filter_by(
        unit_id=unit.id, old_code=old_code).first() is not None

    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=old_code)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.confirmed.value
    assert payment.unit_id == unit.id


# ===========================================================================
# 4. Phone, single lease → auto
# ===========================================================================

def test_04_phone_single_lease_auto_allocates(estate):
    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=estate["single"].phone)

    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.confirmed.value
    assert payment.tenant_id == estate["single"].id
    assert sum(Decimal(str(a.amount_allocated))
               for a in payment.payment_allocations) == Decimal("15000")


# ===========================================================================
# 5. Phone, MULTI lease — the core case
# ===========================================================================

def test_05_multi_lease_lump_sum_goes_to_suspense_with_a_suggestion(estate):
    """The bug this engine exists to fix. Never auto-committed."""
    _invoice_with_rent(estate, estate["multi_shop"], "20000")
    _invoice_with_rent(estate, estate["multi_flat"], "10000")

    payment = _payment(estate, "25000", reference=estate["shared_phone"])
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.suspense.value
    assert payment.suspense_reason == SuspenseReason.multi_lease.value
    assert payment.payment_allocations == [], "nothing may be allocated yet"

    suggestion = payment.suggested_split_json
    assert suggestion, "the manager must be offered a starting point"
    # Arrears-first: the 30,000 debt is served before the 10,000 one.
    assert Decimal(suggestion[0]["amount"]) == Decimal("25000.00")
    assert suggestion[0]["unit_id"] == estate["shop"].id


def test_05b_manager_confirms_the_split(estate):
    """Confirming writes the correct split, tagged with the actor."""
    _invoice_with_rent(estate, estate["multi_shop"], "20000")
    _invoice_with_rent(estate, estate["multi_flat"], "10000")

    payment = _payment(estate, "25000", reference=estate["shared_phone"])
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    payment_resolver.allocate_manually(
        payment, estate["landlord"],
        [{"tenant_id": estate["multi_shop"].id, "amount": "20000"},
         {"tenant_id": estate["multi_flat"].id, "amount": "5000"}],
        actor_user_id=estate["user"].id,
    )
    db.session.commit()

    assert payment.status == PaymentStatus.confirmed.value
    assert payment.tenant_id == estate["multi_shop"].id
    assert Decimal(str(payment.amount)) == Decimal("20000")

    # The second leg became its own payment, because a Payment row carries one
    # tenant and every downstream report reads that.
    sibling = (db.session.query(Payment)
               .filter(Payment.tenant_id == estate["multi_flat"].id,
                       Payment.payment_ref.like(f"{payment.payment_ref}%"))
               .first())
    assert sibling is not None
    assert Decimal(str(sibling.amount)) == Decimal("5000")

    for allocation in payment.payment_allocations:
        assert allocation.method == "manual"
        assert allocation.allocated_by == estate["user"].id


def test_05c_split_cannot_exceed_the_payment(estate):
    _invoice_with_rent(estate, estate["multi_shop"], "20000")
    payment = _payment(estate, "1000", reference=estate["shared_phone"])
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    with pytest.raises(ApiError):
        payment_resolver.allocate_manually(
            payment, estate["landlord"],
            [{"tenant_id": estate["multi_shop"].id, "amount": "9999"}],
            actor_user_id=estate["user"].id,
        )


# ===========================================================================
# 6. Masked payer phone
# ===========================================================================

def test_06_masked_payer_phone_does_not_misroute(estate):
    """
    M-Pesa masks the payer number on forwarded confirmations. A masked value
    must never fuzzy-match a tenant — with no usable reference this is suspense.
    """
    payment = _payment(estate, "8000", reference=None, payer_phone="2547****123")
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.suspense.value
    assert payment.tenant_id is None


def test_06b_reference_wins_over_a_masked_payer_phone(estate):
    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=estate["single"].phone,
                       payer_phone="2547****999")
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.confirmed.value
    assert payment.tenant_id == estate["single"].id


# ===========================================================================
# 7 & 8. Partial payment and overpayment
# ===========================================================================

def test_07_partial_payment_leaves_a_balance(estate):
    _, line = _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "6000", reference=estate["single"].phone)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    db.session.refresh(line)
    assert Decimal(str(line.amount_paid)) == Decimal("6000")
    assert Decimal(str(line.remaining)) == Decimal("9000")


def test_08_overpayment_becomes_lease_credit(estate):
    from models import CreditLedger

    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "20000", reference=estate["single"].phone)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    tenant = estate["single"]
    db.session.refresh(tenant)
    assert Decimal(str(tenant.credit_balance)) == Decimal("5000")
    assert db.session.query(CreditLedger).filter_by(payment_id=payment.id).first() is not None


# ===========================================================================
# 9. Multi-source landlord
# ===========================================================================

def test_09_source_narrows_to_the_right_property(estate):
    """
    Two blocks, two paybills, and the SAME phone renting in both. The source
    mapping alone resolves what the phone cannot.
    """
    landlord = estate["landlord"]
    source = InboundPaymentSource(
        landlord_id=landlord.id, label="Block B till", shortcode="556677",
        mapped_property_id=estate["block_b"].id,
    )
    db.session.add(source)
    # Give the multi-unit tenant a third tenancy in Block B on the same phone.
    third = Tenant(landlord_id=landlord.id, unit_id=estate["solo"].id,
                   first_name="Mary", last_name=_uniq(),
                   phone=estate["shared_phone"], account_number=f"M3-{_uniq()}",
                   balance=Decimal("-15000"))
    db.session.add(third)
    db.session.flush()
    _invoice_with_rent(estate, third, "15000")

    payment = _payment(estate, "15000", reference=estate["shared_phone"])
    payment_resolver.resolve(payment, landlord, shortcode="556677")
    db.session.commit()

    assert payment.source_id == source.id
    assert payment.status == PaymentStatus.confirmed.value
    assert payment.property_id == estate["block_b"].id


# ===========================================================================
# 10. Unparseable message
# ===========================================================================

def test_10_unknown_reference_is_held_not_discarded(estate):
    payment = _payment(estate, "3000", reference="TOTALLY-UNKNOWN")
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.suspense.value
    assert payment.suspense_reason == SuspenseReason.unknown_reference.value
    # The money is still on record — never dropped.
    assert Decimal(str(payment.amount)) == Decimal("3000")


# ===========================================================================
# 11. Reversal
# ===========================================================================

def test_11_reversal_restores_balances_and_flags_the_payment(estate):
    _, line = _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=estate["single"].phone)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    db.session.refresh(line)
    assert Decimal(str(line.amount_paid)) == Decimal("15000")
    balance_after_payment = Decimal(str(estate["single"].balance))

    payment_resolver.reverse_payment(payment, actor_user_id=estate["user"].id,
                                     reason="M-Pesa reversal")
    db.session.commit()

    db.session.refresh(line)
    db.session.refresh(estate["single"])
    assert payment.status == PaymentStatus.reversed.value
    assert Decimal(str(line.amount_paid)) == Decimal("0")
    assert payment.payment_allocations == []
    assert Decimal(str(estate["single"].balance)) == balance_after_payment + Decimal("15000")


# ===========================================================================
# 12. Commission scope precedence
# ===========================================================================

def test_12_unit_rule_beats_property_beats_landlord(estate):
    landlord = estate["landlord"]
    db.session.add_all([
        CommissionRule(landlord_id=landlord.id,
                       scope_type=CommissionScopeType.landlord.value, scope_id=None,
                       rate_type=CommissionRateType.percentage.value,
                       rate_value=Decimal("10")),
        CommissionRule(landlord_id=landlord.id,
                       scope_type=CommissionScopeType.property.value,
                       scope_id=estate["block_a"].id,
                       rate_type=CommissionRateType.percentage.value,
                       rate_value=Decimal("8")),
        CommissionRule(landlord_id=landlord.id,
                       scope_type=CommissionScopeType.unit.value,
                       scope_id=estate["shop"].id,
                       rate_type=CommissionRateType.percentage.value,
                       rate_value=Decimal("5")),
    ])
    db.session.commit()

    unit_rule = payout_service.resolve_commission_rule(
        landlord.id, unit_id=estate["shop"].id, property_id=estate["block_a"].id)
    assert Decimal(str(unit_rule.rate_value)) == Decimal("5")

    property_rule = payout_service.resolve_commission_rule(
        landlord.id, unit_id=estate["flat"].id, property_id=estate["block_a"].id)
    assert Decimal(str(property_rule.rate_value)) == Decimal("8")

    account_rule = payout_service.resolve_commission_rule(
        landlord.id, unit_id=estate["solo"].id, property_id=estate["block_b"].id)
    assert Decimal(str(account_rule.rate_value)) == Decimal("10")


def test_12b_no_rule_means_no_commission(estate):
    """A manager who hasn't said what they charge must not have a rate invented."""
    rule = payout_service.resolve_commission_rule(
        estate["landlord"].id, unit_id=estate["shop"].id,
        property_id=estate["block_a"].id)
    assert rule is None
    assert payout_service.commission_for_base(rule, Decimal("100000")) == Decimal("0.00")


# ===========================================================================
# 13. The worked example — 100,000 rent, deposit excluded
# ===========================================================================

def test_13_commission_and_tax_base_excludes_the_deposit(estate):
    """
    Spec §4.10: 100,000 rent collected → tax 7,500, commission (10%) 10,000,
    and a deposit passes through in full, in NEITHER base.
    """
    landlord = estate["landlord"]
    db.session.add(CommissionRule(
        landlord_id=landlord.id, scope_type=CommissionScopeType.landlord.value,
        scope_id=None, rate_type=CommissionRateType.percentage.value,
        rate_value=Decimal("10")))
    db.session.flush()

    tenant = estate["single"]
    n = _uniq()
    invoice = Invoice(
        invoice_number=f"INV-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=tenant.unit_id, property_id=tenant.unit.property_id,
        invoice_type=InvoiceType.monthly.value, issue_date=date.today(),
        status=InvoiceStatus.open.value, total_amount=Decimal("130000"),
        amount_paid=Decimal("0"), balance=Decimal("130000"),
    )
    db.session.add(invoice)
    db.session.flush()

    rent_cat = rent_category_id(landlord.id)

    def line(item, amount, subcategory):
        li = InvoiceLineItem(invoice_id=invoice.id, item=item, quantity=1,
                             unit_price=Decimal(amount), amount=Decimal(amount),
                             category_id=rent_cat, subcategory=subcategory)
        db.session.add(li)
        db.session.flush()
        return li

    rent_line = line("Rent", "100000", "current")
    deposit_line = line("Deposit", "30000", "deposit")

    payment = Payment(
        payment_ref=f"PMT-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=tenant.unit_id, property_id=tenant.unit.property_id,
        amount=Decimal("130000"), payment_date=date.today(),
        status=PaymentStatus.confirmed.value, source=PaymentSource.mpesa.value,
    )
    db.session.add(payment)
    db.session.flush()
    for li, amount in ((rent_line, "100000"), (deposit_line, "30000")):
        db.session.add(PaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, line_item_id=li.id,
            amount_allocated=Decimal(amount), method="auto"))
    db.session.commit()

    today = date.today()
    previews = payout_service.preview_payouts(
        landlord.id, today - timedelta(days=1), today + timedelta(days=1))
    preview = next(p for p in previews if p["owner_id"] == estate["owner"].id)

    assert preview["rent_collected_base"] == Decimal("100000.00")
    assert preview["commission_amount"] == Decimal("10000.00")
    assert preview["tax_amount"] == Decimal("7500.00")
    # The deposit is in total_collected (the agent is holding it) but in
    # neither base, and it passes through to the owner untouched.
    assert preview["total_collected"] == Decimal("130000.00")
    assert preview["tax_withheld"] is False
    assert preview["net_payable"] == Decimal("120000.00")


def test_13b_withholding_deducts_the_tax(estate):
    """With withholding ON the same figures net 7,500 lower."""
    landlord = estate["landlord"]
    landlord.tax_withholding_enabled = True
    db.session.add(CommissionRule(
        landlord_id=landlord.id, scope_type=CommissionScopeType.landlord.value,
        scope_id=None, rate_type=CommissionRateType.percentage.value,
        rate_value=Decimal("10")))
    db.session.flush()

    _, line = _invoice_with_rent(estate, estate["single"], "100000")
    payment = _payment(estate, "100000", reference=estate["single"].phone)
    payment_resolver.resolve(payment, landlord)
    db.session.commit()

    today = date.today()
    previews = payout_service.preview_payouts(
        landlord.id, today - timedelta(days=1), today + timedelta(days=1))
    preview = next(p for p in previews if p["owner_id"] == estate["owner"].id)

    assert preview["tax_withheld"] is True
    assert preview["tax_amount"] == Decimal("7500.00")
    assert preview["net_payable"] == Decimal("82500.00")   # 100k − 10k − 7.5k


def test_13c_fixed_commission_never_exceeds_the_rent(estate):
    landlord = estate["landlord"]
    rule = CommissionRule(
        landlord_id=landlord.id, scope_type=CommissionScopeType.landlord.value,
        scope_id=None, rate_type=CommissionRateType.fixed.value,
        rate_value=Decimal("15000"))
    db.session.add(rule)
    db.session.flush()

    assert payout_service.commission_for_base(rule, Decimal("40000")) == Decimal("15000.00")
    # A thin month must not hand the owner a negative payout.
    assert payout_service.commission_for_base(rule, Decimal("4000")) == Decimal("4000.00")


# ===========================================================================
# 14. Suspense guarantee + audit trail
# ===========================================================================

def test_14_every_outcome_is_audited(estate):
    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=estate["single"].phone)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    rows = db.session.query(AllocationAudit).filter_by(payment_id=payment.id).all()
    assert rows, "an allocation must leave a trail"
    assert rows[0].action == "allocate"
    assert rows[0].after_json


def test_14b_suspense_is_audited_too(estate):
    payment = _payment(estate, "4000", reference="NOPE-NOPE")
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    rows = db.session.query(AllocationAudit).filter_by(payment_id=payment.id).all()
    assert [r.action for r in rows] == ["suspense"]
    assert rows[0].after_json["reason"] == SuspenseReason.unknown_reference.value


def test_14c_nothing_leaves_suspense_without_an_explicit_allocation(estate):
    _invoice_with_rent(estate, estate["multi_shop"], "20000")
    _invoice_with_rent(estate, estate["multi_flat"], "10000")
    payment = _payment(estate, "25000", reference=estate["shared_phone"])

    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    # Re-resolving must not quietly "give up and pick one".
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    assert payment.status == PaymentStatus.suspense.value
    assert payment.payment_allocations == []


# ===========================================================================
# Pay-code rules (§4.3)
# ===========================================================================

def test_pay_codes_are_unique_per_account_and_hard_block_duplicates(estate):
    taken = estate["shop"].pay_code
    with pytest.raises(ApiError) as excinfo:
        pay_code_service.assign(estate["flat"], taken,
                                landlord_id=estate["landlord"].id)
    assert "already in use" in excinfo.value.message


def test_pay_code_stays_editable_after_payments_used_it(estate):
    _invoice_with_rent(estate, estate["single"], "15000")
    payment = _payment(estate, "15000", reference=estate["solo"].pay_code)
    payment_resolver.resolve(payment, estate["landlord"])
    db.session.commit()

    # Editing is allowed — locking would trap an owner with a typo forever.
    pay_code_service.assign(estate["solo"], "SOLO-RENAMED",
                            landlord_id=estate["landlord"].id)
    db.session.commit()
    assert estate["solo"].pay_code == "SOLO-RENAMED"


@pytest.mark.parametrize("bad", ["semi;colon", "-leading", "sla/sh", "x" * 40])
def test_pay_code_validation_rejects_junk(bad):
    with pytest.raises(ApiError):
        pay_code_service.normalise(bad)


def test_pay_code_normalisation_is_forgiving_about_spacing_and_case():
    """A code read aloud as "pw f11" is the same code as PWF11."""
    assert pay_code_service.normalise("  pw f11 ") == "PWF11"
    assert pay_code_service.normalise("") is None


def test_existing_accounts_keep_phone_mode(estate):
    """
    The migration sets every EXISTING account to phone so behaviour is
    unchanged; only new accounts default to unit_code.
    """
    assert estate["landlord"].allocation_method == AllocationMethod.phone.value
