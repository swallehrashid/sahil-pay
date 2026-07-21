"""
Tests for the FluxSMS integration (FLUXSMS_INTEGRATION_SPEC.md).

Covers: phone normalization + provider-response parsing in
services/sms_service.py (HTTP mocked, no network calls), the balance gate and
charge-after-success semantics in services/communication_service.py's
dispatch_message(), and the settings-routes connect validation.

dispatch_message() and the /connect route both commit internally, so — like
test_demo_mode.py's convention — every test that exercises them cleans up its
own committed rows in a `finally` block rather than relying on the fixture's
rollback (which can't undo a commit that already happened).
"""

import itertools
import json
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import text
from werkzeug.security import generate_password_hash

from models import User, Landlord, LandlordSettings, Property, Unit, Tenant, SmsPricingConfig

_counter = itertools.count()


# ---------------------------------------------------------------------------
# Factories (mirrors test_copilot_service.py's convention)
# ---------------------------------------------------------------------------

def make_landlord(session, **overrides):
    n = next(_counter)
    user = User(
        email=f"fluxsms-landlord{n}@test.sahilpay", phone=f"25470{n:07d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(
        user_id=user.id, company_name=f"FluxSMS Test Landlord {n}", currency="KES",
        sms_balance=overrides.pop("sms_balance", 100),
        **overrides,
    )
    session.add(landlord)
    session.flush()
    return landlord


def make_settings(session, landlord, **overrides):
    ls = LandlordSettings(landlord_id=landlord.id, **overrides)
    session.add(ls)
    session.flush()
    return ls


def make_tenant(session, landlord, *, phone=None):
    n = next(_counter)
    prop = Property(landlord_id=landlord.id, name=f"Property {n}", number_of_units=1, city="Nairobi")
    session.add(prop)
    session.flush()
    unit = Unit(property_id=prop.id, name=f"U{n}", rent_amount=Decimal("10000.00"))
    session.add(unit)
    session.flush()
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="Test", last_name=f"Tenant{n}",
        phone=phone or f"+254711{n:06d}",
        balance=Decimal("0.00"), credit_balance=Decimal("0.00"),
    )
    session.add(tenant)
    session.flush()
    return tenant


def _reset_sms_pricing(session):
    cfg = SmsPricingConfig.get_singleton()
    cfg.default_price_per_sms = Decimal("1.00")
    cfg.custom_price_per_sms = Decimal("0.50")
    cfg.platform_cost_per_sms = Decimal("0.65")
    cfg.shared_sending_enabled = True
    cfg.pool_balance = 10_000
    session.flush()
    return cfg


