"""
Phase 10 — demo mode must never look like real platform activity.

Demo data deliberately lives in the real database under a hidden "shadow"
landlord (DEMO_MODE_SPEC.md §2), which keeps it production-realistic. The cost
is that every action taken while practising writes a real audit row — and the
demo seed drives the billing engine, so those rows show invoices issued by
"platform" for tenants nobody created.

Left unfiltered in the admin's master audit log, that is indistinguishable from
a breach. These tests pin the filtering shut.
"""

import uuid

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    AuditLog, Landlord, LandlordSettings, SystemAdmin, User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def demo_world(app, db_session):
    """A real landlord, their demo shadow, and an audit row against each."""
    s = db_session
    n = _uniq()

    real_user = User(
        email=f"demo-real-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    s.add(real_user)
    s.flush()
    real = Landlord(user_id=real_user.id, company_name=f"Real {n}", currency="KES")
    s.add(real)
    s.flush()
    s.add(LandlordSettings(landlord_id=real.id))
    s.flush()

    shadow_user = User(
        email=f"demo+{n}@sahilpay.demo", role="landlord",
        password_hash=generate_password_hash("x"), is_verified=True, is_active=False,
    )
    s.add(shadow_user)
    s.flush()
    shadow = Landlord(
        user_id=shadow_user.id, company_name=f"Real {n} (Demo)", currency="KES",
        is_demo=True, demo_owner_landlord_id=real.id,
    )
    s.add(shadow)
    s.flush()

    admin_user = User(
        email=f"demo-admin-{n}@test.sahilpay", phone=f"2548{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", is_verified=True, is_active=True,
        # Admin routes require an active second factor (spec 3.4), so a test
        # admin must be enrolled exactly like a real one.
        totp_enabled=True,
    )
    s.add(admin_user)
    s.flush()
    s.add(SystemAdmin(user_id=admin_user.id, first_name="Demo", last_name="Admin"))
    s.flush()

    s.add(AuditLog(
        actor_user_id=real_user.id, landlord_id=real.id, action="create_tenant",
        entity_type="tenant", entity_id=1, description=f"REAL-ROW-{n}",
    ))
    s.add(AuditLog(
        actor_user_id=shadow_user.id, landlord_id=shadow.id, action="create_invoice",
        entity_type="invoice", entity_id=2, description=f"[DEMO] DEMO-ROW-{n}",
    ))
    s.commit()

    with app.app_context():
        token = create_access_token(
            identity=str(admin_user.id), additional_claims={"role": "system_admin"}
        )

    return {"real": real, "shadow": shadow, "token": token, "n": n}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_master_audit_log_hides_demo_rows(client, demo_world):
    """The reported symptom: demo invoices appearing as platform activity."""
    resp = client.get(
        "/api/admin/audit?per_page=100", headers=_auth(demo_world["token"])
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    blob = str(resp.get_json())

    assert f"REAL-ROW-{demo_world['n']}" in blob, "real activity must still show"
    assert f"DEMO-ROW-{demo_world['n']}" not in blob, (
        "a demo-mode audit row surfaced in the admin master log — this is what "
        "made a practice session look like a breach"
    )


def test_support_can_still_opt_into_demo_rows(client, demo_world):
    """Hidden by default, but reachable when support explicitly asks."""
    resp = client.get(
        "/api/admin/audit?per_page=100&include_demo=true",
        headers=_auth(demo_world["token"]),
    )
    assert resp.status_code == 200
    assert f"DEMO-ROW-{demo_world['n']}" in str(resp.get_json())


def test_admin_landlord_list_excludes_demo_shadows(client, demo_world):
    # Search by this fixture's unique suffix so the assertion is about THESE two
    # landlords, not whatever else the shared test database happens to hold.
    resp = client.get(
        f"/api/admin/landlords?per_page=100&search={demo_world['n']}",
        headers=_auth(demo_world["token"]),
    )
    assert resp.status_code == 200
    blob = str(resp.get_json())
    assert demo_world["real"].company_name in blob, "the real landlord must be listed"
    assert "(Demo)" not in blob, "a demo shadow appeared in the admin landlord list"


def test_trial_expiry_skips_demo_shadows(db_session, demo_world):
    """A shadow is scaffolding, not a customer — it is never billed or expired."""
    from datetime import datetime, timedelta

    from services.trial_service import expire_due_trials

    shadow = demo_world["shadow"]
    shadow.is_on_trial = True
    shadow.trial_ends_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()

    result = expire_due_trials()
    assert shadow.id not in result.get("landlord_ids", []), (
        "the demo shadow was processed by trial expiry"
    )
    assert shadow.is_on_trial is True


def test_monthly_billing_skips_demo_shadows(demo_world):
    """Demo data must not churn overnight — it only changes via demo/reset."""
    import inspect

    from tasks.invoice_tasks import run_monthly_billing_all

    source = inspect.getsource(run_monthly_billing_all)
    assert "is_demo" in source, (
        "run_monthly_billing_all no longer filters demo landlords"
    )
