"""
Regression suite for the Co-pilot SMS-forwarder pipeline
(services/copilot_service.py). See COPILOT_PLATFORM_SPEC.md §11.

Tests the SERVICE layer directly against real Postgres, mirroring
test_affiliate_service.py's convention — route-level concerns (the /pair
HTTP endpoint's rate limiting, bad-agent-code 404, revoked-device 401) are
covered by the curl walkthrough in COPILOT_ROLLOUT_TESTING.md Phase 2, not
here.
"""

import itertools
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, Landlord, LandlordSettings, Property, Unit, Tenant,
    Invoice, InvoiceLineItem, InvoiceStatus, LineItemStatus,
    SmsParserTemplate, CopilotDevice, CopilotDeviceStatus,
    CopilotParseStatus, CopilotMatchStatus, PaymentStatus, PaymentSource,
)
from services.category_service import seed_default_categories
from services import copilot_service as svc

_counter = itertools.count()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def make_landlord(session, *, copilot_enabled=True, auto_allocate=False, admin_locked=False):
    n = next(_counter)
    user = User(
        email=f"landlord{n}@test.sahilpay", phone=f"25470{n:07d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(user_id=user.id, company_name=f"Test Landlord {n}", currency="KES")
    session.add(landlord)
    session.flush()

    ls = LandlordSettings(
        landlord_id=landlord.id,
        copilot_enabled=copilot_enabled,
        copilot_auto_allocate=auto_allocate,
        copilot_admin_locked=admin_locked,
    )
    session.add(ls)
    session.flush()
    return landlord


def make_property_unit(session, landlord):
    n = next(_counter)
    prop = Property(landlord_id=landlord.id, name=f"Property {n}", number_of_units=1, city="Nairobi")
    session.add(prop)
    session.flush()
    unit = Unit(property_id=prop.id, name=f"U{n}", rent_amount=Decimal("10000.00"))
    session.add(unit)
    session.flush()
    return prop, unit


def make_tenant(session, landlord, unit, *, phone=None, account_number=None):
    n = next(_counter)
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Test", last_name=f"Tenant{n}",
        phone=phone or f"+254711{n:06d}",
        account_number=account_number or f"ACCT{n}",
        balance=Decimal("0.00"), credit_balance=Decimal("0.00"),
    )
    session.add(tenant)
    session.flush()
    return tenant


def make_device(session, landlord, *, status=CopilotDeviceStatus.active.value):
    raw_token, token_hash = svc.generate_device_token()
    device = CopilotDevice(
        landlord_id=landlord.id, device_name="Test Phone",
        token_hash=token_hash, status=status,
    )
    session.add(device)
    session.flush()
    device._raw_token = raw_token  # test convenience only, not persisted
    return device


def make_template(session, *, sender_id, template_text, priority=100):
    n = next(_counter)
    t = SmsParserTemplate(
        name=f"Template {n}", sender_id=sender_id, template_text=template_text,
        is_active=True, priority=priority,
    )
    session.add(t)
    session.flush()
    return t


def make_outstanding_invoice(session, landlord, tenant, unit, amount=Decimal("10000.00")):
    """One outstanding 'Rent'/'current' line item — enough to exercise auto_allocate."""
    categories = seed_default_categories(landlord.id)
    rent_cat = next(c for c in categories if c.name == "Rent")

    inv = Invoice(
        invoice_number=f"INV-{tenant.id}-{next(_counter)}", landlord_id=landlord.id,
        tenant_id=tenant.id, unit_id=unit.id, property_id=unit.property_id,
        issue_date=date.today(), status=InvoiceStatus.open.value,
        total_amount=amount, amount_paid=Decimal("0"), balance=amount,
    )
    session.add(inv)
    session.flush()
    line = InvoiceLineItem(
        invoice_id=inv.id, item="Rent", quantity=Decimal("1"), unit_price=amount,
        amount=amount, category_id=rent_cat.id, subcategory="current",
        amount_paid=Decimal("0"), status=LineItemStatus.open.value,
    )
    session.add(line)
    session.flush()
    return inv, line