def _cleanup_landlord(session, landlord):
    """Wipe a landlord (and everything FK-dependent on it) committed during a
    test — mirrors test_demo_mode.py's _cleanup_shadow_and_landlord pattern,
    since dispatch_message()/the connect route commit internally and a plain
    rollback can't undo that."""
    user_id = landlord.user_id
    session.execute(text("DELETE FROM audit_logs WHERE landlord_id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM communication_logs WHERE landlord_id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM tenants WHERE landlord_id = :lid"), {"lid": landlord.id})
    session.execute(
        text("DELETE FROM units WHERE property_id IN (SELECT id FROM properties WHERE landlord_id = :lid)"),
        {"lid": landlord.id},
    )
    session.execute(text("DELETE FROM properties WHERE landlord_id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM landlord_settings WHERE landlord_id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM landlords WHERE id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    session.commit()


# ---------------------------------------------------------------------------
# services/sms_service.py — phone normalization + response parsing (HTTP mocked)
# ---------------------------------------------------------------------------

class TestSmsServiceSend:
    def test_send_sms_success_returns_messageid(self, app):
        from services import sms_service

        with app.app_context():
            app.config["FLUXSMS_API_KEY"] = "test-key"
            app.config["FLUXSMS_SENDER_ID"] = "SAHILPAY"

            fake_response = json.loads(json.dumps({
                "response-code": 200, "response-description": "Success",
                "mobile": 254712345678, "messageid": "MSGID123", "networkid": 1,
            }))

            with patch("services.sms_service._post", return_value=fake_response) as mock_post:
                result = sms_service.send_sms("0712345678", "Hello")
                assert result == "MSGID123"
                body = mock_post.call_args[0][1]
                assert body["phone"] == "0712345678"
                assert body["sender_id"] == "SAHILPAY"
                assert body["api_key"] == "test-key"

    def test_send_sms_error_response_returns_none(self, app):
        from services import sms_service

        with app.app_context():
            app.config["FLUXSMS_API_KEY"] = "test-key"
            with patch("services.sms_service._post", return_value={"error": "Invalid API key"}):
                assert sms_service.send_sms("0712345678", "Hello") is None

    def test_send_sms_no_key_configured_returns_none_stub(self, app):
        from services import sms_service

        with app.app_context():
            app.config["FLUXSMS_API_KEY"] = None
            assert sms_service.send_sms("0712345678", "Hello") is None

    def test_normalize_phone_strips_non_digits(self):
        from services.sms_service import _normalize_phone
        assert _normalize_phone("+254 711 234 567") == "254711234567"
        assert _normalize_phone("0712-345-678") == "0712345678"

    def test_check_sms_balance_success(self, app):
        from services import sms_service

        with app.app_context():
            app.config["FLUXSMS_API_KEY"] = "test-key"
            with patch("services.sms_service._post", return_value={"success": True, "sms_balance": 124}):
                assert sms_service.check_sms_balance() == 124

    def test_check_sms_balance_bad_key_returns_none(self, app):
        from services import sms_service

        with app.app_context():
            app.config["FLUXSMS_API_KEY"] = "bad-key"
            with patch("services.sms_service._post", return_value={"error": "Invalid API key"}):
                assert sms_service.check_sms_balance(api_key="bad-key") is None


# ---------------------------------------------------------------------------
# services/communication_service.py — dispatch_message balance gate + charge timing
# ---------------------------------------------------------------------------

class TestDispatchMessageBalanceGate:
    """NB: db_session already runs inside a live app.app_context() (see
    conftest.py) — do NOT open a nested `with app.app_context():` here; a
    second push/pop cycle detaches ORM objects (like the returned log) from
    the session before assertions can read their attributes."""

    def test_blocked_when_balance_below_segments(self, app, db_session):
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=0)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = True
            log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Balance due")
            db_session.commit()

            assert log.status == "failed"
            assert log.sms_charge == 0
            assert log.platform_cost == 0
            db_session.refresh(landlord)
            assert landlord.sms_balance == 0
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_custom_sender_also_gated_by_balance(self, app, db_session):
        """A custom (own-sender) landlord with 0 credits must still be blocked —
        custom senders are NOT exempt from the balance gate."""
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=0)
        make_settings(db_session, landlord, sms_api_key="custom-key", sms_sender_id="BRANDX", sms_connected=True)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = True
            log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Balance due")
            db_session.commit()

            assert log.status == "failed"
            assert log.uses_own_sender is True
            assert log.sms_charge == 0
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_successful_simulated_send_decrements_balance(self, app, db_session):
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=10)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = True
            log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Balance due")
            db_session.commit()

            assert log.status == "delivered"
            assert log.sms_charge == Decimal("1.00")
            db_session.refresh(landlord)
            assert landlord.sms_balance == 9
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_failed_real_send_does_not_burn_credits(self, app, db_session):
        """A provider-level failure (send_sms returns None) must not decrement
        the landlord's balance or record a charge."""
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=10)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = False
            with patch("services.sms_service.send_sms", return_value=None):
                log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Balance due")
                db_session.commit()

            assert log.status == "failed"
            assert log.sms_charge == 0
            assert log.platform_cost == 0
            db_session.refresh(landlord)
            assert landlord.sms_balance == 10
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_successful_real_send_stores_provider_message_id(self, app, db_session):
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=10)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = False
            with patch("services.sms_service.send_sms", return_value="MSGID999"):
                log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Balance due")
                db_session.commit()

            assert log.status == "delivered"
            assert log.provider_message_id == "MSGID999"
            db_session.refresh(landlord)
            assert landlord.sms_balance == 9
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_custom_sender_uses_own_api_key(self, app, db_session):
        from services.communication_service import dispatch_message

        landlord = make_landlord(db_session, sms_balance=10)
        make_settings(db_session, landlord, sms_api_key="custom-key", sms_sender_id="BRANDX", sms_connected=True)
        tenant = make_tenant(db_session, landlord)
        _reset_sms_pricing(db_session)
        db_session.commit()

        try:
            app.config["COMMS_SIMULATION_MODE"] = False
            with patch("services.sms_service.send_sms", return_value="MSGID1") as mock_send:
                log = dispatch_message(landlord_id=landlord.id, tenant=tenant, channel="sms", content="Hi")
                db_session.commit()

            assert mock_send.call_args.kwargs["api_key"] == "custom-key"
            assert mock_send.call_args.kwargs["sender_id"] == "BRANDX"
            assert log.uses_own_sender is True
            assert log.sms_charge == Decimal("0.50")  # custom_price_per_sms
        finally:
            _cleanup_landlord(db_session, landlord)


