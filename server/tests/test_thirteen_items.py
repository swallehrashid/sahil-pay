"""
The September-2026 thirteen-item release — the rules that must not regress.

  1  next of kin saved with the tenant
  2  a receipt is sent only on the channels the sender ticked
  3  the "A4 third" receipt is an A4 PORTRAIT page (so it prints as previewed)
  4  a payment is allocated once, to one tenant — by any route
  5  no receipt for a payment that is not confirmed and allocated
  6  the Payments Report reconciles and tracks every allocation by month
  7  search matches every word, whatever the order, spaces included
  8  letterhead sizes are the landlord's to set
  9  a third-party SMS account is verified live and bills its own account
 10  a property's own units and tenants
 11  monthly invoices generated one property at a time
 12  move-in on the 28th: next month's rent billed once, labelled with its month
 13  every receipt line names the month it is for (except the lease fee)
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest

from extensions import db
from models import (
    BalanceRollover, ChargeCategory, Invoice, InvoiceLineItem, Payment, PaymentSource,
    PaymentStatus, Tenant,
)
from services.category_service import seed_default_categories
from tests.test_access_control import (
    _auth, _make_landlord, _make_property, _make_tenant, _make_unit, _token, _uniq,
)


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def world(app, db_session):
    landlord, owner = _make_landlord(db_session, "t13")
    seed_default_categories(landlord.id)
    prop = _make_property(db_session, landlord, "Kingongo")
    unit = _make_unit(db_session, prop, "MN4")
    unit.rent_amount = Decimal("6000")
    tenant = _make_tenant(db_session, landlord, unit)
    tenant.first_name, tenant.last_name = "Alex", f"Kirui{_uniq()[:3]}"
    unit.is_occupied = True
    db_session.flush()
    cats = {c.name: c for c in ChargeCategory.query.filter_by(landlord_id=landlord.id).all()}
    return {"landlord": landlord, "owner": owner, "prop": prop, "unit": unit, "tenant": tenant,
            "cats": cats, "h": _auth(_token(app, owner, landlord_id=landlord.id))}


def _invoice(w, issue, lines, itype="monthly"):
    inv = Invoice(invoice_number=f"INV-{_uniq()}", landlord_id=w["landlord"].id,
                  tenant_id=w["tenant"].id, unit_id=w["unit"].id, property_id=w["prop"].id,
                  invoice_type=itype, issue_date=issue, status="open",
                  total_amount=sum(Decimal(str(l[1])) for l in lines), amount_paid=0,
                  balance=sum(Decimal(str(l[1])) for l in lines))
    db.session.add(inv)
    db.session.flush()
    out = []
    for name, amount, sub, *rest in lines:
        cat = w["cats"].get(name.split(" ")[0])
        li = InvoiceLineItem(invoice_id=inv.id, item=name, quantity=1, unit_price=amount,
                             amount=amount, category_id=cat.id if cat else None,
                             subcategory=sub, amount_paid=0, status="open",
                             period_month=rest[0] if rest else None)
        db.session.add(li)
        out.append(li)
    db.session.flush()
    return inv, out


def _pay(w, amount, when, ref=None, status="confirmed", allocate=True):
    from services.allocation_service import apply_allocations, auto_allocate
    p = Payment(payment_ref=f"PMT-{_uniq()}", landlord_id=w["landlord"].id,
                tenant_id=w["tenant"].id, unit_id=w["unit"].id, property_id=w["prop"].id,
                amount=Decimal(str(amount)), payment_date=when, status=status,
                source=PaymentSource.manual.value, mpesa_reference=ref)
    db.session.add(p)
    db.session.flush()
    if allocate and status == "confirmed":
        rows = auto_allocate(w["tenant"], p.amount, w["landlord"], ref_date=when)
        apply_allocations(p, w["tenant"], rows, w["landlord"].id)
    return p


# ---------------------------------------------------------------- 1 next of kin

def test_next_of_kin_is_saved_and_validated(client, world):
    w = world
    unit2 = _make_unit(db.session, w["prop"], "NK")
    r = client.post("/api/tenants/", headers=w["h"], json={
        "unit_id": unit2.id, "first_name": "Jonah", "last_name": "Mwendwa", "phone": "0712345678",
        "next_of_kin_name": "Mary Mwendwa", "next_of_kin_relationship": "Sister",
        "next_of_kin_phone": "0722 000 111"})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["next_of_kin_name"] == "Mary Mwendwa"
    assert body["next_of_kin_relationship"] == "Sister"
    assert body["next_of_kin_phone"] == "254722000111"

    unit3 = _make_unit(db.session, w["prop"], "NK2")
    bad = client.post("/api/tenants/", headers=w["h"], json={
        "unit_id": unit3.id, "first_name": "A", "last_name": "B", "phone": "0712345679",
        "next_of_kin_phone": "12"})
    assert bad.status_code == 400 and "Next of kin" in bad.get_json()["error"]


# ------------------------------------------------- 2 + 5 receipt channels & gating

def test_receipt_send_requires_a_channel_and_an_allocated_payment(client, world):
    w = world
    _invoice(w, date(2026, 9, 1), [("Rent", 6000, "current")])
    paid = _pay(w, 6000, date(2026, 9, 3))
    r = client.post(f"/api/payments/{paid.id}/receipt/send", headers=w["h"], json={})
    assert r.status_code == 400 and "Choose at least one" in r.get_json()["error"]

    pending = _pay(w, 500, date(2026, 9, 4), status="pending")
    assert client.post(f"/api/payments/{pending.id}/receipt/send", headers=w["h"],
                       json={"channels": ["in_app"]}).status_code == 409
    assert client.get(f"/api/payments/{pending.id}/receipt/download", headers=w["h"]).status_code == 409

    unallocated = _pay(w, 500, date(2026, 9, 4), allocate=False)
    assert client.get(f"/api/payments/{unallocated.id}/receipt/download",
                      headers=w["h"]).status_code == 409

    listing = client.get("/api/payments/?per_page=50", headers=w["h"]).get_json()["payments"]
    flags = {p["id"]: p["receipt_available"] for p in listing}
    assert flags[paid.id] is True and flags[pending.id] is False and flags[unallocated.id] is False


# ------------------------------------------------ 3 the third prints as previewed

def test_every_a4_paper_is_an_a4_page(world):
    from pypdf import PdfReader
    import io
    from services.receipt_service import render_receipt_pdf
    w = world
    _invoice(w, date(2026, 9, 1), [("Rent", 6000, "current")])
    p = _pay(w, 6000, date(2026, 9, 3))
    for paper, (wmm, hmm) in {"a4_third_band": (210, 297), "a4_third_slip": (210, 297),
                              "a4": (210, 297), "a4_third_landscape": (297, 210),
                              "a4_third_portrait": (210, 297)}.items():
        page = PdfReader(io.BytesIO(render_receipt_pdf(p, {"paper": paper}))).pages
        assert len(page) == 1, paper
        box = page[0].mediabox
        assert round(float(box.width) / 72 * 25.4) == wmm, paper
        assert round(float(box.height) / 72 * 25.4) == hmm, paper


# ------------------------------------------------------- 4 allocated once only

def test_a_payment_is_allocated_once_by_any_route(client, world):
    w = world
    _invoice(w, date(2026, 9, 1), [("Rent", 6000, "current")])
    p = _pay(w, 6000, date(2026, 9, 3), ref="UIPRH7P2U5", status="pending", allocate=False)

    first = client.post(f"/api/payments/{p.id}/confirm", headers=w["h"], json={"mode": "auto"})
    assert first.status_code == 200, first.get_json()
    assert "reviewed and allocated" in first.get_json()["message"]

    again = client.post(f"/api/payments/{p.id}/confirm", headers=w["h"], json={"mode": "auto"})
    assert again.status_code == 409
    split = client.post(f"/api/payments/{p.id}/allocate", headers=w["h"],
                        json={"splits": [{"tenant_id": w["tenant"].id, "amount": 6000}]})
    assert split.status_code == 409

    # The same M-Pesa code cannot be recorded again on the Payments page…
    dup = client.post("/api/payments/", headers=w["h"], json={
        "tenant_id": w["tenant"].id, "amount": 6000, "mpesa_reference": "uiprh7p2u5"})
    assert dup.status_code == 409 and "already allocated" in dup.get_json()["error"]

    # …nor confirmed from a second pending copy (e.g. Co-pilot read the SMS too).
    copy = _pay(w, 6000, date(2026, 9, 3), ref="UIPRH7P2U5", status="pending", allocate=False)
    assert client.post(f"/api/payments/{copy.id}/confirm", headers=w["h"],
                       json={"mode": "auto"}).status_code == 409

    total = sum(a.amount_allocated for a in Payment.query.get(p.id).payment_allocations)
    assert total == Decimal("6000")


# ------------------------------------------------------ 6 the report adds up

def test_payments_report_reconciles_and_tracks_months(world):
    from services.payment_report_service import build_payments_report
    w = world
    _invoice(w, date(2026, 8, 1), [("Rent", 6000, "current")])
    _invoice(w, date(2026, 9, 1), [("Rent", 6000, "current"), ("Water", 900, "current")])
    _pay(w, 7000, date(2026, 9, 10))
    _pay(w, 9000, date(2026, 9, 20))          # clears everything, 3,100 advance

    data = build_payments_report(w["landlord"].id, date_from=date(2026, 9, 1),
                                 date_to=date(2026, 9, 30))
    recon = data["reconciliation"]
    assert recon["cash_received"] == 16000
    assert recon["allocated_to_charges"] == 12900
    assert recon["advance_to_credit"] == 3100
    assert recon["difference"] == 0
    months = {(r["month"], r["category_name"]): r for r in data["by_month"]}
    assert months[("2026-08-01", "Rent")]["collected"] == 6000
    assert months[("2026-09-01", "Rent")]["collected"] == 6000
    assert months[("2026-09-01", "Water")]["collected"] == 900
    assert round(sum(r["amount"] for r in data["ledger"]), 2) == 12900
    assert {r["month_label"] for r in data["ledger"]} >= {"August 2026", "September 2026"}


# -------------------------------------------------------- 7 search with spaces

def test_search_matches_every_word_in_any_order(client, world):
    w = world
    for q in (f"Alex {w['tenant'].last_name}", f"{w['tenant'].last_name} alex", "alex  "):
        rows = client.get("/api/tenants/", headers=w["h"], query_string={"search": q}).get_json()["tenants"]
        assert [t["id"] for t in rows] == [w["tenant"].id], q
    none = client.get("/api/tenants/", headers=w["h"],
                      query_string={"search": "Alex Nobody"}).get_json()["tenants"]
    assert none == []


# ------------------------------------------------------ 8 letterhead sizes

def test_letterhead_sizes_are_kept_and_clamped():
    from services import receipt_layout as rl
    lay = rl.normalise({"paper": "a4_third_band",
                        "letterhead": {"logo": 2, "title": 9, "contact": 0.1, "title_align": "center"}})
    assert lay["letterhead"] == {"logo": 2.0, "title": 2.5, "contact": 0.5, "title_align": "center"}
    css = rl.page_css(lay)
    assert "height: 44.0mm" in css          # 22 mm logo at 200 %


# ------------------------------------------------------- 9 third-party SMS

def test_third_party_sms_account_is_verified_and_bills_itself(app, world):
    from services import sms_provider_service as sp
    from services.communication_service import dispatch_message
    w = world
    ls = w["landlord"].landlord_settings
    ls.sms_sender_id = "RAWAESTATE"
    sp.store_key(ls, "third-party-key-1234")
    assert ls.sms_api_key.startswith("enc:") and "1234" not in ls.sms_api_key
    assert sp.own_key(ls) == "third-party-key-1234"

    with mock.patch("services.sms_service._post", return_value={"error": "Invalid API key"}):
        ok, msg, _ = sp.verify(ls)
    assert not ok and "Invalid API key" in msg
    with mock.patch("services.sms_service._post", return_value={"success": True, "sms_balance": 17}):
        ok, msg, bal = sp.verify(ls)
    assert ok and bal == 17

    ls.sms_connected = True
    w["landlord"].sms_balance = 0          # their Sahil Pay balance is NOT what pays
    db.session.flush()
    app.config["COMMS_SIMULATION_MODE"], was = False, app.config.get("COMMS_SIMULATION_MODE")
    try:
        with mock.patch("services.sms_service.send_sms", return_value="msg-1") as send:
            log = dispatch_message(landlord_id=w["landlord"].id, tenant=w["tenant"],
                                   channel="sms", content="Hello")
    finally:
        app.config["COMMS_SIMULATION_MODE"] = was
    assert log.status == "delivered"
    assert send.call_args.kwargs["api_key"] == "third-party-key-1234"
    assert send.call_args.kwargs["sender_id"] == "RAWAESTATE"
    assert w["landlord"].sms_balance == 0 and log.sms_charge == 0


# --------------------------------------------- 10 + 11 property pages & invoicing

def test_property_page_and_per_property_invoicing(client, world):
    w = world
    detail = client.get(f"/api/properties/{w['prop'].id}", headers=w["h"]).get_json()
    assert detail["summary"]["tenants"] == 1 and detail["summary"]["units"] == 1

    other = _make_property(db.session, w["landlord"], "Other")
    ou = _make_unit(db.session, other, "O1")
    _make_tenant(db.session, w["landlord"], ou)
    db.session.flush()

    month = date.today().strftime("%Y-%m")
    overview = client.get("/api/invoice-queue/by-property", headers=w["h"],
                          query_string={"month": month}).get_json()["data"]
    assert {p["property_id"] for p in overview["properties"]} >= {w["prop"].id, other.id}

    prev = client.get(f"/api/invoice-queue/by-property/{w['prop'].id}", headers=w["h"],
                      query_string={"month": month}).get_json()["data"]
    assert prev["summary"]["to_invoice"] == 1 and prev["summary"]["rent"] == 6000

    # Generating is the ordinary monthly run scoped to one property. (Called
    # directly: under eager Celery the task runs in its own session and cannot
    # see this test's uncommitted rows.)
    from tasks.invoice_tasks import run_monthly_billing_task
    tally = run_monthly_billing_task.run(w["landlord"].id, None, [w["prop"].id], None, None)
    assert tally["created"] == 1
    assert Invoice.query.filter_by(tenant_id=w["tenant"].id, invoice_type="monthly").count() == 1
    other_tenant = Tenant.query.filter_by(unit_id=ou.id).one()
    assert Invoice.query.filter_by(tenant_id=other_tenant.id).count() == 0   # untouched
    again = client.get(f"/api/invoice-queue/by-property/{w['prop'].id}", headers=w["h"],
                       query_string={"month": month}).get_json()["data"]
    assert again["summary"]["to_invoice"] == 0


# ------------------------------------------ 12 the 28th-of-the-month move-in

def _move_in_lines(w, rent, deposit, lease, penalty_deposit=0):
    c = w["cats"]
    lines = [{"category_id": c["Rent"].id, "subcategory": "current", "amount": rent},
             {"category_id": c["Rent"].id, "subcategory": "deposit", "amount": deposit},
             {"category_id": c["Lease Agreement"].id, "subcategory": "current", "amount": lease}]
    if penalty_deposit:
        lines.append({"category_id": c["Penalty"].id, "subcategory": "deposit", "amount": penalty_deposit})
    return lines


def test_moving_in_from_the_20th_bills_next_month_once(world):
    """26 September, box ticked: every line is FOR October, billed and paid on the 26th."""
    from services.move_in_service import bill_move_in
    from services.receipt_service import build_receipt
    from services.payment_report_service import build_payments_report
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant
    w = world
    t = w["tenant"]
    t.move_in_date = date(2026, 9, 26)
    db.session.flush()

    inv = bill_move_in(t, {"bill_next_month": True, "bill_month": "2026-10",
                           "lines": _move_in_lines(w, 6000, 6000, 500, penalty_deposit=1000)})
    assert inv.invoice_type == "move_in" and inv.issue_date == date(2026, 9, 26)
    assert {li.period_month for li in inv.line_items} == {date(2026, 10, 1)}
    assert {li.item for li in inv.line_items} == {"Rent", "Rent Deposit", "Lease Agreement", "Penalty Deposit"}
    assert t.lease_start_date == date(2026, 10, 1)

    p = _pay(w, 13500, date(2026, 9, 26))
    r = build_receipt(p)
    labels = {x["label"] for x in r["paid_items"]}
    assert labels == {"Rent — October 2026", "Rent Deposit — October 2026",
                      "Penalty Deposit — October 2026", "Lease Agreement"}   # lease: no month
    assert r["payment_date"] == "2026-09-26" and r["period_label"] == "October 2026"

    # Reports file all of it — the lease fee too — under October.
    rep = build_payments_report(w["landlord"].id, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    months = {(m["month"], m["category_name"]): m for m in rep["by_month"]}
    assert months[("2026-10-01", "Rent")]["collected"] == 6000
    assert months[("2026-10-01", "Lease Agreement")]["collected"] == 500
    assert rep["reconciliation"]["difference"] == 0
    # "Invoiced" by month is rent only — the deposit billed with it is not rent.
    both = build_payments_report(w["landlord"].id, date_from=date(2026, 9, 1), date_to=date(2026, 10, 31))
    oct_rent = [m for m in both["by_month"] if m["month"] == "2026-10-01" and m["category_name"] == "Rent"][0]
    assert oct_rent["invoiced"] == 6000

    run = lambda m: _run_monthly_billing_for_tenant(w["landlord"], t, m, m, None)   # noqa: E731
    assert run(date(2026, 9, 1)) == "empty"        # no September rent
    assert run(date(2026, 10, 1)) == "empty"       # October already billed
    assert run(date(2026, 11, 1)) == "created"     # November as normal


def test_moving_in_before_the_20th_bills_the_part_month(world):
    """15 September, box unticked: 'Rent — September' at the part-month amount; October in full."""
    from services.move_in_service import bill_move_in
    from services.receipt_service import build_receipt
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant
    w = world
    t = w["tenant"]
    t.move_in_date = date(2026, 9, 15)
    db.session.flush()

    inv = bill_move_in(t, {"bill_next_month": False, "lines": _move_in_lines(w, 3000, 6000, 500)})
    assert {li.period_month for li in inv.line_items} == {date(2026, 9, 1)}
    assert t.lease_start_date == date(2026, 9, 15)

    p = _pay(w, 9500, date(2026, 9, 15))
    labels = {x["label"]: x["amount"] for x in build_receipt(p)["paid_items"]}
    assert labels["Rent — September 2026"] == 3000.0

    run = lambda m: _run_monthly_billing_for_tenant(w["landlord"], t, m, m, None)   # noqa: E731
    # A September run after the 15th must not add the full rent on top of the part month.
    assert run(date(2026, 9, 1)) == "empty"
    assert run(date(2026, 10, 1)) == "created"
    oct_rent = [li for li in InvoiceLineItem.query.join(Invoice).filter(
        Invoice.tenant_id == t.id, InvoiceLineItem.period_month == date(2026, 10, 1)).all()]
    assert [(li.item, li.amount) for li in oct_rent] == [("Rent", Decimal("6000.00"))]


def test_next_month_billing_must_be_after_the_move_in_month(world):
    from services.move_in_service import bill_move_in
    from utils import ApiError
    w = world
    w["tenant"].move_in_date = date(2026, 9, 26)
    with pytest.raises(ApiError):
        bill_move_in(w["tenant"], {"bill_next_month": True, "bill_month": "2026-09",
                                   "lines": _move_in_lines(w, 6000, 0, 0)})


def test_a_part_month_on_an_ordinary_invoice_also_blocks_double_rent(world):
    """Billed from Invoices → Add invoice instead of the tenant form: same protection."""
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant
    w = world
    _invoice(w, date(2026, 9, 15), [("Rent", 3000, "current")], itype="custom")
    assert _run_monthly_billing_for_tenant(w["landlord"], w["tenant"], date(2026, 9, 1),
                                           date(2026, 9, 30), None) == "empty"


# ----------------------------------------------- 13 every line names its month

def test_receipt_splits_a_carried_balance_by_month_and_is_point_in_time(world):
    from services.receipt_service import build_receipt
    w = world
    rent = w["cats"]["Rent"]
    _, (jul,) = _invoice(w, date(2026, 7, 1), [("Rent", 6000, "current")])
    _, (aug,) = _invoice(w, date(2026, 8, 1), [("Rent", 6000, "current")])
    jul.status = aug.status = "rolled"
    _, (bf, sep) = _invoice(w, date(2026, 9, 1), [("Rent Balance b/f", 12000, "balance"),
                                                   ("Rent", 6000, "current")])
    db.session.add_all([
        BalanceRollover(landlord_id=w["landlord"].id, tenant_id=w["tenant"].id, category_id=rent.id,
                        source_line_item_id=jul.id, target_line_item_id=bf.id,
                        origin_month=date(2026, 7, 1), amount=6000),
        BalanceRollover(landlord_id=w["landlord"].id, tenant_id=w["tenant"].id, category_id=rent.id,
                        source_line_item_id=aug.id, target_line_item_id=bf.id,
                        origin_month=date(2026, 8, 1), amount=6000),
    ])
    db.session.flush()

    first = _pay(w, 8000, date(2026, 9, 5))
    r1 = build_receipt(first)
    assert [(i["label"], i["amount"]) for i in r1["paid_items"]] == \
        [("Rent — July 2026", 6000.0), ("Rent — August 2026", 2000.0)]
    owed = {i["label"]: i["amount"] for i in r1["outstanding_items"]}
    assert owed == {"Rent — August 2026": 4000.0, "Rent — September 2026": 6000.0}
    assert r1["balance_remaining"] == 10000.0

    second = _pay(w, 10000, date(2026, 9, 25))
    r2 = build_receipt(second)
    assert [(i["label"], i["amount"]) for i in r2["paid_items"]] == \
        [("Rent — August 2026", 4000.0), ("Rent — September 2026", 6000.0)]
    # Re-issuing the FIRST receipt after the second payment changes nothing.
    again = build_receipt(Payment.query.get(first.id))
    assert again["balance_remaining"] == 10000.0
    assert again["paid_items"] == r1["paid_items"]
