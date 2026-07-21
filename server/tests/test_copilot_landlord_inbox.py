"""
Regression suite for COPILOT_LANDLORD_INBOX_SPEC.md.

Covers:
  §2   body-scoped retention (redaction of messages no template claims,
       the copilot_retain_unmatched opt-out, and dedupe-before-redaction
       ordering).
  §3   the new landlord-session /api/copilot/messages* endpoints (scoping,
       filters, summary counts, auth).
  §9   the two-message template-robustness regression for §1.5's editor fix
       (a template built the CORRECT way — no literal date/time/balance —
       must match two different real SMS bodies of the same shape).

Fixture style follows test_copilot_service.py (service-layer factories) plus
test_daraja_webhooks.py (HTTP client + JWT auth header) for the endpoint tests.
"""

import itertools
import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask import g
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant,
    SmsParserTemplate, CopilotDevice, CopilotDeviceStatus, CopilotMessage,
    CopilotParseStatus, CopilotMatchStatus, PaymentStatus, PaymentSource,
)
from services import copilot_service as svc

_counter = itertools.count()


def _uniq() -> str:
    """6-digit unique-enough suffix, unique per process AND across reruns
    (unlike a plain in-process counter, which collides with a previous run's
    leftover rows since these factories commit — see test_daraja_webhooks.py,
    same convention)."""
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Factories (mirrors test_copilot_service.py; commits so the HTTP request's
# own db.session — same app context, per conftest.py — can see the rows)
# ---------------------------------------------------------------------------

def make_landlord(session, *, copilot_enabled=True, auto_allocate=False,
                   admin_locked=False, retain_unmatched=False):
    n = _uniq()
    user = User(
        email=f"inbox-landlord{n}@test.sahilpay", phone=f"2547{n}{next(_counter):02d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Inbox Test Landlord {n}", currency="KES")
    session.add(landlord)
    session.flush()

    ls = LandlordSettings(
        landlord_id=landlord.id,
        copilot_enabled=copilot_enabled,
        copilot_auto_allocate=auto_allocate,
        copilot_admin_locked=admin_locked,
        copilot_retain_unmatched=retain_unmatched,
    )
    session.add(ls)
    session.commit()
    return user, landlord


def make_property_unit(session, landlord):
    n = _uniq()
    prop = Property(landlord_id=landlord.id, name=f"Inbox Property {n}", number_of_units=1, city="Nairobi")
    session.add(prop)
    session.flush()
    unit = Unit(property_id=prop.id, name=f"U{n}", rent_amount=Decimal("10000.00"))
    session.add(unit)
    session.commit()
    return prop, unit


def make_tenant(session, landlord, unit, *, phone=None, account_number=None):
    n = _uniq()
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Inbox", last_name=f"Tenant{n}",
        phone=phone or f"+2547{n}{next(_counter):02d}",
        account_number=account_number or f"ACCT{n}",
        balance=Decimal("0.00"), credit_balance=Decimal("0.00"),
    )
    session.add(tenant)
    session.commit()
    return tenant


def make_device(session, landlord, *, status=CopilotDeviceStatus.active.value):
    raw_token, token_hash = svc.generate_device_token()
    device = CopilotDevice(
        landlord_id=landlord.id, device_name="Inbox Test Phone",
        token_hash=token_hash, status=status,
    )
    session.add(device)
    session.commit()
    device._raw_token = raw_token
    return device


def make_template(session, *, sender_id, template_text, priority=100):
    n = _uniq()
    t = SmsParserTemplate(
        name=f"Inbox Template {n}", sender_id=sender_id, template_text=template_text,
        is_active=True, priority=priority,
    )
    session.add(t)
    session.commit()
    return t


def auth_header(user):
    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return {"Authorization": f"Bearer {token}"}


def reset_request_globals():
    """
    utils.get_jwt_user() (and current_landlord_id()'s demo-mode check) cache
    their result on flask.g, keyed for the life of the APP context — not the
    request context. That's correct for a real WSGI server (each request
    gets its own fresh app context) but NOT for this test harness, where
    db_session's `with app.app_context():` stays open across every
    `client.get()` call in a test. Without this reset, a second request as a
    DIFFERENT user within the same test would silently reuse the first
    request's cached identity. Call this between requests in any test that
    authenticates as more than one user.
    """
    for attr in ("_jwt_user", "_demo_shadow_id", "_active_impersonation"):
        if hasattr(g, attr):
            delattr(g, attr)


# The real production paybill template + SMS from COPILOT_LANDLORD_INBOX_SPEC.md §1/§5.1.
PAYBILL_TEMPLATE_TEXT = (
    "{ref} Confirmed. Ksh{amount} received from {name} for account {account} "
    "on {date} at {time} New account balance is Ksh{*}. Amount you can transact "
    "within the day is {*}."
)

PRODUCTION_SMS = (
    "UG9MLAk3ML Confirmed. Ksh5000.00 received from SAHILPAY for account f2 "
    "on 21/7/26 at 5:51 PM New account balance is Ksh26,543.42. Amount you can "
    "transact within the day is 499,850.00."
)


