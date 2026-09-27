"""
Caretaker submits utilities → secretary approves → the 1st-of-month invoice
carries rent + approved utilities + any balance brought forward, as ONE invoice.
"""

from datetime import date
from decimal import Decimal

import pytest

from models import (
    ChargeCategory, Invoice, InvoiceLineItem, InvoiceType, Notification, Property,
    QueuedCharge, UtilityReading,
)
from services.category_service import seed_default_categories
from tasks.invoice_tasks import run_monthly_billing_all, run_monthly_billing_task
from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_team_member, _make_tenant, _make_unit, _token,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def estate(app, db_session):
    landlord, owner = _make_landlord(db_session, "qr")
    seed_default_categories(landlord.id)
    water = ChargeCategory.query.filter_by(landlord_id=landlord.id, name="Water").one()
    water.default_rate = Decimal("100")
    prop = _make_property(db_session, landlord, "Qr")
    units = [_make_unit(db_session, prop, f"Q{i}") for i in range(3)]
    tenants = [_make_tenant(db_session, landlord, u) for u in units]
    caretaker, ct_user = _make_team_member(db_session, landlord, property_ids=[prop.id],
                                           modules=["utilities"])
    secretary, sec_user = _make_team_member(db_session, landlord, property_ids=[prop.id])
    secretary.property_access_all = True
    db_session.flush()
    return {
        "landlord": landlord, "prop": prop, "units": units, "tenants": tenants, "water": water,
        "owner": owner,
        "caretaker_h": _auth(_token(app, ct_user, landlord_id=landlord.id, team_member_id=caretaker.id)),
        "secretary_h": _auth(_token(app, sec_user, landlord_id=landlord.id, team_member_id=secretary.id)),
        "owner_h": _auth(_token(app, owner, landlord_id=landlord.id)),
    }


def _record_readings(db_session, e, month="2026-09"):
    for i, unit in enumerate(e["units"]):
        db_session.add(UtilityReading(
            landlord_id=e["landlord"].id, property_id=e["prop"].id, unit_id=unit.id,
            utility_item="Water", category_id=e["water"].id, subcategory="current",
            previous_reading=Decimal("10"), current_reading=Decimal(str(12 + i)),
            consumption=Decimal(str(2 + i)), reading_month=month,
        ))
    db_session.flush()


def test_caretaker_submission_waits_for_review_and_cannot_approve_itself(client, e_ready):
    e, db_session = e_ready
    r = client.post("/api/utilities/queue", headers=e["caretaker_h"],
                    json={"property_id": e["prop"].id, "reading_month": "2026-09"})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["status"] == "pending" and r.get_json()["queued"] == 3

    charges = QueuedCharge.query.filter_by(landlord_id=e["landlord"].id).all()
    assert {c.status for c in charges} == {"pending"}
    assert Notification.query.filter_by(recipient_user_id=e["owner"].id, category="queue_review").count() == 1

    # A caretaker cannot approve — that is the point of the review step.
    assert client.post("/api/invoice-queue/review", headers=e["caretaker_h"],
                       json={"action": "approve", "all": True}).status_code == 403

    # Submitting again does not double-queue the same readings.
    again = client.post("/api/utilities/queue", headers=e["caretaker_h"],
                        json={"property_id": e["prop"].id, "reading_month": "2026-09"})
    assert again.get_json()["queued"] == 0


@pytest.fixture()
def e_ready(estate, db_session):
    _record_readings(db_session, estate)
    return estate, db_session


def test_pending_charges_are_never_invoiced(client, e_ready):
    e, db_session = e_ready
    client.post("/api/utilities/queue", headers=e["caretaker_h"],
                json={"property_id": e["prop"].id, "reading_month": "2026-09"})
    run_monthly_billing_task.run(e["landlord"].id, issue_date="2026-10-01",
                             include_rent=True, include_queued=True)
    lines = (InvoiceLineItem.query.join(Invoice)
             .filter(Invoice.landlord_id == e["landlord"].id).all())
    assert lines and all(li.item == "Rent" for li in lines)