# ---------------------------------------------------------------------------
# services/sms_billing.py — resolve_sender with renamed fields
# ---------------------------------------------------------------------------

class TestResolveSender:
    def test_resolve_sender_default_when_not_connected(self, app, db_session):
        from services.sms_billing import resolve_sender

        landlord = make_landlord(db_session)
        settings = make_settings(db_session, landlord, sms_sender_id="BRANDX", sms_connected=False)

        with app.app_context():
            app.config["FLUXSMS_SENDER_ID"] = "SAHILPAY"
            sender_id, uses_own = resolve_sender(settings)
        assert sender_id == "SAHILPAY"
        assert uses_own is False

    def test_resolve_sender_custom_when_connected(self, app, db_session):
        from services.sms_billing import resolve_sender

        landlord = make_landlord(db_session)
        settings = make_settings(db_session, landlord, sms_sender_id="BRANDX", sms_connected=True)

        with app.app_context():
            sender_id, uses_own = resolve_sender(settings)
        assert sender_id == "BRANDX"
        assert uses_own is True


# ---------------------------------------------------------------------------
# routes/settings_routes.py — sms-provider connect validates the key live
# ---------------------------------------------------------------------------

class TestConnectSmsProviderValidation:
    def test_connect_rejects_bad_key(self, app, db_session):
        from flask_jwt_extended import create_access_token

        landlord = make_landlord(db_session)
        make_settings(db_session, landlord, sms_api_key="bad-key", sms_sender_id="BRANDX")
        db_session.commit()

        try:
            with app.app_context():
                token = create_access_token(identity=str(landlord.user_id))
            client = app.test_client()
            with patch("services.sms_service.check_sms_balance", return_value=None):
                resp = client.post(
                    "/api/settings/sms-provider/connect",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 400
            assert "rejected" in resp.get_json()["error"].lower()
        finally:
            _cleanup_landlord(db_session, landlord)

    def test_connect_accepts_valid_key(self, app, db_session):
        from flask_jwt_extended import create_access_token

        landlord = make_landlord(db_session)
        make_settings(db_session, landlord, sms_api_key="good-key", sms_sender_id="BRANDX")
        db_session.commit()

        try:
            with app.app_context():
                token = create_access_token(identity=str(landlord.user_id))
            client = app.test_client()
            with patch("services.sms_service.check_sms_balance", return_value=500):
                resp = client.post(
                    "/api/settings/sms-provider/connect",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.get_json()["settings"]["sms_connected"] is True
        finally:
            _cleanup_landlord(db_session, landlord)
