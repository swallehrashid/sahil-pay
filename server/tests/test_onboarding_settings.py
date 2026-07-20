"""
Route-level tests for GET/PUT /api/settings/onboarding
(ONBOARDING_TUTORIALS_SPEC.md §4.6).

Unlike the service-level tests in this package, these exercise the real
Flask route, which calls db.session.commit() internally (mirroring every
other settings_routes.py handler) — so fixtures here commit their setup
data and delete it again at teardown via raw SQL (by primary key) rather
than ORM session.delete(): the Flask test client processes each request in
its own app-context-scoped session, and by the time control returns to the
test, this test's own Session object can no longer see that row as
"attached" for an ORM-tracked delete, even though the row is (correctly)
still there — raw SQL sidesteps that entirely.
"""

import itertools

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from models import User, Landlord, TeamMember, TeamMemberPermission

_counter = itertools.count()


@pytest.fixture()
def client(app):
    return app.test_client()


def _make_landlord(session, **overrides):
    n = next(_counter)
    user = User(
        email=f"onboard-landlord{n}@test.sahilpay",
        phone=f"254701{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord",
        is_verified=True,
    )
    session.add(user)
    session.flush()

    landlord = Landlord(
        user_id=user.id, company_name=f"Onboarding Test Landlord {n}", currency="KES",
        **overrides,
    )
    session.add(landlord)
    session.commit()
    return user, landlord


def _make_team_member(session, landlord, module_permissions=None):
    """module_permissions=None → default full 'settings' access. Pass an
    explicit (possibly empty) list to control exactly which rows exist."""
    n = next(_counter)
    user = User(
        email=f"onboard-team{n}@test.sahilpay",
        phone=f"254702{n:06d}",
        password_hash=generate_password_hash("Testpass1"),
        role="team_member",
        is_verified=True,
    )
    session.add(user)
    session.flush()

    tm = TeamMember(
        user_id=user.id, landlord_id=landlord.id, username=f"team{n}",
        is_active=True, property_access_all=True,
    )
    session.add(tm)
    session.flush()

    perms = [("settings", True, True)] if module_permissions is None else module_permissions
    for module, view, edit in perms:
        session.add(TeamMemberPermission(
            team_member_id=tm.id, module=module, can_view=view, can_edit=edit,
        ))
    session.commit()
    return user, tm


def _auth_header(user):
    token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _delete_by_id(session, table, row_id):
    session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})


def _cleanup_landlord(session, landlord, user):
    _delete_by_id(session, "landlords", landlord.id)
    _delete_by_id(session, "users", user.id)
    session.commit()


def _cleanup_team_member(session, tm, tm_user):
    session.execute(text("DELETE FROM team_member_permissions WHERE team_member_id = :id"), {"id": tm.id})
    _delete_by_id(session, "team_members", tm.id)
    _delete_by_id(session, "users", tm_user.id)
    session.commit()


class TestOnboardingSettingsGet:
    def test_fresh_landlord_has_null_state_and_zero_counts(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            resp = client.get("/api/settings/onboarding", headers=_auth_header(user))
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["state"] is None
            assert body["counts"] == {
                "properties": 0, "units": 0, "tenants": 0,
                "invoices": 0, "payments": 0, "charge_categories": 0,
            }
        finally:
            _cleanup_landlord(db_session, landlord, user)

    def test_counts_reflect_seeded_entities(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        db_session.execute(
            text(
                "INSERT INTO properties (landlord_id, name, number_of_units, city, is_deleted, tax_rate, created_at, updated_at) "
                "VALUES (:lid, 'Test Property', 1, 'Nairobi', false, 7.50, now(), now()) RETURNING id"
            ),
            {"lid": landlord.id},
        )
        prop_id = db_session.execute(
            text("SELECT id FROM properties WHERE landlord_id = :lid"), {"lid": landlord.id},
        ).scalar()
        db_session.execute(
            text(
                "INSERT INTO units (property_id, name, rent_amount, is_occupied, is_deleted, created_at, updated_at) "
                "VALUES (:pid, 'A1', 10000, false, false, now(), now())"
            ),
            {"pid": prop_id},
        )
        db_session.execute(
            text(
                "INSERT INTO charge_categories (landlord_id, name, kind, is_metered, auto_bill_monthly, is_default, is_active, created_at, updated_at) "
                "VALUES (:lid, 'Rent', 'invoice', false, false, false, true, now(), now())"
            ),
            {"lid": landlord.id},
        )
        db_session.commit()

        try:
            resp = client.get("/api/settings/onboarding", headers=_auth_header(user))
            assert resp.status_code == 200
            counts = resp.get_json()["counts"]
            assert counts["properties"] == 1
            assert counts["units"] == 1
            assert counts["charge_categories"] == 1
            assert counts["tenants"] == 0
        finally:
            db_session.execute(text("DELETE FROM charge_categories WHERE landlord_id = :lid"), {"lid": landlord.id})
            db_session.execute(text("DELETE FROM units WHERE property_id = :pid"), {"pid": prop_id})
            db_session.execute(text("DELETE FROM properties WHERE id = :pid"), {"pid": prop_id})
            db_session.commit()
            _cleanup_landlord(db_session, landlord, user)


class TestOnboardingSettingsPut:
    def test_put_stores_and_get_round_trips(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            state = {
                "version": 1,
                "welcome_seen_at": "2026-07-08T10:00:00Z",
                "checklist_dismissed_at": None,
                "tutorials": {"create-property": {"status": "completed", "at": "2026-07-08T10:05:00Z"}},
            }
            put_resp = client.put(
                "/api/settings/onboarding", headers=_auth_header(user), json=state,
            )
            assert put_resp.status_code == 200
            assert put_resp.get_json()["state"] == state

            get_resp = client.get("/api/settings/onboarding", headers=_auth_header(user))
            assert get_resp.get_json()["state"] == state
        finally:
            _cleanup_landlord(db_session, landlord, user)

    def test_put_rejects_non_object_payload(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            resp = client.put(
                "/api/settings/onboarding", headers=_auth_header(user), json=[1, 2, 3],
            )
            assert resp.status_code == 400
        finally:
            _cleanup_landlord(db_session, landlord, user)

    def test_put_rejects_oversized_payload(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        try:
            oversized = {"blob": "x" * 9000}
            resp = client.put(
                "/api/settings/onboarding", headers=_auth_header(user), json=oversized,
            )
            assert resp.status_code == 400
        finally:
            _cleanup_landlord(db_session, landlord, user)

    def test_put_as_team_member_is_forbidden(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        tm_user, tm = _make_team_member(db_session, landlord)
        try:
            resp = client.put(
                "/api/settings/onboarding", headers=_auth_header(tm_user),
                json={"version": 1},
            )
            assert resp.status_code == 403
        finally:
            _cleanup_team_member(db_session, tm, tm_user)
            _cleanup_landlord(db_session, landlord, user)

    def test_get_as_team_member_without_settings_permission_is_forbidden(self, app, client, db_session):
        user, landlord = _make_landlord(db_session)
        tm_user, tm = _make_team_member(db_session, landlord, module_permissions=[])
        try:
            resp = client.get("/api/settings/onboarding", headers=_auth_header(tm_user))
            assert resp.status_code == 403
        finally:
            _cleanup_team_member(db_session, tm, tm_user)
            _cleanup_landlord(db_session, landlord, user)
