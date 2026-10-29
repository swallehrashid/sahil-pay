"""
THE INVOICE RULE — no money is recorded that no invoice accounts for.

A payment answers a charge. You invoice first, then allocate a payment to that
invoice; allocating to something that does not exist yet is a guess. The app used
to accept any amount and park the excess as "tenant credit", which is how the
dashboard showed more collected than was ever invoiced and why receipts came out
carrying negative lines.

Enforced invariant, for every confirmed payment that is not a credit
re-application:

    sum(allocations) == payment.amount   =>   recorded <= invoiced

Advances are not an exception: paying January–December in January records only
January, because only January is invoiced. The money is not lost — it is
recorded month by month as each month is invoiced.

These tests cover the entry points money can arrive through, and the ways the
old code let the rule be broken.
"""

import itertools
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant,
    Invoice, InvoiceLineItem, InvoiceStatus, InvoiceType,
    Payment, PaymentAllocation, PaymentStatus, PaymentSource,
    CreditLedger,
)
from services.category_service import rent_category_id, seed_default_categories
from services.allocation_service import auto_allocate, apply_allocations
from services.payment_guard import (
    ExceedsInvoiced, outstanding_invoiced, assert_within_invoiced,
)

_c = itertools.count()


def _uniq():
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def world(db_session):
    s = db_session
    n = _uniq()
    user = User(email=f"ir-{n}@test.sp", phone=f"2547{next(_c):08d}",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True)
    s.add(user)
    s.flush()
    landlord = Landlord(user_id=user.id, company_name=f"IR Co {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    seed_default_categories(landlord.id)
    s.flush()
    prop = Property(landlord_id=landlord.id, name=f"Block {n}", number_of_units=1,
                    city="Nairobi", tax_rate=Decimal("0.00"))
    s.add(prop)
    s.flush()
    unit = Unit(property_id=prop.id, name=f"U-{n}", rent_amount=Decimal("10000"))
    s.add(unit)
    s.flush()
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, first_name="Tala",
                    last_name=n, phone=f"+2547{next(_c):08d}",
                    account_number=f"IR-{n}", balance=Decimal("0"))
    s.add(tenant)
    s.flush()
    s.commit()
    return {"user": user, "landlord": landlord, "property": prop,
            "unit": unit, "tenant": tenant}


def invoice_for(world, amount, *, issue=None):
    """Raise a real rent invoice so there is something to allocate against."""
    n = _uniq()
    landlord, tenant = world["landlord"], world["tenant"]
    inv = Invoice(invoice_number=f"INV-{n}", landlord_id=landlord.id, tenant_id=tenant.id,
                  unit_id=tenant.unit_id, property_id=world["property"].id,
                  invoice_type=InvoiceType.monthly.value, issue_date=issue or date.today(),
                  status=InvoiceStatus.open.value, total_amount=Decimal(amount),
                  amount_paid=Decimal("0"), balance=Decimal(amount))
    db.session.add(inv)
    db.session.flush()
    line = InvoiceLineItem(invoice_id=inv.id, item="Rent", quantity=1,
                           unit_price=Decimal(amount), amount=Decimal(amount),
                           category_id=rent_category_id(landlord.id), subcategory="current")
    db.session.add(line)
    db.session.flush()
    return inv, line


def lh(world):
    tok = create_access_token(identity=str(world["user"].id),
                              additional_claims={"role": "landlord",
                                                 "landlord_id": world["landlord"].id})
    return {"Authorization": f"Bearer {tok}"}


def make_payment(world, amount, *, source=PaymentSource.manual.value,
                 status=PaymentStatus.confirmed.value):
    p = Payment(payment_ref=f"PMT-{_uniq()}", landlord_id=world["landlord"].id,
                tenant_id=world["tenant"].id, unit_id=world["tenant"].unit_id,
                property_id=world["property"].id, amount=Decimal(str(amount)),
                payment_date=date.today(), status=status, source=source)
    db.session.add(p)
    db.session.flush()
    return p