MPESA_TEMPLATE_TEXT = "{ref} Confirmed. {*}Ksh{amount} received from {name} {phone} on {*}"
MPESA_ACCOUNT_TEMPLATE_TEXT = (
    "{ref} Confirmed.{*}Ksh{amount}{*}received from {name} {phone}{*}for account {account}{*}"
)


def mpesa_sms(ref="SFR4XKPLM0", amount="1,500.00", name="JOHN DOE", phone="254712345678"):
    return f"{ref} Confirmed. Ksh{amount} received from {name} {phone} on 1/6/25 at 10:34 AM"


def mpesa_account_sms(ref="SFR4XKPLM1", amount="2,000.00", name="JOHN DOE",
                       phone="254712345678", account="A12"):
    return (f"{ref} Confirmed. Ksh{amount} received from {name} {phone} "
            f"for account {account} on 1/6/25 at 10:34 AM")


# ===========================================================================
# Template compiler
# ===========================================================================

def test_compile_template_requires_amount_placeholder():
    with pytest.raises(ValueError, match="amount"):
        svc.compile_template("{ref} Confirmed. No amount here.")


def test_compile_template_rejects_unknown_placeholder():
    with pytest.raises(ValueError, match="Unknown placeholder"):
        svc.compile_template("{ref} paid {amount} to {bogus}")


def test_compile_template_rejects_adjacent_loose_placeholders():
    with pytest.raises(ValueError, match="free-text placeholders"):
        svc.compile_template("{amount} from {name}{*}")


def test_compile_template_allows_bounded_placeholder_adjacent_to_loose():
    # {amount}(bounded) directly followed by {*}(loose) is fine — amount's
    # character class self-terminates.
    pattern = svc.compile_template("Ksh{amount}{*}received from {name} {phone}")
    m = pattern.search("Ksh1,500.00 received from JOHN DOE 254712345678")
    assert m.group("amount") == "1,500.00"


def test_compile_template_tolerates_whitespace_variation():
    pattern = svc.compile_template("{ref} Confirmed. Ksh{amount} received from {name} {phone}")
    # Extra/newline whitespace where the template only has single spaces.
    text = "REF123456  Confirmed.\nKsh1,000.00   received  from JANE DOE 254712345678"
    assert pattern.search(text) is not None


def test_placeholder_post_processing_via_parse_sms(db_session):
    make_template(db_session, sender_id="TESTBANK", template_text=MPESA_TEMPLATE_TEXT)
    template, fields = svc.parse_sms("TESTBANK", mpesa_sms())
    assert template is not None
    assert fields["amount"] == Decimal("1500.00")
    assert fields["ref"] == "SFR4XKPLM0"
    assert fields["name"] == "JOHN DOE"
    assert fields["phone"] == "254712345678"


def test_parse_sms_tries_templates_in_priority_order(db_session):
    make_template(db_session, sender_id="TESTBANK2", template_text=MPESA_ACCOUNT_TEMPLATE_TEXT, priority=50)
    make_template(db_session, sender_id="TESTBANK2", template_text=MPESA_TEMPLATE_TEXT, priority=100)
    template, fields = svc.parse_sms("TESTBANK2", mpesa_account_sms())
    assert fields["account"] == "A12"   # only the priority-50 (account) template extracts this


def test_parse_sms_no_match_returns_none(db_session):
    make_template(db_session, sender_id="TESTBANK3", template_text=MPESA_TEMPLATE_TEXT)
    template, fields = svc.parse_sms("TESTBANK3", "Completely unrelated text.")
    assert template is None
    assert fields is None


def test_test_template_reports_match_failure():
    result = svc.test_template(MPESA_TEMPLATE_TEXT, "nothing like an mpesa sms")
    assert result["ok"] is False
    assert "error" in result


