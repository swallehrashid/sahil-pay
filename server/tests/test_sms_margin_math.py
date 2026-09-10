"""
The SMS resale arithmetic, end to end, with a per-landlord negotiated rate.

WHAT THIS IS FOR
----------------
Sahil Pay buys SMS credits in bulk and resells them. Different landlords pay
different rates — one agreed 0.80 on the phone, another 0.50, everybody else
pays the account-wide 1.00 — and the margin is the gap between what a credit is
sold for and what it costs to buy.

The pieces of that already existed and are individually tested. What nobody had
checked is that they AGREE: that the rate quoted on the buy screen is the rate
actually charged, that the rate charged is the one the margin report uses, and
that a landlord on a negotiated rate gets the number of credits their money buys
at THEIR price rather than at the standard one. Those are three different call
sites reading the same figure, and the failure mode when they disagree is not a
crash — it is books that look right and are wrong.

So this walks one number all the way through: set a rate, buy credits, send a
message, read the margin report, and assert the arithmetic closes at every step.
"""

import itertools
import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    Landlord, LandlordSettings, SmsPricingConfig, User,
)
from services import sms_billing

_counter = itertools.count()


def _uniq():
    return uuid.uuid4().hex[:10]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def rates(db_session):
    """A known price book: sell at 1.00, buy at 0.40."""
    cfg = SmsPricingConfig.get_singleton()
    cfg.default_price_per_sms = Decimal("1.00")
    cfg.platform_cost_per_sms = Decimal("0.40")
    db_session.commit()
    return {"default": Decimal("1.00"), "cost": Decimal("0.40")}


def _make_landlord(db_session, *, override=None):
    n = _uniq()
    user = User(email=f"sms-{n}@test.sahilpay", phone=f"2547{n[:9]}",
                password_hash=generate_password_hash("Testpass1"),
                role="landlord", is_verified=True, is_active=True)
    db_session.add(user)
    db_session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"SMS Test {n}",
                        currency="KES", sms_price_override=override, sms_balance=0)
    db_session.add(landlord)
    db_session.flush()
    db_session.add(LandlordSettings(landlord_id=landlord.id))
    db_session.commit()
    return user, landlord


def _auth(user):
    token = create_access_token(identity=str(user.id), additional_claims={"role": user.role})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# One price, decided in one place
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("override,expected", [
    (None,             "1.00"),   # the account-wide default
    (Decimal("0.80"),  "0.80"),   # the landlord's own words
    (Decimal("0.50"),  "0.50"),
    (Decimal("1.20"),  "1.20"),   # a premium rate is equally a negotiated one
])
def test_each_landlord_pays_their_own_rate(db_session, rates, override, expected):
    _, landlord = _make_landlord(db_session, override=override)

    price = sms_billing.effective_price_per_sms(
        landlord.landlord_settings, landlord=landlord
    )

    assert price == Decimal(expected)


def test_three_landlords_on_three_rates_do_not_affect_each_other(db_session, rates):
    """The whole point of a per-landlord rate: it is per landlord."""
    _, a = _make_landlord(db_session, override=Decimal("0.80"))
    _, b = _make_landlord(db_session, override=Decimal("0.50"))
    _, c = _make_landlord(db_session, override=None)

    prices = [
        sms_billing.effective_price_per_sms(x.landlord_settings, landlord=x)
        for x in (a, b, c)
    ]

    assert prices == [Decimal("0.80"), Decimal("0.50"), Decimal("1.00")]


def test_a_landlord_with_no_settings_row_keeps_their_rate(db_session, rates):
    """
    effective_price_per_sms is normally reached through LandlordSettings. An
    account without that row must not silently fall back to the standard rate —
    that is a discount nobody agreed to, applied invisibly.
    """
    _, landlord = _make_landlord(db_session, override=Decimal("0.80"))

    assert sms_billing.effective_price_per_sms(None, landlord=landlord) == Decimal("0.80")


