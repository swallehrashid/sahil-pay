"""
Receipts for payments that no human touched.

Co-pilot can match an M-Pesa SMS and allocate the money on its own. Before
this, the tenant either heard nothing or got a bare "we received your payment"
with no breakdown, no PDF and no link — a worse receipt than the manual path
produced, for no reason other than which route the money took. Both paths now
go through one implementation.

The rule with teeth is the silent one: a payment sitting in SUSPENSE must send
NOTHING. "We have your money but don't know what it's for" is the exact phone
call the review queue exists to prevent, and it is worse than saying nothing at
all until a person has decided.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    AutomationSettings, ChargeCategory, Landlord, LandlordSettings, Payment,
    PaymentStatus, Property, Tenant, Unit, User,
)
from services import automation_service, receipt_service


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def estate(app, db_session):
    s = db_session
    n = _uniq()

    owner = User(email=f"ar-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()

    landlord = Landlord(user_id=owner.id, company_name=f"AR {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.add(ChargeCategory(landlord_id=landlord.id, name="Rent",
                         kind="invoice", is_metered=False))
    automation = AutomationSettings(landlord_id=landlord.id)
    s.add(automation)
    s.flush()

    prop = Property(landlord_id=landlord.id, name=f"Block {n}", city="Nairobi")
    s.add(prop)
    s.flush()
    unit = Unit(property_id=prop.id, name=f"U{n[:3]}", rent_amount=Decimal("20000"))
    s.add(unit)
    s.flush()

    tenant_user = User(email=f"art-{n}@test.sahilpay", phone=f"2548{n[:7]}",
                       password_hash=generate_password_hash("Testpass1"),
                       role="tenant", is_verified=True, is_active=True)
    s.add(tenant_user)
    s.flush()

    tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, user_id=tenant_user.id,
                    first_name="Joseph", last_name=n[:4],
                    phone=f"2549{n[:7]}", email=f"joe-{n}@test.sahilpay",
                    account_number=f"AR{n}", balance=Decimal("-5000"))
    s.add(tenant)
    s.flush()

    payment = Payment(landlord_id=landlord.id, tenant_id=tenant.id, unit_id=unit.id,
                      property_id=prop.id, amount=Decimal("5000"),
                      payment_date=date(2026, 8, 5),
                      payment_ref=f"PAY{n}", status=PaymentStatus.confirmed.value)
    s.add(payment)
    s.flush()

    return {"landlord": landlord, "tenant": tenant, "payment": payment,
            "automation": automation}


# ---------------------------------------------------------------------------
# Channel selection
# ---------------------------------------------------------------------------

def test_nothing_is_sent_while_the_feature_is_off(estate):
    """Off is the shipped default and must mean genuinely nothing."""
    assert automation_service.auto_receipt_channels(estate["landlord"]) == []


def test_channels_follow_the_individual_toggles(db_session, estate):
    aut = estate["automation"]
    aut.auto_receipt_enabled = True
    aut.auto_receipt_email = True
    aut.auto_receipt_sms = False
    aut.auto_receipt_in_app = True
    db_session.flush()

    assert automation_service.auto_receipt_channels(estate["landlord"]) == ["email", "in_app"]


def test_all_three_can_be_selected(db_session, estate):
    aut = estate["automation"]
    aut.auto_receipt_enabled = True
    aut.auto_receipt_email = aut.auto_receipt_sms = aut.auto_receipt_in_app = True
    db_session.flush()

    assert automation_service.auto_receipt_channels(estate["landlord"]) == \
        ["email", "sms", "in_app"]


def test_the_master_switch_beats_the_individual_ones(db_session, estate):
    """All three ticked but the feature off still sends nothing."""
    aut = estate["automation"]
    aut.auto_receipt_enabled = False
    aut.auto_receipt_email = aut.auto_receipt_sms = aut.auto_receipt_in_app = True
    db_session.flush()

    assert automation_service.auto_receipt_channels(estate["landlord"]) == []


def test_sms_is_off_by_default_when_the_feature_is_switched_on(db_session, estate):
    """
    SMS is billed per segment. An account should not discover this feature by
    running out of credit, so enabling it selects only the free channels.
    """
    aut = estate["automation"]
    aut.auto_receipt_enabled = True
    db_session.flush()

    channels = automation_service.auto_receipt_channels(estate["landlord"])
    assert "sms" not in channels
    assert "email" in channels and "in_app" in channels


# ---------------------------------------------------------------------------
# The SMS itself
# ---------------------------------------------------------------------------

def test_sms_states_the_amount_balance_and_a_receipt_link(estate):
    text = receipt_service.sms_receipt_text(estate["payment"])

    assert estate["payment"].payment_ref in text
    assert "5,000" in text
    assert "/api/receipts/public/" in text      # the tappable link
    assert "Thank you" in text


def test_sms_is_plain_ascii(estate):
    """
    One emoji or accented character forces the message into UCS-2, cutting a
    segment from 160 characters to 70 and up to tripling what the landlord pays
    for every message. Worth a test, because it is invisible until the bill.
    """
    text = receipt_service.sms_receipt_text(estate["payment"])
    assert text.isascii(), f"non-ASCII in SMS: {text!r}"


def test_sms_stays_short_enough_to_be_affordable(estate):
    text = receipt_service.sms_receipt_text(estate["payment"])
    # Three segments is the practical ceiling for a routine notification.
    assert len(text) <= 480, f"{len(text)} chars: {text!r}"


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def test_a_missing_contact_detail_skips_only_that_channel(db_session, estate):
    """A tenant with no email must still get the in-app copy."""
    estate["tenant"].email = None
    db_session.flush()

    sent, skipped = receipt_service.send_receipt(
        estate["payment"], ["email", "in_app"], landlord_id=estate["landlord"].id,
    )

    assert "in_app" in sent
    assert any("email" in s for s in skipped)


def test_whatsapp_is_reported_as_skipped_not_silently_dropped(estate):
    sent, skipped = receipt_service.send_receipt(
        estate["payment"], ["whatsapp"], landlord_id=estate["landlord"].id)
    assert sent == []
    assert any("whatsapp" in s for s in skipped)


def test_an_unknown_channel_is_reported(estate):
    sent, skipped = receipt_service.send_receipt(
        estate["payment"], ["carrier-pigeon"], landlord_id=estate["landlord"].id)
    assert sent == []
    assert any("carrier-pigeon" in s for s in skipped)


def test_a_payment_with_no_tenant_sends_nothing(db_session, estate):
    orphan = Payment(landlord_id=estate["landlord"].id, amount=Decimal("100"),
                     payment_date=date(2026, 8, 5), payment_ref=f"ORPH{_uniq()}",
                     status=PaymentStatus.confirmed.value)
    db_session.add(orphan)
    db_session.flush()

    sent, skipped = receipt_service.send_receipt(
        orphan, ["email"], landlord_id=estate["landlord"].id)
    assert sent == []
    assert skipped


# ---------------------------------------------------------------------------
# Auto-allocation entry point
# ---------------------------------------------------------------------------

def test_auto_allocated_payment_sends_the_receipt(db_session, estate):
    aut = estate["automation"]
    aut.auto_receipt_enabled = True
    aut.auto_receipt_email = False
    aut.auto_receipt_sms = False
    aut.auto_receipt_in_app = True
    db_session.flush()

    sent = automation_service.on_payment_auto_allocated(
        estate["landlord"], estate["payment"], estate["tenant"])

    assert sent == ["in_app"]


def test_auto_allocation_sends_nothing_when_the_feature_is_off(estate):
    sent = automation_service.on_payment_auto_allocated(
        estate["landlord"], estate["payment"], estate["tenant"])
    assert sent == []


def test_a_delivery_failure_never_breaks_the_payment(db_session, estate, monkeypatch):
    """
    The receipt is a courtesy; the payment is the money. A gateway outage must
    not roll back a tenant's credit.
    """
    aut = estate["automation"]
    aut.auto_receipt_enabled = True
    db_session.flush()

    def explode(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(receipt_service, "send_receipt", explode)

    sent = automation_service.on_payment_auto_allocated(
        estate["landlord"], estate["payment"], estate["tenant"])
    assert sent == []          # reported as nothing sent, no exception raised


def test_suspense_never_reaches_the_receipt_path():
    """
    The guarantee is structural, not a flag: copilot_service returns from the
    suspense and unmatched branches BEFORE the auto-allocation block, so a
    payment nobody could attribute cannot notify the tenant. Pinned here so a
    later edit that moves the call earlier fails loudly.
    """
    import inspect

    from services import copilot_service

    source = inspect.getsource(copilot_service._finalize_message)
    suspense_at = source.index("SuspenseReason.multi_lease")
    receipt_at = source.index("on_payment_auto_allocated")
    assert suspense_at < receipt_at, (
        "the auto-receipt call must stay AFTER the suspense branch returns"
    )
    # And the suspense branch must still return before reaching it.
    between = source[suspense_at:receipt_at]
    assert "return" in between
