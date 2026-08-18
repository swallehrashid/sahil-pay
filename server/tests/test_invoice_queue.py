"""
The invoice queue — charges that are ready to bill before an invoice exists.

The scenario this is built for, end to end: a caretaker reads the water meter on
28 March. The bill goes out on 1 April. On the 28th there is nothing to attach
the reading to — March's invoice is closing and April's does not exist. Queue it,
and April's monthly run picks it up.

What has to hold:

  ONCE          the monthly run is explicitly re-runnable, so a queued charge
                must be consumed exactly once or a re-run double-bills.
  THE UNIT      the charge follows the meter, not the person. A tenant leaving
                on the 30th must not be billed for it, and the arriving tenant
                must not silently inherit it unnoticed.
  THE LEDGER    consuming a charge moves the invoice total AND the tenant
                balance, in the right direction. Getting the sign wrong files a
                debtor as being in credit.
  NOT EMPTY     a tenant whose ONLY charge this month is queued water still gets
                an invoice — otherwise the reading silently never goes out.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    ChargeCategory, Invoice, InvoiceStatus, Landlord, LandlordSettings,
    Property, QueuedCharge, Tenant, Unit, User,
)
from services import invoice_queue_service as queue


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def estate(app, db_session):
    s = db_session
    n = _uniq()

    owner = User(email=f"iq-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Queue {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))

    rent = ChargeCategory(landlord_id=landlord.id, name="Rent", kind="invoice",
                          is_metered=False, auto_bill_monthly=True)
    water = ChargeCategory(landlord_id=landlord.id, name="Water", kind="utility",
                           is_metered=True)
    s.add_all([rent, water])
    s.flush()

    prop = Property(landlord_id=landlord.id, name=f"Block {n}", city="Nairobi")
    s.add(prop)
    s.flush()
    unit = Unit(landlord_id=landlord.id, property_id=prop.id, name=f"A{n[:3]}",
                rent_amount=Decimal("25000"))
    s.add(unit)
    s.flush()
    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id,
                    first_name="Amina", last_name=n[:4],
                    phone=f"2547{n[:7]}", account_number=f"Q{n}",
                    balance=Decimal("0"))
    s.add(tenant)
    s.flush()

    return {"landlord": landlord, "property": prop, "unit": unit,
            "tenant": tenant, "rent": rent, "water": water, "n": n}


def _queue_water(estate, amount="400"):
    return queue.queue_charge(
        estate["landlord"].id, estate["unit"],
        item="Water", amount=Decimal(amount),
        category_id=estate["water"].id, subcategory="current",
        description="2026-03 — 100 to 102",
    )


def _open_invoice(estate, total="25000"):
    invoice = Invoice(
        landlord_id=estate["landlord"].id, tenant_id=estate["tenant"].id,
        unit_id=estate["unit"].id, property_id=estate["property"].id,
        invoice_number=f"INV-{estate['n']}", invoice_type="rent", title="Rent",
        issue_date=date.today(), due_date=date.today(),
        total_amount=Decimal(total), amount_paid=Decimal("0"),
        balance=Decimal(total), status=InvoiceStatus.open.value,
    )
    db.session.add(invoice)
    db.session.flush()
    return invoice


# ---------------------------------------------------------------------------
# Queueing
# ---------------------------------------------------------------------------

def test_a_charge_can_wait_without_an_invoice(estate):
    charge = _queue_water(estate)

    assert charge.status == QueuedCharge.STATUS_QUEUED
    assert charge.unit_id == estate["unit"].id
    assert queue.pending_total_for_unit(estate["unit"].id) == Decimal("400")


def test_queueing_bills_nobody_yet(estate):
    """Nothing is charged at queue time — that is the entire point."""
    before = estate["tenant"].balance
    _queue_water(estate)

    assert estate["tenant"].balance == before
    assert Invoice.query.filter_by(tenant_id=estate["tenant"].id).count() == 0


def test_the_occupant_at_queue_time_is_recorded(estate):
    """
    So a change of tenant between reading and billing is visible at the point it
    is billed, rather than discovered by the new tenant on their first invoice.
    """
    charge = _queue_water(estate)

    assert charge.occupant_at_queue_id == estate["tenant"].id


def test_a_zero_charge_is_not_queued(estate):
    assert queue.queue_charge(estate["landlord"].id, estate["unit"],
                              item="Water", amount=0) is None


# ---------------------------------------------------------------------------
# Consuming
# ---------------------------------------------------------------------------

def test_consuming_adds_a_line_and_moves_the_ledger(estate):
    charge = _queue_water(estate)
    invoice = _open_invoice(estate)
    tenant = estate["tenant"]
    before_total, before_balance = invoice.total_amount, tenant.balance

    added = queue.consume_into_invoice(invoice, [charge], tenant=tenant)

    assert added == Decimal("400")
    assert invoice.total_amount == before_total + Decimal("400")
    assert invoice.balance == invoice.total_amount - invoice.amount_paid
    # New debt makes the balance MORE negative.
    assert tenant.balance == before_balance - Decimal("400")
    assert any(li.item == "Water" for li in invoice.line_items)


def test_a_consumed_charge_records_which_invoice_took_it(estate):
    charge = _queue_water(estate)
    invoice = _open_invoice(estate)

    queue.consume_into_invoice(invoice, [charge], tenant=estate["tenant"])

    assert charge.status == QueuedCharge.STATUS_CONSUMED
    assert charge.consumed_by_invoice_id == invoice.id
    assert charge.consumed_at is not None


def test_a_charge_is_consumed_only_once(estate):
    """
    The monthly run is designed to be re-runnable, so this is what stands
    between a re-run and a double bill.
    """
    charge = _queue_water(estate)
    invoice = _open_invoice(estate)
    tenant = estate["tenant"]

    first = queue.consume_into_invoice(invoice, [charge], tenant=tenant)
    balance_after_first = tenant.balance
    second = queue.consume_into_invoice(invoice, [charge], tenant=tenant)

    assert first == Decimal("400")
    assert second == Decimal("0.00")
    assert tenant.balance == balance_after_first


def test_consuming_clears_it_from_the_queue(estate):
    charge = _queue_water(estate)
    invoice = _open_invoice(estate)

    queue.consume_into_invoice(invoice, [charge], tenant=estate["tenant"])

    assert queue.pending_for_unit(estate["unit"].id) == []


def test_cancelling_leaves_a_record_rather_than_deleting(estate):
    """"Why was this never billed?" is asked months later."""
    charge = _queue_water(estate)

    queue.cancel(charge)

    assert charge.status == QueuedCharge.STATUS_CANCELLED
    assert db.session.get(QueuedCharge, charge.id) is not None
    assert queue.pending_for_unit(estate["unit"].id) == []


def test_a_cancelled_charge_is_never_billed(estate):
    charge = _queue_water(estate)
    queue.cancel(charge)
    invoice = _open_invoice(estate)

    added = queue.consume_into_invoice(invoice, [charge], tenant=estate["tenant"])

    assert added == Decimal("0.00")


# ---------------------------------------------------------------------------
# The monthly run — the scenario the queue exists for
# ---------------------------------------------------------------------------

def test_the_monthly_run_picks_up_a_queued_reading(app, estate):
    """
    28 March: caretaker reads the meter and queues it.
    1 April:  the monthly run bills rent AND the water, on one invoice.
    """
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant

    _queue_water(estate)
    april = date(2026, 4, 1)

    outcome = _run_monthly_billing_for_tenant(
        estate["landlord"], estate["tenant"], april, april, None)
    db.session.flush()

    assert outcome == "created"
    invoice = Invoice.query.filter_by(tenant_id=estate["tenant"].id).one()
    items = {li.item for li in invoice.line_items}
    assert "Water" in items
    assert "Rent" in items
    # 25,000 rent + 400 water, on ONE bill rather than two.
    assert invoice.total_amount == Decimal("25400.00")


def test_re_running_the_monthly_billing_does_not_double_bill_the_queue(app, estate):
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant

    _queue_water(estate)
    april = date(2026, 4, 1)

    _run_monthly_billing_for_tenant(estate["landlord"], estate["tenant"], april, april, None)
    db.session.flush()
    second = _run_monthly_billing_for_tenant(
        estate["landlord"], estate["tenant"], april, april, None)

    # The run's own idempotency guard fires first, and the queue is empty anyway.
    assert second == "skipped"
    invoice = Invoice.query.filter_by(tenant_id=estate["tenant"].id).one()
    water_lines = [li for li in invoice.line_items if li.item == "Water"]
    assert len(water_lines) == 1


def test_a_queued_charge_alone_is_enough_to_raise_an_invoice(app, estate, db_session):
    """
    A tenant whose only charge this month is water still has to be billed for
    the water — otherwise the caretaker's reading silently never goes out.
    """
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant

    # No auto-billed rent this month.
    estate["rent"].auto_bill_monthly = False
    db_session.flush()

    _queue_water(estate)
    april = date(2026, 4, 1)

    outcome = _run_monthly_billing_for_tenant(
        estate["landlord"], estate["tenant"], april, april, None)
    db.session.flush()

    assert outcome == "created"
    invoice = Invoice.query.filter_by(tenant_id=estate["tenant"].id).one()
    assert invoice.total_amount == Decimal("400.00")


def test_nothing_queued_and_nothing_to_bill_still_means_empty(app, estate, db_session):
    """The queue must not turn every tenant into an invoice."""
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant

    estate["rent"].auto_bill_monthly = False
    db_session.flush()

    outcome = _run_monthly_billing_for_tenant(
        estate["landlord"], estate["tenant"], date(2026, 4, 1), date(2026, 4, 1), None)

    assert outcome == "empty"


# ---------------------------------------------------------------------------
# Reporting on the queue
# ---------------------------------------------------------------------------

def test_the_summary_groups_by_unit(estate):
    _queue_water(estate, "400")
    _queue_water(estate, "150")

    summary = queue.summary_for_landlord(estate["landlord"].id)

    assert summary["count"] == 2
    assert summary["total"] == 550.0
    assert summary["units"][0]["unit_id"] == estate["unit"].id
    assert summary["units"][0]["count"] == 2


def test_consumed_charges_drop_out_of_the_summary(estate):
    charge = _queue_water(estate)
    invoice = _open_invoice(estate)
    queue.consume_into_invoice(invoice, [charge], tenant=estate["tenant"])

    assert queue.summary_for_landlord(estate["landlord"].id)["count"] == 0
