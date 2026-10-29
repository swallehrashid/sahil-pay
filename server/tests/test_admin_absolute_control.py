"""
The admin's word is final.

Billing automation is a convenience, not an authority: who is paying and on what
terms is a commercial conversation the system cannot see. These tests pin the
behaviour the owner asked for — when the admin sets it, it STAYS set, and a bad
value is answered with a precise message instead of
"An unexpected error occurred. Our team has been notified."

Regressions covered (all reproduced against the old code):
  * a non-ISO date raised straight out of the request -> HTTP 500
  * an admin-set status was silently rewritten by _settle_status on save
  * extending next_billing_date re-armed balance_due_since to today, so the
    account locked itself again once the grace days elapsed
  * the status dropdown offered 'cancelled', which is not a real status
  * billing_cycle 'yearly' was accepted but unknown to the pricing tables
"""

import itertools
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import User, Landlord, Subscription, SubscriptionStatus
from services import billing_service

_c = itertools.count()


def _u():
    return uuid.uuid4().hex[:6]


@pytest.fixture()
def client(app):
    return app.test_client()


def make_world(session, *, amount_due="3000", status=None, nbd=None, due_since=None):
    n = _u()
    admin = User(email=f"ac-adm{n}@t.sp", phone=f"2547{next(_c):08d}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="system_admin", totp_enabled=True, is_verified=True)
    session.add(admin)
    session.flush()
    lu = User(email=f"ac-ll{n}@t.sp", phone=f"2548{next(_c):08d}",
              password_hash=generate_password_hash("Testpass1"),
              role="landlord", is_verified=True)
    session.add(lu)
    session.flush()
    ll = Landlord(user_id=lu.id, company_name=f"AC Co {n}", currency="KES",
                  is_on_trial=False, trial_ends_at=None)
    session.add(ll)
    session.flush()
    sub = Subscription(
        landlord_id=ll.id, unit_count=5, subscription_cost=Decimal("1000"),
        status=status or SubscriptionStatus.active.value, billing_cycle="monthly",
        amount_due=Decimal(amount_due),
        next_billing_date=nbd or (date.today() - timedelta(days=20)),
        balance_due_since=due_since or (date.today() - timedelta(days=20)),
    )
    session.add(sub)
    session.commit()
    return admin, ll, sub


def ah(u):
    tok = create_access_token(identity=str(u.id), additional_claims={"role": "system_admin"})
    return {"Authorization": f"Bearer {tok}"}


def put(client, ll, admin, payload):
    return client.put(f"/api/admin/pricing/landlords/{ll.id}/billing",
                      json=payload, headers=ah(admin))


# ---------------------------------------------------------------------------
# No more 500s
# ---------------------------------------------------------------------------

def test_bad_date_is_a_clear_422_not_a_500(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"next_billing_date": "05/11/2026"})
        assert r.status_code == 422, r.status_code
        assert "next_billing_date" in r.get_json()["errors"]


def test_bad_amount_is_a_clear_422(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"amount_due": "not-a-number"})
        assert r.status_code == 422
        assert "amount_due" in r.get_json()["errors"]


def test_invalid_status_rejected_with_the_valid_list(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"status": "cancelled"})
        assert r.status_code == 422
        assert "status" in r.get_json()["errors"]


def test_legacy_yearly_cycle_is_accepted_and_normalised(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"billing_cycle": "yearly"})
        assert r.status_code == 200
        assert r.get_json()["subscription"]["billing_cycle"] == "annual"


# ---------------------------------------------------------------------------
# What the admin sets, stays set
# ---------------------------------------------------------------------------

def test_admin_status_sticks_and_is_pinned(app, client, db_session):
    admin, ll, sub = make_world(db_session, amount_due="5000")
    with app.app_context():
        r = put(client, ll, admin, {"status": "active", "amount_due": 5000})
        assert r.status_code == 200
        body = r.get_json()["subscription"]
        assert body["status"] == "active"
        assert body["admin_status_locked"] is True

        # The settler must now be a no-op, however overdue the balance is.
        fresh = db.session.get(Subscription, sub.id)
        billing_service._settle_status(fresh, date.today())
        assert fresh.status == "active", "a pinned status must never be rewritten"


