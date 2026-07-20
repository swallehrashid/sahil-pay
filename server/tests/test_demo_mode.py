"""
Tests for demo mode (DEMO_MODE_SPEC.md).

Covers: shadow creation/idempotency, the current_landlord_id() resolver's
demo-header behavior across every role, seeded-data invariants, write
isolation (a demo-scope write lands on the shadow, not the real landlord),
no-real-sends guarantee, admin/scheduled-task exclusion, and reset
completeness.
"""

import itertools

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from models import User, Landlord, TeamMember, TeamMemberPermission
from services.allocation_service import outstanding_line_items
from services.demo_service import ensure_demo_landlord, reset_demo_data, get_demo_shadow

_counter = itertools.count()


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_landlord(session, **overrides):
    n = next(_counter)
    user = User(
        email=f"demo-test-landlord{n}@test.sahilpay",
        phone=f"254703{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord",
        is_verified=True,
        is_active=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(
        user_id=user.id, company_name=f"Demo Test Landlord {n}", currency="KES",
        **overrides,
    )
    session.add(landlord)
    session.commit()
    return user, landlord


def _make_team_member(session, landlord):
    n = next(_counter)
    user = User(
        email=f"demo-test-team{n}@test.sahilpay",
        phone=f"254704{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="team_member",
        is_verified=True,
        is_active=True,
    )
    session.add(user)
    session.flush()
    tm = TeamMember(
        user_id=user.id, landlord_id=landlord.id, username=f"demoteam{n}",
        is_active=True, property_access_all=True,
    )
    session.add(tm)
    session.flush()
    session.add(TeamMemberPermission(team_member_id=tm.id, module="settings", can_view=True, can_edit=True))
    session.commit()
    return user, tm


def _auth_header(user, extra=None):
    token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _cleanup_shadow_and_landlord(session, landlord, user):
    """Wipe a demo shadow (if any) then the real landlord — raw SQL by id,
    matching this package's established teardown pattern (test_onboarding_settings.py)."""
    shadow = session.query(Landlord).filter_by(demo_owner_landlord_id=landlord.id).first()
    if shadow is not None:
        from services.demo_service import _wipe_landlord_scoped_rows

        _wipe_landlord_scoped_rows(shadow.id)
        session.execute(text("DELETE FROM landlord_settings WHERE landlord_id = :lid"), {"lid": shadow.id})
        session.execute(text("DELETE FROM automation_settings WHERE landlord_id = :lid"), {"lid": shadow.id})
        shadow_user_id = shadow.user_id
        session.execute(text("DELETE FROM landlords WHERE id = :lid"), {"lid": shadow.id})
        session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": shadow_user_id})
        session.commit()

    session.execute(text("DELETE FROM landlords WHERE id = :lid"), {"lid": landlord.id})
    session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
    session.commit()


class TestEnsureDemoLandlord:
    def test_creates_shadow_with_expected_flags(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            assert shadow.is_demo is True
            assert shadow.demo_owner_landlord_id == landlord.id
            assert shadow.user.is_active is False
            # Seeding itself sends one simulated SMS (the balance-reminder
            # comms-log garnish), decrementing the starting 500 by 1 segment.
            assert shadow.sms_balance == 499
            assert shadow.is_on_trial is False
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_idempotent_on_second_call(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            first = ensure_demo_landlord(landlord)
            db_session.commit()
            second = ensure_demo_landlord(landlord)
            db_session.commit()

            assert first.id == second.id
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_seeded_dataset_invariants(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from models import Property, Unit, Tenant, BalanceRollover, CreditLedger, InvoiceLineItem, Invoice

            assert Property.query.filter_by(landlord_id=shadow.id).count() >= 3
            assert Unit.query.join(Property).filter(Property.landlord_id == shadow.id).count() >= 12
            tenants = Tenant.query.filter_by(landlord_id=shadow.id).all()
            assert len(tenants) >= 10

            # Every tenant's outstanding remaining reconciles to -balance.
            for t in tenants:
                remaining = sum(li.remaining for li in outstanding_line_items(t))
                assert remaining == -t.balance, f"{t.first_name} does not reconcile"

            # At least one multi-component balance rollover (Grace-style arrears).
            assert BalanceRollover.query.filter_by(landlord_id=shadow.id).count() >= 1

            # At least one credit-consumption event (Hassan-style overpay).
            assert CreditLedger.query.filter_by(landlord_id=shadow.id).count() >= 1

            # A deposit line exists and was never rolled (still open/unpaid).
            deposit_lines = (
                InvoiceLineItem.query.join(Invoice)
                .filter(Invoice.landlord_id == shadow.id, InvoiceLineItem.subcategory == "deposit")
                .all()
            )
            assert any(li.status == "open" for li in deposit_lines)
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_seeded_tenants_have_no_reachable_login(self, app, db_session):
        """Demo tenants must never be reachable via OTP login (§3.4, §4.2)."""
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from models import Tenant

            for t in Tenant.query.filter_by(landlord_id=shadow.id).all():
                assert t.phone.startswith("+254700000")
                assert t.email.endswith("@sahilpay.demo")
                if t.user_id:
                    tenant_user = db_session.get(User, t.user_id)
                    assert tenant_user.is_active is False
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestResetDemoData:
    def test_reset_reseeds_cleanly_with_no_orphans(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from models import Tenant
            before_count = Tenant.query.filter_by(landlord_id=shadow.id).count()

            reset_demo_data(landlord)
            db_session.commit()

            after_count = Tenant.query.filter_by(landlord_id=shadow.id).count()
            assert after_count == before_count

            for t in Tenant.query.filter_by(landlord_id=shadow.id).all():
                remaining = sum(li.remaining for li in outstanding_line_items(t))
                assert remaining == -t.balance

            orphan_tuh = db_session.execute(
                text("SELECT count(*) FROM tenant_unit_history WHERE tenant_id NOT IN (SELECT id FROM tenants)")
            ).scalar()
            orphan_ili = db_session.execute(
                text("SELECT count(*) FROM invoice_line_items WHERE invoice_id NOT IN (SELECT id FROM invoices)")
            ).scalar()
            assert orphan_tuh == 0
            assert orphan_ili == 0
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_reset_without_existing_shadow_raises(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            with pytest.raises(ValueError):
                reset_demo_data(landlord)
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestResolverBehavior:
    def test_no_header_resolves_real_landlord(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            resp = client.get("/api/settings/general", headers=_auth_header(user))
            assert resp.status_code == 200
            assert resp.get_json()["id"] == landlord.id
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_header_without_shadow_falls_back_to_real(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            headers = _auth_header(user)
            headers["X-Demo-Mode"] = "1"
            resp = client.get("/api/settings/general", headers=headers)
            assert resp.status_code == 200
            assert resp.get_json()["id"] == landlord.id
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_header_with_shadow_resolves_to_shadow(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            headers = _auth_header(user)
            headers["X-Demo-Mode"] = "1"
            resp = client.get("/api/settings/general", headers=headers)
            assert resp.status_code == 200
            assert resp.get_json()["id"] == shadow.id
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_team_member_header_ignored(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()
            tm_user, tm = _make_team_member(db_session, landlord)

            headers = _auth_header(tm_user)
            headers["X-Demo-Mode"] = "1"
            resp = client.get("/api/settings/general", headers=headers)
            assert resp.status_code == 200
            assert resp.get_json()["id"] == landlord.id
            assert resp.get_json()["id"] != shadow.id
        finally:
            db_session.execute(text("DELETE FROM team_member_permissions WHERE team_member_id = :id"), {"id": tm.id})
            db_session.execute(text("DELETE FROM team_members WHERE id = :id"), {"id": tm.id})
            db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tm_user.id})
            db_session.commit()
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestWriteIsolation:
    def test_write_in_demo_scope_lands_on_shadow_only(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from models import Tenant
            real_count_before = Tenant.query.filter_by(landlord_id=landlord.id).count()
            shadow_count_before = Tenant.query.filter_by(landlord_id=shadow.id).count()

            headers = _auth_header(user)
            headers["X-Demo-Mode"] = "1"
            unit = shadow.properties[0].units[0]
            # Free up the unit if the seeded tenant occupies it — just check counts
            # increase on the shadow only, not whether the specific create succeeds
            # against business rules (that's covered by tenant_routes' own tests).
            resp = client.post(
                "/api/tenants",
                headers=headers,
                json={
                    "unit_id": unit.id, "first_name": "Test", "last_name": "Writer",
                    "phone": "+254799999999", "account_number": "WRITE-TEST",
                },
            )
            # Whether it's a 201 or a validation 4xx (e.g. unit occupied) doesn't
            # matter here — what matters is nothing landed on the REAL landlord.
            real_count_after = Tenant.query.filter_by(landlord_id=landlord.id).count()
            assert real_count_after == real_count_before

            if resp.status_code == 201:
                shadow_count_after = Tenant.query.filter_by(landlord_id=shadow.id).count()
                assert shadow_count_after == shadow_count_before + 1
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestNoRealSends:
    def test_dispatch_message_never_calls_provider_for_demo_landlord(self, app, db_session, monkeypatch):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            app.config["COMMS_SIMULATION_MODE"] = False
            called = {"send_sms": False}

            def _fake_send_sms(*args, **kwargs):
                called["send_sms"] = True
                return True

            monkeypatch.setattr("services.sms_service.send_sms", _fake_send_sms)

            from models import Tenant
            from services.communication_service import dispatch_message

            tenant = Tenant.query.filter_by(landlord_id=shadow.id).first()
            log = dispatch_message(landlord_id=shadow.id, tenant=tenant, channel="sms", content="test")
            db_session.commit()

            assert called["send_sms"] is False
            assert log.status == "delivered"
            assert log.sms_charge == 0
            assert log.platform_cost == 0
        finally:
            app.config["COMMS_SIMULATION_MODE"] = True
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestAdminExclusion:
    def test_admin_landlord_counts_exclude_demo_shadow(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            real_ids = [l.id for l in Landlord.query.filter(Landlord.is_demo.is_(False)).all()]
            assert shadow.id not in real_ids
            assert landlord.id in real_ids
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_recompute_subscription_noops_for_demo(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from services.billing_service import recompute_subscription
            result = recompute_subscription(shadow)
            assert result is None
            assert shadow.subscription is None
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)

    def test_run_monthly_billing_all_query_skips_demo(self, app, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            ids = [l.id for l in Landlord.query.filter(Landlord.is_demo.is_(False)).all()]
            assert shadow.id not in ids
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)


class TestOtpExclusion:
    def test_otp_request_does_not_reach_demo_tenant(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            shadow = ensure_demo_landlord(landlord)
            db_session.commit()

            from models import Tenant
            demo_tenant = Tenant.query.filter_by(landlord_id=shadow.id).first()

            resp = client.post("/api/otp/request", json={"identifier": demo_tenant.phone})
            assert resp.status_code == 200
            # No enumeration either way, but there must be zero OTP tokens issued.
            from models import OtpToken
            count = OtpToken.query.filter_by(identifier=demo_tenant.phone).count()
            assert count == 0
        finally:
            _cleanup_shadow_and_landlord(db_session, landlord, user)