# ===========================================================================
# The measure itself
# ===========================================================================

def test_outstanding_invoiced_is_zero_with_no_invoices(world):
    assert outstanding_invoiced(world["tenant"]) == Decimal("0.00")


def test_outstanding_invoiced_counts_only_what_is_still_owed(world):
    invoice_for(world, "10000")
    assert outstanding_invoiced(world["tenant"]) == Decimal("10000.00")
    invoice_for(world, "2500")
    assert outstanding_invoiced(world["tenant"]) == Decimal("12500.00")


def test_void_and_deleted_invoices_do_not_count(world):
    inv, _ = invoice_for(world, "10000")
    inv.status = InvoiceStatus.void.value
    db.session.flush()
    assert outstanding_invoiced(world["tenant"]) == Decimal("0.00")
    inv.status = InvoiceStatus.open.value
    inv.is_deleted = True
    db.session.flush()
    assert outstanding_invoiced(world["tenant"]) == Decimal("0.00")


# ===========================================================================
# The chokepoint: apply_allocations may never leave money unaccounted for
# ===========================================================================

def test_exact_payment_allocates_fully_and_creates_no_credit(world):
    invoice_for(world, "10000")
    p = make_payment(world, "10000")
    rows = auto_allocate(world["tenant"], p.amount, world["landlord"])
    allocated = apply_allocations(p, world["tenant"], rows, world["landlord"].id)
    assert allocated == Decimal("10000.00")
    assert world["tenant"].credit_balance == Decimal("0.00")
    assert CreditLedger.query.filter_by(tenant_id=world["tenant"].id).count() == 0


def test_partial_payment_is_fine(world):
    invoice_for(world, "10000")
    p = make_payment(world, "4000")
    rows = auto_allocate(world["tenant"], p.amount, world["landlord"])
    assert apply_allocations(p, world["tenant"], rows, world["landlord"].id) == Decimal("4000.00")
    assert outstanding_invoiced(world["tenant"]) == Decimal("6000.00")


def test_overpayment_is_refused_instead_of_becoming_credit(world):
    """The exact production defect: 12,000 paid against a 10,000 invoice."""
    invoice_for(world, "10000")
    p = make_payment(world, "12000")
    rows = auto_allocate(world["tenant"], p.amount, world["landlord"])
    with pytest.raises(ExceedsInvoiced):
        apply_allocations(p, world["tenant"], rows, world["landlord"].id)


def test_payment_with_nothing_invoiced_is_refused(world):
    p = make_payment(world, "10000")
    rows = auto_allocate(world["tenant"], p.amount, world["landlord"])
    assert rows == []
    with pytest.raises(ExceedsInvoiced):
        apply_allocations(p, world["tenant"], rows, world["landlord"].id)


def test_deliberate_under_allocation_is_refused(world):
    """Allocating only part of a payment would leave the rest sitting nowhere."""
    _, line = invoice_for(world, "10000")
    p = make_payment(world, "10000")
    rows = [{"line_item_id": line.id, "invoice_id": line.invoice_id,
             "amount_allocated": Decimal("6000")}]
    with pytest.raises(ExceedsInvoiced):
        apply_allocations(p, world["tenant"], rows, world["landlord"].id)


def test_credit_reapplication_is_still_allowed(world):
    """Held credit moving onto a new invoice is money already recorded."""
    invoice_for(world, "10000")
    p = make_payment(world, "12000", source=PaymentSource.credit.value)
    rows = auto_allocate(world["tenant"], Decimal("10000"), world["landlord"])
    # Exempt: no raise, and the un-allocated part is not re-recorded as cash.
    assert apply_allocations(p, world["tenant"], rows, world["landlord"].id) == Decimal("10000.00")


# ===========================================================================
# Advance payments: recorded month by month, as each month is invoiced
# ===========================================================================