def test_test_template_reports_compiler_error():
    result = svc.test_template("{amount}{name}{*}", "irrelevant")
    assert result["ok"] is False
    assert "free-text" in result["error"]


# ===========================================================================
# Device tokens
# ===========================================================================

def test_device_token_round_trip():
    raw, digest = svc.generate_device_token()
    assert svc.hash_device_token(raw) == digest
    assert svc.hash_device_token("something-else") != digest


# ===========================================================================
# Ingest pipeline
# ===========================================================================

def test_pipeline_matched_by_account_number(db_session):
    landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, account_number="A12")
    make_template(db_session, sender_id="MPESA", template_text=MPESA_ACCOUNT_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_account_sms(account="A12"),
    )

    assert msg.parse_status == CopilotParseStatus.parsed.value
    assert msg.match_status == CopilotMatchStatus.matched.value
    assert msg.tenant_id == tenant.id
    assert msg.payment_id is not None
    assert msg.payment.status == PaymentStatus.pending.value
    assert msg.payment.source == PaymentSource.co_pilot.value


def test_pipeline_matched_by_phone_with_plus_prefix(db_session):
    landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    # Tenant.phone stored WITH a leading '+', matching how seed.py stores it.
    tenant = make_tenant(db_session, landlord, unit, phone="+254712345678")
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(phone="254712345678"),
    )

    assert msg.match_status == CopilotMatchStatus.matched.value
    assert msg.tenant_id == tenant.id


def test_pipeline_unmatched_when_no_tenant_hits(db_session):
    landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(phone="254799999999"),
    )

    assert msg.parse_status == CopilotParseStatus.parsed.value
    assert msg.match_status == CopilotMatchStatus.unmatched.value
    assert msg.payment_id is None
    assert msg.mpesa_transaction_id is not None


def test_pipeline_unparsed_when_no_template_matches(db_session):
    landlord = make_landlord(db_session)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="RANDOMBANK",
        raw_text="Some message no template covers.",
    )

    assert msg.parse_status == CopilotParseStatus.unparsed.value
    assert msg.match_status == CopilotMatchStatus.n_a.value


def test_pipeline_client_uuid_replay_is_idempotent(db_session):
    landlord = make_landlord(db_session)
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)
    client_uuid = str(uuid.uuid4())

    msg1 = svc.process_copilot_message(
        device, client_uuid=client_uuid, sender_id="MPESA", raw_text=mpesa_sms(),
    )
    msg2 = svc.process_copilot_message(
        device, client_uuid=client_uuid, sender_id="MPESA", raw_text=mpesa_sms(),
    )

    assert msg1.id == msg2.id   # same row returned, nothing duplicated


def test_pipeline_dedupe_hash_replay_within_7_days(db_session):
    landlord = make_landlord(db_session)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, phone="+254712345678")
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    text = mpesa_sms(ref="DUPEREF001", phone="254712345678")
    msg1 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=text,
    )
    # Different client_uuid, identical text — e.g. re-forwarded after a
    # code regeneration or a queue replay across two app installs.
    msg2 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=text,
    )

    assert msg1.id != msg2.id
    assert msg1.parse_status == CopilotParseStatus.parsed.value
    assert msg2.parse_status == CopilotParseStatus.duplicate.value
    assert msg2.payment_id is None


def test_pipeline_parsed_ref_replay_against_existing_mpesa_transaction(db_session):
    landlord = make_landlord(db_session)
    _, unit = make_property_unit(db_session, landlord)
    make_tenant(db_session, landlord, unit, phone="+254712345678")
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg1 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(ref="UNIQUEREF9", phone="254712345678"),
    )
    assert msg1.parse_status == CopilotParseStatus.parsed.value

    # Same ref, different wording entirely — dedupe_hash would differ, but the
    # parsed_ref vs MpesaTransaction check must still catch it (step 4).
    msg2 = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(ref="UNIQUEREF9", phone="254712345678", name="A DIFFERENT NAME"),
    )
    assert msg2.parse_status == CopilotParseStatus.duplicate.value
    assert msg2.payment_id is None


