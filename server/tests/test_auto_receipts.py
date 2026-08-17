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


# ---------------------------------------------------------------------------
# One receipt per payment
# ---------------------------------------------------------------------------
# A receipt is a statement of fact about one event, but several paths could each
# decide one was due — recording the payment, co-pilot allocating it, M-Pesa
# reconciliation — and none could see what the others had done. Two GET download
# endpoints emailed a copy on every fetch on top of that, which is how one
# payment produced a handful of receipts: opening the PDF sent another, and a
# mail scanner merely PREFETCHING the public link sent one with no human at all.

@pytest.fixture()
def emails(monkeypatch):
    """Every receipt email the code tries to dispatch."""
    from services import email_service

    captured = []
    monkeypatch.setattr(
        email_service.send_receipt_email, "delay",
        lambda *args, **kwargs: captured.append(args),
    )
    return captured


def test_the_receipt_email_goes_out_once(db_session, estate, emails):
    from services.receipt_service import send_receipt

    payment = estate["payment"]
    landlord_id = estate["landlord"].id

    first, _ = send_receipt(payment, ["email"], landlord_id=landlord_id)
    assert first == ["email"]
    assert len(emails) == 1

    # The other paths that would each have sent their own copy.
    for _ in range(4):
        send_receipt(payment, ["email"], landlord_id=landlord_id)

    assert len(emails) == 1, f"receipt emailed {len(emails)} times for one payment"


def test_a_repeat_send_reports_why_it_skipped(db_session, estate, emails):
    """Skipping silently is how "the tenant never got it" goes unnoticed."""
    from services.receipt_service import send_receipt

    send_receipt(estate["payment"], ["email"], landlord_id=estate["landlord"].id)
    _, skipped = send_receipt(estate["payment"], ["email"], landlord_id=estate["landlord"].id)

    assert any("already emailed" in reason for reason in skipped)


def test_the_first_send_is_stamped_on_the_payment(db_session, estate, emails):
    from services.receipt_service import send_receipt

    payment = estate["payment"]
    assert payment.receipt_emailed_at is None

    send_receipt(payment, ["email"], landlord_id=estate["landlord"].id)

    assert payment.receipt_emailed_at is not None


def test_a_human_can_still_deliberately_resend(db_session, estate, emails):
    """
    The landlord pressing "send receipt" means it: the tenant deleted it, or the
    address was fixed. That is the one caller allowed past the guard.
    """
    from services.receipt_service import send_receipt

    payment = estate["payment"]
    landlord_id = estate["landlord"].id

    send_receipt(payment, ["email"], landlord_id=landlord_id)
    sent, _ = send_receipt(payment, ["email"], landlord_id=landlord_id, force_email=True)

    assert sent == ["email"]
    assert len(emails) == 2


def test_two_different_payments_each_get_their_own_receipt(db_session, estate, emails):
    """The guard is per payment, not per tenant — an obvious way to get it wrong."""
    from services.receipt_service import send_receipt

    first = estate["payment"]
    second = Payment(
        landlord_id=first.landlord_id, tenant_id=first.tenant_id,
        unit_id=first.unit_id, property_id=first.property_id,
        amount=Decimal("7000"), payment_date=date(2026, 9, 5),
        payment_ref=f"{first.payment_ref}-2", status=PaymentStatus.confirmed.value,
    )
    db_session.add(second)
    db_session.flush()

    send_receipt(first, ["email"], landlord_id=first.landlord_id)
    send_receipt(second, ["email"], landlord_id=first.landlord_id)

    assert len(emails) == 2


def test_the_guard_does_not_suppress_the_other_channels(db_session, estate, emails):
    """
    Only email is de-duplicated. An in-app notification lands in a list the
    tenant already sees, and suppressing it would lose the record of a resend.
    """
    from services.receipt_service import send_receipt

    payment = estate["payment"]
    landlord_id = estate["landlord"].id

    send_receipt(payment, ["email", "in_app"], landlord_id=landlord_id)
    sent, _ = send_receipt(payment, ["email", "in_app"], landlord_id=landlord_id)

    assert "in_app" in sent
    assert "email" not in sent


# ---------------------------------------------------------------------------
# Once, and only once
# ---------------------------------------------------------------------------
# A receipt is a statement of fact about one event. Several callers could each
# decide one was due — recording a payment, co-pilot auto-allocation, M-Pesa
# reconciliation, the "send receipt" button — and two GET *download* endpoints
# emailed a fresh copy on every fetch. Nothing recorded that a receipt had
# already gone out, so a single payment produced a burst of identical emails,
# some of them triggered by link scanners rather than by a person.

def test_the_receipt_email_is_sent_only_once(db_session, estate):
    payment = estate["payment"]
    assert payment.receipt_emailed_at is None

    first, _ = receipt_service.send_receipt(payment, ["email"])
    assert first == ["email"]
    assert payment.receipt_emailed_at is not None

    second, skipped = receipt_service.send_receipt(payment, ["email"])
    assert second == []
    assert any("already emailed" in reason for reason in skipped)


def test_every_caller_shares_the_same_guard(db_session, estate):
    """
    The point is not that one function is idempotent — it is that the separate
    paths cannot each send their own copy.
    """
    payment = estate["payment"]
    estate["automation"].auto_receipt_enabled = True
    estate["automation"].auto_receipt_email = True
    db.session.flush()

    sent_first = automation_service.on_payment_auto_allocated(
        estate["landlord"], payment, estate["tenant"])
    assert "email" in sent_first

    # A second, independent path now finds the stamp and declines.
    sent_again, skipped = receipt_service.send_receipt(payment, ["email"])
    assert sent_again == []
    assert skipped


def test_a_human_resend_is_still_allowed(db_session, estate):
    """
    Pressing "send receipt" means send another copy — that IS the intent, and
    the guard must not turn a deliberate action into a silent no-op.
    """
    payment = estate["payment"]
    receipt_service.send_receipt(payment, ["email"])
    first_stamp = payment.receipt_emailed_at

    sent, _ = receipt_service.send_receipt(payment, ["email"], force_email=True)

    assert sent == ["email"]
    assert payment.receipt_emailed_at >= first_stamp


def test_the_guard_does_not_suppress_other_channels(db_session, estate):
    """
    Only email is de-duplicated. An in-app notice lands in a list the tenant can
    already see, and suppressing it because an email went out weeks ago would
    hide the record of a NEW delivery attempt.
    """
    payment = estate["payment"]
    receipt_service.send_receipt(payment, ["email"])

    sent, _ = receipt_service.send_receipt(payment, ["email", "in_app"])

    assert "email" not in sent
    assert "in_app" in sent


def test_downloading_a_receipt_does_not_email_one(app, db_session, estate):
    """
    The self-amplifying half of the bug: the tenant portal download and the
    public SMS link both emailed a copy on every fetch, so opening your own
    receipt sent you another — and a mail scanner PREFETCHING the public link
    sent one with nobody involved at all.
    """
    import inspect

    from routes import payment_routes, tenant_portal_routes

    for module in (payment_routes, tenant_portal_routes):
        source = inspect.getsource(module)
        assert "send_receipt_email" not in source, (
            f"{module.__name__} still emails a receipt from a download path"
        )
