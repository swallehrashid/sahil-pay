"""
SMS reselling economics — one pool, one price.

Sahil Pay buys credits from FluxSMS wholesale, holds them in a single pool, and
sells the right to send. Every alphanumeric sender ID is registered with
FluxSMS ON SAHIL PAY'S ACCOUNT, so a landlord's own branded sender changes the
name on the recipient's handset and nothing else: the credits still come out of
the same pool and still cost Sahil Pay the same to buy.

That was not always true. The previous model assumed a branded sender meant the
landlord had their own FluxSMS account, so it charged a smaller "service fee",
recorded ZERO delivery cost, and never touched the pool. The moment a sender ID
was registered under Sahil Pay's account instead, the pool drained for real
while the books showed nothing. These tests exist so that cannot come back.

The second thing pinned here is that ONE function decides a landlord's price.
The buy screen used to read the global rate directly, so a negotiated rate
applied to the reports but not to the money actually taken — the books and the
bank disagreed by exactly the discount.
"""

import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    Landlord, LandlordSettings, SmsPricingConfig, SystemAdmin, User,
)
from services.sms_billing import (
    credits_for_words, effective_price_per_sms, price_sms,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def rates(db_session):
    """Known economics: buy at 0.40, sell at 1.00."""
    cfg = SmsPricingConfig.get_singleton()
    cfg.default_price_per_sms = Decimal("1.00")
    cfg.custom_price_per_sms = Decimal("0.50")     # retired; must not be used
    cfg.platform_cost_per_sms = Decimal("0.40")
    cfg.shared_sending_enabled = True
    cfg.pool_balance = 10_000
    db_session.flush()
    return cfg


def _landlord(s, *, sender_id=None, override=None, balance=100):
    n = _uniq()
    user = User(email=f"rs-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True, is_active=True)
    s.add(user)
    s.flush()
    landlord = Landlord(user_id=user.id, company_name=f"RS {n}", currency="KES",
                        sms_balance=balance, sms_price_override=override)
    s.add(landlord)
    s.flush()
    settings = LandlordSettings(landlord_id=landlord.id)
    if sender_id:
        settings.sms_sender_id = sender_id
        settings.sms_connected = True
    s.add(settings)
    s.flush()
    return landlord


# ---------------------------------------------------------------------------
# One price, whatever name is on the message
# ---------------------------------------------------------------------------

def test_a_branded_sender_pays_the_same_as_the_shared_one(db_session):
    """
    The sender ID is cosmetic. Charging less for it made sense only when the
    landlord was paying their own provider for delivery — they are not.
    """
    plain = _landlord(db_session)
    branded = _landlord(db_session, sender_id="BRANDX")

    assert effective_price_per_sms(plain.landlord_settings) == Decimal("1.00")
    assert effective_price_per_sms(branded.landlord_settings) == Decimal("1.00")


def test_the_retired_custom_rate_is_never_used(db_session, rates):
    """
    custom_price_per_sms still exists so an old config row and the admin PUT
    that writes it keep working. Nothing may price from it — set it somewhere
    absurd and the answer must not move.
    """
    rates.custom_price_per_sms = Decimal("999.00")
    db_session.flush()

    branded = _landlord(db_session, sender_id="BRANDX")
    assert effective_price_per_sms(branded.landlord_settings) == Decimal("1.00")


def test_a_negotiated_rate_beats_the_default(db_session):
    cheap = _landlord(db_session, override=Decimal("0.60"))
    dear = _landlord(db_session, override=Decimal("1.20"))

    assert effective_price_per_sms(cheap.landlord_settings) == Decimal("0.60")
    assert effective_price_per_sms(dear.landlord_settings) == Decimal("1.20")


def test_a_negotiated_rate_applies_to_a_branded_sender_too(db_session):
    landlord = _landlord(db_session, sender_id="BRANDX", override=Decimal("0.80"))
    assert effective_price_per_sms(landlord.landlord_settings) == Decimal("0.80")


def test_the_rate_is_found_without_a_settings_row(db_session):
    """
    A landlord with no LandlordSettings would otherwise silently lose their
    negotiated rate, because the override hangs off the landlord, not settings.
    """
    landlord = _landlord(db_session, override=Decimal("0.75"))
    assert effective_price_per_sms(None, landlord=landlord) == Decimal("0.75")


# ---------------------------------------------------------------------------
# Sahil Pay always pays for delivery
# ---------------------------------------------------------------------------

def test_wholesale_cost_is_recorded_for_a_branded_sender(db_session):
    """
    The exact regression that used to lose money: cost recorded as zero because
    the code believed the landlord's own provider account paid for it.
    """
    branded = _landlord(db_session, sender_id="BRANDX")
    quote = price_sms("Rent is due", branded.landlord_settings)

    assert quote["uses_own_sender_id"] is True
    assert quote["platform_cost"] == Decimal("0.40")
    assert quote["charge"] == Decimal("1.00")


def test_margin_is_the_same_on_both_paths(db_session):
    plain = _landlord(db_session)
    branded = _landlord(db_session, sender_id="BRANDX")

    a = price_sms("Rent is due", plain.landlord_settings)
    b = price_sms("Rent is due", branded.landlord_settings)

    assert a["charge"] - a["platform_cost"] == Decimal("0.60")
    assert b["charge"] - b["platform_cost"] == Decimal("0.60")


def test_a_loss_making_rate_produces_a_negative_margin(db_session):
    """Selling below wholesale is allowed, but the books must show the loss."""
    landlord = _landlord(db_session, override=Decimal("0.30"))
    quote = price_sms("Rent is due", landlord.landlord_settings)
    assert quote["charge"] - quote["platform_cost"] == Decimal("-0.10")


def test_a_long_message_costs_more_on_both_sides(db_session):
    """Credits scale with length, so revenue and cost must scale together."""
    landlord = _landlord(db_session)
    long_text = " ".join(["word"] * 60)          # 60 words → 3 credits

    assert credits_for_words(60) == 3
    quote = price_sms(long_text, landlord.landlord_settings)
    assert quote["credits"] == 3
    assert quote["charge"] == Decimal("3.00")
    assert quote["platform_cost"] == Decimal("1.20")


# ---------------------------------------------------------------------------
# The buy screen and the send path must agree
# ---------------------------------------------------------------------------

def test_the_buy_price_honours_a_negotiated_rate(db_session):
    """
    The books-versus-bank bug: the purchase screen read the global rate, so a
    landlord you had agreed 1.20 with was still charged 1.00 at the till.
    """
    from routes.billing_routes import _sms_unit_price

    landlord = _landlord(db_session, override=Decimal("1.20"))
    assert _sms_unit_price(landlord) == Decimal("1.20")


def test_the_buy_price_matches_what_the_send_path_charges(db_session):
    """One function decides the price, so these can never drift apart."""
    from routes.billing_routes import _sms_unit_price

    for override in (None, Decimal("0.60"), Decimal("1.20")):
        landlord = _landlord(db_session, override=override)
        buy = _sms_unit_price(landlord)
        send = price_sms("Rent is due", landlord.landlord_settings)["charge"]
        assert buy == send, f"buy {buy} != send {send} for override {override}"


def test_a_branded_sender_is_not_quoted_a_discount_at_the_till(db_session):
    from routes.billing_routes import _sms_unit_price

    branded = _landlord(db_session, sender_id="BRANDX")
    assert _sms_unit_price(branded) == Decimal("1.00")


# ---------------------------------------------------------------------------
# Setting a rate
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin(app, db_session):
    n = _uniq()
    user = User(email=f"rs-admin-{n}@test.sahilpay", phone=f"2546{n[:7]}",
                password_hash=generate_password_hash("Testpass1"),
                role="system_admin", is_verified=True, is_active=True,
                totp_enabled=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(SystemAdmin(user_id=user.id))
    db_session.flush()
    with app.app_context():
        token = create_access_token(identity=str(user.id),
                                    additional_claims={"role": "system_admin"})
    return {"user": user, "token": token}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_set_and_clear_a_rate(client, db_session, admin):
    landlord = _landlord(db_session)

    res = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                     headers=_auth(admin["token"]),
                     json={"sms_price_override": 0.80, "reason": "Volume deal"})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["effective_price"] == 0.80

    cleared = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                         headers=_auth(admin["token"]),
                         json={"sms_price_override": None, "reason": "Back to standard"})
    assert cleared.status_code == 200
    assert cleared.get_json()["sms_price_override"] is None
    assert cleared.get_json()["effective_price"] == 1.00


def test_a_rate_change_requires_a_reason(client, db_session, admin):
    """It is a verbally agreed commercial term — the audit log needs the why."""
    landlord = _landlord(db_session)
    res = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                     headers=_auth(admin["token"]),
                     json={"sms_price_override": 0.80})
    assert res.status_code == 400


def test_a_rate_below_wholesale_needs_explicit_confirmation(client, db_session, admin):
    """
    0.30 against a 0.40 cost loses money on every message. A loss-leader is a
    real choice, but never an accidental one.
    """
    landlord = _landlord(db_session)
    res = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                     headers=_auth(admin["token"]),
                     json={"sms_price_override": 0.30, "reason": "Trial"})
    assert res.status_code == 400
    assert "lose money" in res.get_json()["error"]

    forced = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                        headers=_auth(admin["token"]),
                        json={"sms_price_override": 0.30, "reason": "Trial",
                              "confirm_below_cost": True})
    assert forced.status_code == 200


def test_a_zero_or_negative_rate_is_refused(client, db_session, admin):
    landlord = _landlord(db_session)
    for bad in (0, -1):
        res = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                         headers=_auth(admin["token"]),
                         json={"sms_price_override": bad, "reason": "x"})
        assert res.status_code == 400


def test_setting_a_rate_is_closed_to_non_admins(client, db_session):
    landlord = _landlord(db_session)
    res = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                     json={"sms_price_override": 0.10, "reason": "nope"})
    assert res.status_code in (401, 403)