# ---------------------------------------------------------------------------
# Buying: the money in, and the credits out
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("override,paid,expected_credits", [
    (Decimal("0.80"), Decimal("1000"), 1250),   # 1000 / 0.80
    (Decimal("0.50"), Decimal("1000"), 2000),   # 1000 / 0.50
    (None,            Decimal("1000"), 1000),   # 1000 / 1.00
])
def test_a_thousand_shillings_buys_credits_at_their_own_rate(
    db_session, rates, override, paid, expected_credits
):
    """
    The landlord's own framing: "anytime they pay 1,000 they get credits worth
    0.80 per credit, despite 1.00 being the universal rate."
    """
    _, landlord = _make_landlord(db_session, override=override)

    rate = sms_billing.effective_price_per_sms(landlord.landlord_settings, landlord=landlord)
    credits = int(paid / rate)

    assert credits == expected_credits
    # ...and the money that buys them reconciles back exactly.
    assert (rate * credits).quantize(Decimal("0.01")) == paid


def test_the_buy_screen_quotes_the_rate_that_is_charged(client, db_session, rates):
    """
    The quote and the charge come from the same function on purpose. When they
    did not, a landlord you had agreed 1.20 with was billed 1.00 at the till and
    the reports showed revenue that never arrived.
    """
    user, landlord = _make_landlord(db_session, override=Decimal("1.20"))

    response = client.post("/api/billing/buy-sms", headers=_auth(user),
                           json={"sms_count": 500, "payment_reference": f"REF{_uniq()}"})

    assert response.status_code == 202, response.get_data(as_text=True)
    txn = response.get_json()["transaction"]
    assert Decimal(str(txn["amount"])) == Decimal("600.00")     # 500 x 1.20
    assert txn["sms_count"] == 500


def test_the_default_rate_applies_when_nothing_was_negotiated(client, db_session, rates):
    user, landlord = _make_landlord(db_session, override=None)

    response = client.post("/api/billing/buy-sms", headers=_auth(user),
                           json={"sms_count": 500, "payment_reference": f"REF{_uniq()}"})

    assert Decimal(str(response.get_json()["transaction"]["amount"])) == Decimal("500.00")


# ---------------------------------------------------------------------------
# Sending: what a message costs the landlord, and what it costs Sahil Pay
# ---------------------------------------------------------------------------

def test_a_send_is_priced_at_the_landlords_rate_and_costed_at_wholesale(db_session, rates):
    """
    The margin on one message. Sahil Pay pays for delivery whichever sender ID
    the message goes out under, so the cost side must NOT vary with branding —
    recording zero there is what used to hide a real loss.
    """
    _, landlord = _make_landlord(db_session, override=Decimal("0.80"))

    quote = sms_billing.price_sms("Your rent is due on the 5th.", landlord.landlord_settings)

    credits = quote["credits"]
    assert credits >= 1
    assert quote["charge"] == (Decimal("0.80") * credits).quantize(Decimal("0.01"))
    assert quote["platform_cost"] == (Decimal("0.40") * credits).quantize(Decimal("0.01"))
    # The margin is the gap, and it is positive at this rate.
    assert quote["charge"] - quote["platform_cost"] == (Decimal("0.40") * credits).quantize(Decimal("0.01"))


def test_a_below_cost_rate_produces_a_real_negative_margin(db_session, rates):
    """
    A loss-leader is a legitimate commercial choice, so it must be REPRESENTED
    rather than clamped at zero. An admin reading the margin report needs to see
    the loss they agreed to.
    """
    _, landlord = _make_landlord(db_session, override=Decimal("0.25"))

    quote = sms_billing.price_sms("Short message.", landlord.landlord_settings)

    assert quote["charge"] < quote["platform_cost"]
    assert quote["charge"] - quote["platform_cost"] < 0


def test_longer_messages_cost_more_credits_at_the_same_rate(db_session, rates):
    """Credits scale with length; the RATE does not change with it."""
    _, landlord = _make_landlord(db_session, override=Decimal("0.80"))

    short = sms_billing.price_sms("Rent due.", landlord.landlord_settings)
    long_ = sms_billing.price_sms(" ".join(["word"] * 60), landlord.landlord_settings)

    assert long_["credits"] > short["credits"]
    for q in (short, long_):
        assert q["charge"] == (Decimal("0.80") * q["credits"]).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# The admin control
# ---------------------------------------------------------------------------