def test_pipeline_rejects_when_landlord_disabled(db_session):
    landlord = make_landlord(db_session, copilot_enabled=False)
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=mpesa_sms(),
    )

    assert msg.parse_status == CopilotParseStatus.rejected.value
    assert msg.error_reason is not None


def test_pipeline_rejects_when_admin_locked(db_session):
    landlord = make_landlord(db_session, copilot_enabled=True, admin_locked=True)
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=mpesa_sms(),
    )

    assert msg.parse_status == CopilotParseStatus.rejected.value


# ===========================================================================
# Ledger correctness (allocation_service is the only writer)
# ===========================================================================

def test_auto_allocate_path_creates_confirmed_payment_and_allocates(db_session):
    landlord = make_landlord(db_session, auto_allocate=True)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, phone="+254712345678")
    inv, line = make_outstanding_invoice(db_session, landlord, tenant, unit, amount=Decimal("10000.00"))
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(amount="4,000.00", phone="254712345678"),
    )

    assert msg.payment.status == PaymentStatus.confirmed.value
    assert len(msg.payment.payment_allocations) == 1
    alloc = msg.payment.payment_allocations[0]
    assert alloc.amount_allocated == Decimal("4000.00")

    db_session.refresh(line)
    db_session.refresh(tenant)
    assert line.amount_paid == Decimal("4000.00")
    assert line.status == LineItemStatus.open.value   # partially paid, still open
    assert tenant.balance == Decimal("4000.00")        # moved by the allocated amount


def test_pending_path_touches_no_balances_until_confirmed(db_session):
    landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, phone="+254712345678")
    inv, line = make_outstanding_invoice(db_session, landlord, tenant, unit, amount=Decimal("10000.00"))
    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA",
        raw_text=mpesa_sms(amount="4,000.00", phone="254712345678"),
    )

    assert msg.payment.status == PaymentStatus.pending.value
    assert msg.payment.payment_allocations == []

    db_session.refresh(line)
    db_session.refresh(tenant)
    assert line.amount_paid == Decimal("0.00")   # untouched
    assert tenant.balance == Decimal("0.00")     # untouched — only confirm() moves this


# ===========================================================================
# Retry (admin unparsed-queue workflow)
# ===========================================================================

def test_retry_unparsed_message_resolves_after_template_added(db_session):
    landlord = make_landlord(db_session, auto_allocate=False)
    _, unit = make_property_unit(db_session, landlord)
    tenant = make_tenant(db_session, landlord, unit, phone="+254712345678")
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="NEWBANK",
        raw_text=mpesa_sms(phone="254712345678"),
    )
    assert msg.parse_status == CopilotParseStatus.unparsed.value

    # Admin adds a template for this sender after seeing the unparsed queue...
    make_template(db_session, sender_id="NEWBANK", template_text=MPESA_TEMPLATE_TEXT)

    svc.retry_unparsed_message(msg)

    assert msg.parse_status == CopilotParseStatus.parsed.value
    assert msg.match_status == CopilotMatchStatus.matched.value
    assert msg.tenant_id == tenant.id


def test_retry_refuses_when_landlord_currently_disabled(db_session):
    landlord = make_landlord(db_session, copilot_enabled=False)
    device = make_device(db_session, landlord)

    msg = svc.process_copilot_message(
        device, client_uuid=str(uuid.uuid4()), sender_id="MPESA", raw_text=mpesa_sms(),
    )
    assert msg.parse_status == CopilotParseStatus.rejected.value

    make_template(db_session, sender_id="MPESA", template_text=MPESA_TEMPLATE_TEXT)
    svc.retry_unparsed_message(msg)

    # Still disabled — retry must not silently process it.
    assert msg.parse_status == CopilotParseStatus.rejected.value
    assert "disabled" in msg.error_reason.lower()