def test_paying_a_year_ahead_records_only_what_is_invoiced(world):
    """
    Rent is 10,000/mo and the tenant hands over 120,000 in January. Only January
    is invoiced, so only 10,000 may be recorded. The rest is money in the
    landlord's M-Pesa account, recorded as each month is invoiced.
    """
    invoice_for(world, "10000")
    with pytest.raises(ExceedsInvoiced) as err:
        assert_within_invoiced(world["tenant"], Decimal("120000"))
    assert "10,000.00" in str(err.value)

    # January is recorded.
    p = make_payment(world, "10000")
    rows = auto_allocate(world["tenant"], p.amount, world["landlord"])
    apply_allocations(p, world["tenant"], rows, world["landlord"].id)

    # February is invoiced -> February's share may now be recorded.
    invoice_for(world, "10000", issue=date.today() + timedelta(days=31))
    assert outstanding_invoiced(world["tenant"]) == Decimal("10000.00")
    p2 = make_payment(world, "10000")
    rows2 = auto_allocate(world["tenant"], p2.amount, world["landlord"])
    assert apply_allocations(p2, world["tenant"], rows2, world["landlord"].id) == Decimal("10000.00")
    assert world["tenant"].credit_balance == Decimal("0.00")


# ===========================================================================
# The HTTP surface
# ===========================================================================

def test_api_refuses_an_over_invoiced_payment_with_guidance(app, client, world):
    invoice_for(world, "10000")
    db.session.commit()
    with app.app_context():
        r = client.post("/api/payments/", headers=lh(world), json={
            "tenant_id": world["tenant"].id, "amount": 15000,
            "payment_date": str(date.today()), "source": "manual",
        })
        assert r.status_code == 422, r.status_code
        body = r.get_json()
        assert body["code"] == "exceeds_invoiced"
        assert "invoice" in body["message"].lower() or "invoice" in body["error"].lower()
        # Nothing was written.
        assert Payment.query.filter_by(tenant_id=world["tenant"].id).count() == 0


def test_api_accepts_a_payment_the_invoices_cover(app, client, world):
    invoice_for(world, "10000")
    db.session.commit()
    with app.app_context():
        r = client.post("/api/payments/", headers=lh(world), json={
            "tenant_id": world["tenant"].id, "amount": 10000,
            "payment_date": str(date.today()), "source": "manual",
        })
        assert r.status_code == 201, r.get_json()
        pay_id = r.get_json()["id"]
        allocated = sum(
            Decimal(str(a.amount_allocated))
            for a in PaymentAllocation.query.filter_by(payment_id=pay_id).all()
        )
        assert allocated == Decimal("10000.00")
        assert world["tenant"].credit_balance == Decimal("0.00")


def test_api_refuses_a_manual_split_that_leaves_money_over(app, client, world):
    _, line = invoice_for(world, "10000")
    db.session.commit()
    with app.app_context():
        r = client.post("/api/payments/", headers=lh(world), json={
            "tenant_id": world["tenant"].id, "amount": 10000,
            "payment_date": str(date.today()), "source": "manual",
            "allocation_mode": "manual",
            "allocations": [{"invoice_id": line.invoice_id, "line_item_id": line.id,
                             "amount_allocated": 6000}],
        })
        assert r.status_code == 422
        assert "not allocated" in r.get_json()["error"]


def test_confirming_a_pending_payment_beyond_invoiced_is_refused(app, client, world):
    """
    Money can sit pending (it arrived, it is visible, it counts nowhere). It is
    only recorded once an invoice covers it.
    """
    invoice_for(world, "4000")
    pending = make_payment(world, "10000", source=PaymentSource.mpesa.value,
                           status=PaymentStatus.pending.value)
    db.session.commit()
    with app.app_context():
        r = client.post(f"/api/payments/{pending.id}/confirm", headers=lh(world),
                        json={"mode": "auto"})
        assert r.status_code == 422
        assert r.get_json()["code"] == "exceeds_invoiced"
        assert db.session.get(Payment, pending.id).status == PaymentStatus.pending.value

        # Invoice the rest, and the very same payment confirms cleanly.
        invoice_for(world, "6000")
        db.session.commit()
        ok = client.post(f"/api/payments/{pending.id}/confirm", headers=lh(world),
                         json={"mode": "auto"})
        assert ok.status_code == 200, ok.get_json()
        assert db.session.get(Payment, pending.id).status == PaymentStatus.confirmed.value
        assert world["tenant"].credit_balance == Decimal("0.00")