def _admin(db_session):
    from models import SystemAdmin

    n = _uniq()
    # totp_enabled is not optional: require_system_admin() refuses an admin
    # without a second factor, because that account can reach every landlord's
    # money. An admin fixture without it is not an admin.
    user = User(email=f"adm-{n}@test.sahilpay", phone=f"2547{n[:9]}",
                password_hash=generate_password_hash("Testpass1"),
                role="system_admin", is_verified=True, is_active=True,
                totp_enabled=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(SystemAdmin(user_id=user.id, first_name="Sys", last_name="Admin"))
    db_session.commit()
    return user


def test_an_admin_can_set_one_landlords_rate(client, db_session, rates):
    admin = _admin(db_session)
    _, landlord = _make_landlord(db_session, override=None)

    response = client.put(
        f"/api/admin/sms/landlords/{landlord.id}/price",
        headers=_auth(admin),
        json={"sms_price_override": 0.80, "reason": "Volume deal agreed on the phone"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    db_session.refresh(landlord)
    assert landlord.sms_price_override == Decimal("0.8000")
    assert sms_billing.effective_price_per_sms(
        landlord.landlord_settings, landlord=landlord) == Decimal("0.80")


def test_clearing_the_rate_returns_them_to_the_default(client, db_session, rates):
    admin = _admin(db_session)
    _, landlord = _make_landlord(db_session, override=Decimal("0.80"))

    response = client.put(
        f"/api/admin/sms/landlords/{landlord.id}/price",
        headers=_auth(admin),
        json={"sms_price_override": None, "reason": "Deal ended"},
    )

    assert response.status_code == 200
    db_session.refresh(landlord)
    assert landlord.sms_price_override is None
    assert sms_billing.effective_price_per_sms(
        landlord.landlord_settings, landlord=landlord) == Decimal("1.00")


def test_a_rate_below_cost_needs_saying_out_loud(client, db_session, rates):
    """
    Allowed, never by accident. The guard is what stops a mistyped 0.08 from
    quietly losing money on every message for months.
    """
    admin = _admin(db_session)
    _, landlord = _make_landlord(db_session)

    refused = client.put(
        f"/api/admin/sms/landlords/{landlord.id}/price",
        headers=_auth(admin),
        json={"sms_price_override": 0.20, "reason": "Loss leader"},
    )
    assert refused.status_code == 400
    assert "lose money" in refused.get_json()["error"]

    accepted = client.put(
        f"/api/admin/sms/landlords/{landlord.id}/price",
        headers=_auth(admin),
        json={"sms_price_override": 0.20, "reason": "Loss leader",
              "confirm_below_cost": True},
    )
    assert accepted.status_code == 200


def test_a_rate_change_is_audited_with_its_reason(client, db_session, rates):
    """These are verbally agreed commercial terms — the reason is the record."""
    from models import AuditLog

    admin = _admin(db_session)
    _, landlord = _make_landlord(db_session)

    client.put(f"/api/admin/sms/landlords/{landlord.id}/price", headers=_auth(admin),
               json={"sms_price_override": 0.80, "reason": "Volume deal, 10k/month"})

    entry = (AuditLog.query
             .filter_by(landlord_id=landlord.id, action="admin_set_landlord_sms_price")
             .order_by(AuditLog.id.desc()).first())
    assert entry is not None
    assert "Volume deal" in (entry.description or "")


def test_a_rate_needs_a_reason(client, db_session, rates):
    admin = _admin(db_session)
    _, landlord = _make_landlord(db_session)

    response = client.put(f"/api/admin/sms/landlords/{landlord.id}/price",
                          headers=_auth(admin), json={"sms_price_override": 0.80})

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# The margin report reads the same numbers
# ---------------------------------------------------------------------------

def test_the_margin_report_shows_each_landlords_own_rate(db_session, rates):
    """
    The report is how the margin is actually read. If it recomputed the rate
    its own way, it would be a second source of truth for the one number this
    whole feature exists to control.
    """
    from services import sms_analytics_service as analytics

    _, a = _make_landlord(db_session, override=Decimal("0.80"))
    _, b = _make_landlord(db_session, override=None)

    rows = {r["landlord_id"]: r for r in analytics._landlord_rows()}

    assert rows[a.id]["rate"] == 0.80
    assert rows[a.id]["has_own_rate"] is True
    assert rows[b.id]["rate"] == 1.00
    assert rows[b.id]["has_own_rate"] is False