def paybill_sms(ref="UG9MLAk3ML", amount="5000.00", name="SAHILPAY", account="f2",
                date_str="21/7/26", time_str="5:51 PM", balance="26,543.42", limit_="499,850.00"):
    return (
        f"{ref} Confirmed. Ksh{amount} received from {name} for account {account} "
        f"on {date_str} at {time_str} New account balance is Ksh{balance}. "
        f"Amount you can transact within the day is {limit_}."
    )


PERSONAL_TRANSFER_SMS = "You have received Ksh200 from JOHN DOE 254712345678 on 21/7/26 at 6:00 PM"


# ===========================================================================
# §5 — Parsing / scoping
# ===========================================================================

def test_real_world_production_regression(db_session):
    """§5.1 — the exact production template + exact production SMS from the
    2026-07-21 live test must parse cleanly once sender_id is fixed to MPESA."""
    user, landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=PRODUCTION_SMS,
    )
    db_session.commit()

    assert msg.parse_status == CopilotParseStatus.parsed.value
    assert msg.parsed_amount == Decimal("5000.00")
    assert msg.parsed_account == "f2"
    assert msg.parsed_ref == "UG9MLAK3ML"   # ref post-processing upper-cases


def test_auto_allocate_on_writes_confirmed_payment_and_allocates(db_session):
    """§5.2"""
    user, landlord = make_landlord(db_session, auto_allocate=True)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, account_number="f2")
    from services.category_service import seed_default_categories
    from models import Invoice, InvoiceLineItem, InvoiceStatus, LineItemStatus

    categories = seed_default_categories(landlord.id)
    rent_cat = next(c for c in categories if c.name == "Rent")
    inv = Invoice(
        invoice_number=f"INV-{tenant.id}-1", landlord_id=landlord.id,
        tenant_id=tenant.id, unit_id=unit.id, property_id=unit.property_id,
        issue_date=date.today(), status=InvoiceStatus.open.value,
        total_amount=Decimal("10000.00"), amount_paid=Decimal("0"), balance=Decimal("10000.00"),
    )
    db_session.add(inv)
    db_session.flush()
    line = InvoiceLineItem(
        invoice_id=inv.id, item="Rent", quantity=Decimal("1"), unit_price=Decimal("10000.00"),
        amount=Decimal("10000.00"), category_id=rent_cat.id, subcategory="current",
        amount_paid=Decimal("0"), status=LineItemStatus.open.value,
    )
    db_session.add(line)
    db_session.commit()

    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="f2", amount="5000.00"),
    )
    db_session.commit()

    assert msg.payment.status == PaymentStatus.confirmed.value
    assert len(msg.payment.payment_allocations) == 1
    db_session.refresh(tenant)
    assert tenant.balance == Decimal("5000.00")


def test_review_mode_leaves_balance_unchanged(db_session):
    """§5.3"""
    user, landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, account_number="f2")
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="f2", amount="5000.00"),
    )
    db_session.commit()

    assert msg.payment.status == PaymentStatus.pending.value
    db_session.refresh(tenant)
    assert tenant.balance == Decimal("0.00")


def test_unmatched_creates_mpesa_transaction_no_payment(db_session):
    """§5.4"""
    user, landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="NOTREAL"),
    )
    db_session.commit()

    assert msg.match_status == CopilotMatchStatus.unmatched.value
    assert msg.mpesa_transaction_id is not None
    assert msg.payment_id is None


def test_redaction_on_unmatched_template_message(db_session):
    """§5.5 — a personal-transfer SMS that no active template covers must be
    stored only as a redacted shape stub: no digits, no name survives."""
    user, landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=PERSONAL_TRANSFER_SMS,
    )
    db_session.commit()

    assert msg.parse_status == CopilotParseStatus.unparsed.value
    assert msg.raw_text_redacted is True
    assert not any(ch.isdigit() for ch in msg.raw_text)
    # §2.2's stub keeps only the first 40 (digit-masked) chars of the body as
    # a shape fingerprint — long enough that a name early in the message can
    # still appear, but never enough to expose amount/phone/ref (all masked).
    assert "254712345678" not in msg.raw_text
    assert "200" not in msg.raw_text
    assert msg.raw_text.startswith("[redacted: no matching template]")


def test_redaction_opt_out_preserves_raw_text(db_session):
    """§5.6 — copilot_retain_unmatched=True skips redaction."""
    user, landlord = make_landlord(db_session, retain_unmatched=True)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=PERSONAL_TRANSFER_SMS,
    )
    db_session.commit()

    assert msg.parse_status == CopilotParseStatus.unparsed.value
    assert msg.raw_text_redacted is False
    assert msg.raw_text == PERSONAL_TRANSFER_SMS


def test_dedupe_survives_redaction(db_session):
    """§5.7/§2.4 — dedupe_hash is computed from the TRUE body before
    redaction runs; forwarding the same unmatched SMS twice must still yield
    `duplicate` on the second, even though the first is now redacted."""
    user, landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg1 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=PERSONAL_TRANSFER_SMS,
    )
    db_session.commit()
    assert msg1.parse_status == CopilotParseStatus.unparsed.value
    assert msg1.raw_text_redacted is True

    msg2 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=PERSONAL_TRANSFER_SMS,
    )
    db_session.commit()

    assert msg2.parse_status == CopilotParseStatus.duplicate.value
    assert msg2.id != msg1.id