def test_secretary_approves_and_first_of_month_invoice_combines_everything(client, e_ready):
    e, db_session = e_ready
    tenant = e["tenants"][0]

    # September: rent invoiced, only partly paid → arrears to carry forward.
    run_monthly_billing_task.run(e["landlord"].id, issue_date="2026-09-01", include_rent=True, include_queued=False)
    sept = Invoice.query.filter_by(tenant_id=tenant.id, invoice_type=InvoiceType.monthly.value).one()
    assert float(sept.total_amount) == 10000

    client.post("/api/utilities/queue", headers=e["caretaker_h"],
                json={"property_id": e["prop"].id, "reading_month": "2026-09"})
    pending = client.get("/api/invoice-queue/?status=pending", headers=e["secretary_h"]).get_json()["data"]
    assert pending["review_count"] == 3 and len(pending["charges"]) == 3
    assert pending["charges"][0]["property_name"] and pending["charges"][0]["submitted_by"]

    # Reject one, approve the rest.
    reject_id = pending["charges"][2]["id"]
    assert client.post("/api/invoice-queue/review", headers=e["secretary_h"],
                       json={"action": "reject", "charge_ids": [reject_id]}).status_code == 200
    ok = client.post("/api/invoice-queue/review", headers=e["secretary_h"],
                     json={"action": "approve", "all": True})
    assert ok.get_json()["data"]["changed"] == 2

    # October 1st, both switches on.
    run_monthly_billing_task.run(e["landlord"].id, issue_date="2026-10-01", include_rent=True, include_queued=True)
    octo = (Invoice.query.filter_by(tenant_id=tenant.id, invoice_type=InvoiceType.monthly.value)
            .filter(Invoice.issue_date >= date(2026, 10, 1)).one())
    items = sorted(li.item for li in octo.line_items)
    assert "Rent" in items and "Rent Balance b/f" in items
    assert any("Water" in i for i in items)
    water_line = next(li for li in octo.line_items if "Water" in li.item)
    assert float(water_line.amount) == 200           # 2 units × KES 100
    assert float(octo.total_amount) == 10000 + 10000 + 200

    rejected = db_session.get(QueuedCharge, reject_id)
    assert rejected.status == "rejected"
    reading = db_session.get(UtilityReading, water_line.utility_reading_id)
    assert reading.invoice_id == octo.id


def test_rent_off_queued_on_bills_only_units_with_approved_charges(client, e_ready):
    e, db_session = e_ready
    first = e["units"][0]
    reading = UtilityReading.query.filter_by(unit_id=first.id).one()
    client.post("/api/utilities/queue", headers=e["secretary_h"], json={"reading_ids": [reading.id]})
    # The secretary can bill, so it went straight to approved.
    assert QueuedCharge.query.filter_by(unit_id=first.id).one().status == "queued"

    tally = run_monthly_billing_task.run(e["landlord"].id, issue_date="2026-10-01",
                                     include_rent=False, include_queued=True)
    assert tally["created"] == 1
    inv = Invoice.query.filter_by(unit_id=first.id).one()
    assert [li.item for li in inv.line_items] == ["Water"]


@pytest.fixture()
def inline_tasks(monkeypatch):
    """Run the billing task inside the test's own session instead of a fresh one."""
    import types

    from tasks import invoice_tasks

    def delay(*args, **kwargs):
        return types.SimpleNamespace(id="inline", result=invoice_tasks.run_monthly_billing_task.run(*args, **kwargs))

    monkeypatch.setattr(invoice_tasks.run_monthly_billing_task, "delay", delay)


def test_approved_charges_join_an_invoice_already_raised_this_month(client, e_ready, inline_tasks):
    e, db_session = e_ready
    run_monthly_billing_task.run(e["landlord"].id, issue_date="2026-10-01", include_rent=True, include_queued=True)
    client.post("/api/utilities/queue", headers=e["owner_h"],
                json={"property_id": e["prop"].id, "reading_month": "2026-09"})
    r = client.post("/api/invoice-queue/run-monthly", headers=e["secretary_h"],
                    json={"include_rent": True, "include_queued": True, "issue_date": "2026-10-05"})
    assert r.status_code == 202, r.get_json()
    assert r.get_json()["data"]["result"]["updated"] == 3
    assert Invoice.query.filter_by(landlord_id=e["landlord"].id).count() == 3


def test_first_of_month_run_only_bills_accounts_that_switched_it_on(client, e_ready):
    e, db_session = e_ready
    aut = e["landlord"].automation_settings
    aut.auto_generate_recurring_invoices = False
    aut.auto_invoice_queued_charges = False
    db_session.flush()
    run_monthly_billing_all.run(issue_date="2026-10-01")
    assert Invoice.query.filter_by(landlord_id=e["landlord"].id).count() == 0

    aut.auto_generate_recurring_invoices = True
    db_session.flush()
    run_monthly_billing_all.run(issue_date="2026-10-01")
    assert Invoice.query.filter_by(landlord_id=e["landlord"].id).count() == 3