# ===========================================================================
# The dashboard invariant the owner described
# ===========================================================================

def test_recorded_can_never_exceed_invoiced(app, client, world):
    """
    Drive a sequence of attempts and assert the headline invariant: the sum of
    confirmed, cash payments never exceeds the sum of invoiced line items.
    """
    invoice_for(world, "10000")
    invoice_for(world, "5000")
    db.session.commit()
    with app.app_context():
        for amount in (3000, 9000, 50000, 3000, 100, 20000):
            client.post("/api/payments/", headers=lh(world), json={
                "tenant_id": world["tenant"].id, "amount": amount,
                "payment_date": str(date.today()), "source": "manual",
            })
        invoiced = sum(
            Decimal(str(li.amount))
            for li in InvoiceLineItem.query.join(Invoice)
            .filter(Invoice.tenant_id == world["tenant"].id,
                    Invoice.is_deleted.is_(False)).all()
        )
        recorded = sum(
            Decimal(str(p.amount))
            for p in Payment.query.filter_by(tenant_id=world["tenant"].id,
                                             status=PaymentStatus.confirmed.value,
                                             is_deleted=False).all()
            if p.source != PaymentSource.credit.value
        )
        assert recorded <= invoiced, f"recorded {recorded} exceeded invoiced {invoiced}"
        assert world["tenant"].credit_balance == Decimal("0.00")


def test_editing_a_payment_cannot_confirm_it(app, client, world):
    """
    Confirming is what records money, and recording means allocating. The
    generic edit endpoint cannot allocate, so it must not be a back door that
    leaves a payment confirmed with nothing allocated.
    """
    invoice_for(world, "10000")
    pending = make_payment(world, "10000", source=PaymentSource.mpesa.value,
                           status=PaymentStatus.pending.value)
    db.session.commit()
    with app.app_context():
        r = client.put(f"/api/payments/{pending.id}", headers=lh(world),
                       json={"status": "confirmed"})
        assert r.status_code == 422
        assert db.session.get(Payment, pending.id).status == PaymentStatus.pending.value
        # Editing anything else is still fine.
        ok = client.put(f"/api/payments/{pending.id}", headers=lh(world),
                        json={"notes": "proof attached"})
        assert ok.status_code == 200


def test_no_confirmed_payment_is_left_unallocated(app, client, world):
    """
    The structural invariant: every confirmed, cash payment is fully covered by
    PaymentAllocation rows. Walk a mixed sequence and assert it holds.
    """
    invoice_for(world, "10000")
    invoice_for(world, "7000")
    db.session.commit()
    with app.app_context():
        for amount in (5000, 12000, 2000, 40000, 10000):
            client.post("/api/payments/", headers=lh(world), json={
                "tenant_id": world["tenant"].id, "amount": amount,
                "payment_date": str(date.today()), "source": "manual",
            })
        confirmed = Payment.query.filter_by(
            tenant_id=world["tenant"].id, status=PaymentStatus.confirmed.value,
            is_deleted=False,
        ).all()
        assert confirmed, "expected some payments to succeed"
        for p in confirmed:
            if p.source == PaymentSource.credit.value:
                continue
            allocated = sum(
                Decimal(str(a.amount_allocated))
                for a in PaymentAllocation.query.filter_by(payment_id=p.id).all()
            )
            assert allocated == Decimal(str(p.amount)), (
                f"payment {p.payment_ref} recorded {p.amount} but allocated {allocated}"
            )