# ===========================================================================
# §3 / §5 (8-11) — Endpoints
# ===========================================================================

def test_landlord_a_cannot_read_landlord_b_message(db_session, client):
    user_a, landlord_a = make_landlord(db_session)
    user_b, landlord_b = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device_b = make_device(db_session, landlord_b)

    msg = svc.process_copilot_message(
        device_b, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="f2"),
    )
    db_session.commit()

    # Detail: landlord A must get 404, not landlord B's data.
    resp = client.get(f"/api/copilot/messages/{msg.id}", headers=auth_header(user_a))
    assert resp.status_code == 404

    # List: landlord A's list must never contain landlord B's message id.
    resp = client.get("/api/copilot/messages", headers=auth_header(user_a))
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.get_json()["messages"]]
    assert msg.id not in ids

    # Landlord B can read their own. (See reset_request_globals() docstring —
    # required before switching JWT identity within one ambient app context.)
    reset_request_globals()
    resp = client.get(f"/api/copilot/messages/{msg.id}", headers=auth_header(user_b))
    assert resp.status_code == 200
    assert resp.get_json()["id"] == msg.id


def test_status_match_and_search_filters(db_session, client):
    user, landlord = make_landlord(db_session)
    _, unit = make_property_unit(db_session, landlord)
    make_tenant(db_session, landlord, unit, account_number="f2")
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    matched = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="f2", ref="ZQFOUNDREF"),
    )
    unmatched = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="NOPE", ref="QXOTHERREF"),
    )
    unparsed = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=PERSONAL_TRANSFER_SMS,
    )
    db_session.commit()

    # status=unparsed
    resp = client.get("/api/copilot/messages", query_string={"status": "unparsed"}, headers=auth_header(user))
    ids = [m["id"] for m in resp.get_json()["messages"]]
    assert unparsed.id in ids and matched.id not in ids and unmatched.id not in ids

    # match=unmatched
    resp = client.get("/api/copilot/messages", query_string={"match": "unmatched"}, headers=auth_header(user))
    ids = [m["id"] for m in resp.get_json()["messages"]]
    assert unmatched.id in ids and matched.id not in ids

    # q= search over parsed_ref
    resp = client.get("/api/copilot/messages", query_string={"q": "ZQFOUNDREF"}, headers=auth_header(user))
    ids = [m["id"] for m in resp.get_json()["messages"]]
    assert matched.id in ids
    assert unmatched.id not in ids


def test_summary_counts(db_session, client):
    user, landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    make_tenant(db_session, landlord, unit, account_number="f2")
    make_template(db_session, sender_id="MPESA", template_text=PAYBILL_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    # 1 unparsed
    svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=PERSONAL_TRANSFER_SMS,
    )
    # 1 unmatched
    svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="NOPE", ref="SUMUNMATCHED"),
    )
    # 1 matched + pending review
    svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=paybill_sms(account="f2", ref="SUMPENDING"),
    )
    db_session.commit()

    resp = client.get("/api/copilot/messages/summary", headers=auth_header(user))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["unparsed"] == 1
    assert body["unmatched"] == 1
    assert body["pending_review"] == 1


def test_unauthenticated_request_rejected(client):
    resp = client.get("/api/copilot/messages")
    assert resp.status_code == 401


# ===========================================================================
# §9 — Two-message template robustness (§1.5 editor-fix regression)
# ===========================================================================

def test_two_message_robustness_correctly_built_template(db_session):
    """A template built the CORRECT way (account/ref/amount/name as
    placeholders, date/time as {date}/{time} rather than literals) must match
    two DIFFERENT real paybill SMS bodies with different ref/amount/date/time
    values. This is the regression test for the exact §1.5.1 failure mode,
    where the landlord left the masked phone tail / date / time / balance as
    hardcoded literals and the template only ever matched the one SMS it was
    built from."""
    template_pattern = svc.compile_template(PAYBILL_TEMPLATE_TEXT)

    sms_one = paybill_sms(
        ref="AAA111", amount="5000.00", account="f2",
        date_str="21/7/26", time_str="5:51 PM", balance="26,543.42", limit_="499,850.00",
    )
    sms_two = paybill_sms(
        ref="ZZZ999", amount="12345.00", account="b7",
        date_str="5/8/26", time_str="11:02 AM", balance="1,000.00", limit_="50,000.00",
    )

    match_one = template_pattern.search(sms_one)
    match_two = template_pattern.search(sms_two)

    assert match_one is not None
    assert match_one.group("ref") == "AAA111"
    assert match_one.group("amount") == "5000.00"
    assert match_one.group("account") == "f2"

    assert match_two is not None
    assert match_two.group("ref") == "ZZZ999"
    assert match_two.group("amount") == "12345.00"
    assert match_two.group("account") == "b7"