def test_extending_the_due_date_actually_keeps_the_account_open(app, client, db_session):
    """The whole point: push the date out, the account opens and STAYS open."""
    admin, ll, sub = make_world(db_session, amount_due="8000")
    new_due = date.today() + timedelta(days=7)
    with app.app_context():
        # Before: overdue balance, past grace -> locked.
        landlord = db.session.get(Landlord, ll.id)
        assert billing_service.access_state(landlord)["locked"] is True

        r = put(client, ll, admin, {"next_billing_date": new_due.isoformat()})
        assert r.status_code == 200
        body = r.get_json()["subscription"]
        assert str(body["next_billing_date"])[:10] != ""
        # The overdue clock was cleared, so nothing is past grace any more.
        assert body["balance_due_since"] is None
        assert r.get_json()["access"]["locked"] is False

        # And it holds: rolling forward today must not re-charge or re-lock.
        landlord = db.session.get(Landlord, ll.id)
        billing_service.roll_forward(landlord, date.today())
        db.session.flush()
        assert billing_service.access_state(landlord)["locked"] is False
        assert db.session.get(Subscription, sub.id).next_billing_date == new_due


def test_force_open_beats_an_overdue_balance(app, client, db_session):
    admin, ll, _ = make_world(db_session, amount_due="99000")
    with app.app_context():
        r = put(client, ll, admin, {"admin_override_mode": "open",
                                    "admin_override_reason": "Paying in cash monthly"})
        assert r.status_code == 200
        assert r.get_json()["access"]["locked"] is False
        landlord = db.session.get(Landlord, ll.id)
        assert billing_service.access_state(landlord)["locked"] is False


def test_force_closed_beats_a_zero_balance_and_a_trial(app, client, db_session):
    admin, ll, _ = make_world(db_session, amount_due="0")
    with app.app_context():
        r = put(client, ll, admin, {"admin_override_mode": "closed",
                                    "admin_override_reason": "Account under review",
                                    "is_on_trial": True})
        assert r.status_code == 200
        access = r.get_json()["access"]
        assert access["locked"] is True
        assert access["reason"] == "admin_closed"


def test_force_open_requires_a_reason(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"admin_override_mode": "open"})
        assert r.status_code == 422
        assert "admin_override_reason" in r.get_json()["errors"]


def test_override_mode_can_be_handed_back_to_the_system(app, client, db_session):
    admin, ll, _ = make_world(db_session, amount_due="8000")
    with app.app_context():
        put(client, ll, admin, {"admin_override_mode": "open", "admin_override_reason": "cash"})
        r = put(client, ll, admin, {"admin_override_mode": "system"})
        assert r.status_code == 200
        assert r.get_json()["subscription"]["admin_override_mode"] is None
        # System rules apply again -> overdue balance locks it.
        assert r.get_json()["access"]["locked"] is True


def test_frozen_billing_never_charges_or_moves_the_date(app, client, db_session):
    admin, ll, sub = make_world(db_session, amount_due="0",
                                nbd=date.today() - timedelta(days=40))
    with app.app_context():
        r = put(client, ll, admin, {"admin_billing_frozen": True})
        assert r.status_code == 200
        landlord = db.session.get(Landlord, ll.id)
        added = billing_service.roll_forward(landlord, date.today())
        assert added == 0, "a frozen account must never be auto-charged"
        fresh = db.session.get(Subscription, sub.id)
        assert fresh.amount_due == Decimal("0.00")
        assert fresh.next_billing_date == date.today() - timedelta(days=40)


def test_trial_toggled_on_without_a_date_gets_one(app, client, db_session):
    admin, ll, _ = make_world(db_session)
    with app.app_context():
        r = put(client, ll, admin, {"is_on_trial": True})
        assert r.status_code == 200
        landlord = db.session.get(Landlord, ll.id)
        assert landlord.is_on_trial is True
        assert landlord.trial_ends_at is not None
        # A real trial means the portal is open and nothing is charged.
        assert billing_service.access_state(landlord)["locked"] is False


def test_trial_date_set_as_plain_date_does_not_break_access(app, client, db_session):
    """trial_ends_at is a DateTime column; an admin sends a plain YYYY-MM-DD."""
    admin, ll, _ = make_world(db_session)
    future = (date.today() + timedelta(days=15)).isoformat()
    with app.app_context():
        r = put(client, ll, admin, {"is_on_trial": True, "trial_ends_at": future})
        assert r.status_code == 200
        assert r.get_json()["access"]["locked"] is False
        landlord = db.session.get(Landlord, ll.id)
        assert billing_service.roll_forward(landlord, date.today()) == 0
