"""
The three permission modules that did not exist: notifications, leases, penalties.

Each area used to borrow a module that meant something else, and each borrowed
one produced a wrong answer in practice:

  notifications  had no module at all, and /notifications/send refused every
                 team member by ROLE. A secretary with a complete permission
                 matrix still could not send one — the reported "team members'
                 notifications are not active despite having permissions".
  leases         rode on `tenants`, so you could not let anyone read a tenancy
                 agreement without also granting edit over tenant records.
  penalties      rode on `invoices` and `reports`, and the penalty POLICY rode
                 on `properties` — so whoever could rename a block could also
                 change what its tenants were fined.

These tests pin the new gates AND the negative cases, because a permission
change that only proves the "yes" path is how a permission becomes a formality.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from models import (
    Landlord, LandlordSettings, Property, TeamMember, TeamMemberPermission,
    TeamMemberPropertyAccess, Tenant, Unit, User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def world(app, db_session):
    """A landlord with two blocks, a tenant in each, and no team members yet."""
    s = db_session
    n = _uniq()

    owner = User(email=f"pm-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Perm {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.flush()

    props, tenants = [], []
    for index in range(2):
        prop = Property(landlord_id=landlord.id, name=f"Block {index} {n}",
                        city="Nairobi", street_name="Ngong Road")
        s.add(prop)
        s.flush()
        unit = Unit(property_id=prop.id, name=f"U{index}{n[:3]}",
                    rent_amount=Decimal("25000"))
        s.add(unit)
        s.flush()
        tenant_user = User(email=f"pt{index}-{n}@test.sahilpay",
                           phone=f"2541{index}{n[:6]}",
                           password_hash=generate_password_hash("Testpass1"),
                           role="tenant", is_verified=True, is_active=True)
        s.add(tenant_user)
        s.flush()
        tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id,
                        user_id=tenant_user.id,
                        first_name=f"Ten{index}", last_name=n[:4],
                        phone=f"25470{index}{n[:6]}",
                        email=f"pten{index}-{n}@test.sahilpay",
                        account_number=f"P{index}{n}", national_id=f"ID{n}{index}",
                        deposit_amount=Decimal("25000"),
                        lease_start_date=date(2026, 1, 1),
                        lease_expiry_date=date(2026, 12, 31),
                        balance=Decimal("0"))
        s.add(tenant)
        s.flush()
        props.append(prop)
        tenants.append(tenant)

    return {"landlord": landlord, "properties": props, "tenants": tenants,
            "n": n, "session": s}


def _member(app, world, modules, *, scoped_to=None):
    """
    A team member holding exactly *modules* — a dict of
    {module: (can_view, can_edit)} — and optionally restricted to one property.
    """
    s = world["session"]
    n = _uniq()

    user = User(email=f"tm-{n}@test.sahilpay", phone=f"2546{n[:7]}",
                password_hash=generate_password_hash("Testpass1"),
                role="team_member", is_verified=True, is_active=True)
    s.add(user)
    s.flush()

    member = TeamMember(user_id=user.id, landlord_id=world["landlord"].id,
                        username=f"tm{n}", is_active=True,
                        property_access_all=scoped_to is None)
    s.add(member)
    s.flush()

    if scoped_to is not None:
        s.add(TeamMemberPropertyAccess(team_member_id=member.id,
                                       property_id=scoped_to.id))
    for module, (can_view, can_edit) in modules.items():
        s.add(TeamMemberPermission(team_member_id=member.id, module=module,
                                   can_view=can_view, can_edit=can_edit))
    s.flush()

    with app.app_context():
        token = create_access_token(
            identity=str(user.id),
            additional_claims={"role": "team_member",
                               "landlord_id": world["landlord"].id,
                               "team_member_id": member.id})
    return member, {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------

def test_member_with_notifications_edit_can_send(client, app, world):
    """The headline fix: this used to be a flat 403 for every team member."""
    _, headers = _member(app, world, {"notifications": (True, True)})

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "user", "target_type": "tenant",
        "target_id": world["tenants"][0].id,
        "title": "Water shutoff", "body": "Mains work Tuesday 9am-2pm.",
    })

    assert response.status_code == 201
    assert response.get_json()["recipient_count"] == 1


def test_view_only_member_cannot_send(client, app, world):
    """
    A caretaker should receive notices, not broadcast them. If view were enough,
    the module would grant nothing meaningful.
    """
    _, headers = _member(app, world, {"notifications": (True, False)})

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "user", "target_type": "tenant",
        "target_id": world["tenants"][0].id,
        "title": "Nope", "body": "Should not send.",
    })

    assert response.status_code == 403


def test_member_without_the_module_cannot_send(client, app, world):
    _, headers = _member(app, world, {"tenants": (True, True)})

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "user", "target_type": "tenant",
        "target_id": world["tenants"][0].id,
        "title": "Nope", "body": "Should not send.",
    })

    assert response.status_code == 403


def test_a_scoped_member_cannot_broadcast_to_another_block(client, app, world):
    """
    Holding notifications:edit is permission to send, not permission to send to
    everyone. A caretaker for Block 0 must not reach Block 1's tenants by
    passing its property id.
    """
    _, headers = _member(app, world, {"notifications": (True, True)},
                         scoped_to=world["properties"][0])

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "property_tenants",
        "target_id": world["properties"][1].id,
        "title": "Leak", "body": "Not your block.",
    })

    assert response.status_code == 403


def test_all_tenants_means_all_tenants_this_member_can_see(client, app, world):
    """
    "All tenants" for a block-scoped member is their block, not the whole
    account — otherwise property scoping is bypassed by choosing a wider
    audience.
    """
    _, headers = _member(app, world, {"notifications": (True, True)},
                         scoped_to=world["properties"][0])

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "all_tenants", "title": "Notice", "body": "Block only.",
    })

    assert response.status_code == 201
    # Two tenants exist on the account; only the one in their block is reached.
    assert response.get_json()["recipient_count"] == 1


def test_a_member_cannot_notify_another_landlords_tenant(client, app, db_session, world):
    """
    Granting the new module must not have widened the blast radius: reaching
    across accounts stays impossible however complete the matrix is.
    """
    s = db_session
    n = _uniq()

    other_user = User(email=f"other-{n}@test.sahilpay", phone=f"2545{n[:7]}",
                      password_hash=generate_password_hash("Testpass1"),
                      role="landlord", is_verified=True, is_active=True)
    s.add(other_user)
    s.flush()
    other = Landlord(user_id=other_user.id, company_name=f"Other {n}", currency="KES")
    s.add(other)
    s.flush()
    prop = Property(landlord_id=other.id, name=f"Foreign {n}",
                    city="Mombasa", street_name="Moi Avenue")
    s.add(prop)
    s.flush()
    unit = Unit(property_id=prop.id, name=f"F{n[:3]}", rent_amount=Decimal("1000"))
    s.add(unit)
    s.flush()
    foreign_tenant = Tenant(landlord_id=other.id, unit_id=unit.id,
                            first_name="Foreign", last_name=n[:4],
                            phone=f"2544{n[:6]}", account_number=f"X{n}",
                            balance=Decimal("0"))
    s.add(foreign_tenant)
    s.flush()

    _, headers = _member(app, world, {"notifications": (True, True)})

    response = client.post("/api/notifications/send", headers=headers, json={
        "audience": "user", "target_type": "tenant",
        "target_id": foreign_tenant.id,
        "title": "Leak", "body": "Wrong account.",
    })

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# leases — no longer gated on `tenants`
# ---------------------------------------------------------------------------

def test_leases_need_the_leases_module_not_tenants(client, app, world):
    """Full tenant rights must no longer imply access to tenancy agreements."""
    _, headers = _member(app, world, {"tenants": (True, True)})

    assert client.get("/api/leases", headers=headers).status_code == 403


def test_the_leases_module_grants_leases(client, app, world):
    _, headers = _member(app, world, {"leases": (True, False)})

    assert client.get("/api/leases", headers=headers).status_code == 200


# ---------------------------------------------------------------------------
# penalties — no longer gated on invoices / reports / properties
# ---------------------------------------------------------------------------

def test_penalties_need_the_penalties_module(client, app, world):
    _, headers = _member(app, world, {"invoices": (True, True), "reports": (True, True)})

    assert client.get("/api/penalties/preview", headers=headers).status_code == 403


def test_the_penalties_module_grants_the_preview(client, app, world):
    _, headers = _member(app, world, {"penalties": (True, False)})

    assert client.get("/api/penalties/preview", headers=headers).status_code == 200


def test_changing_a_penalty_policy_is_not_a_property_permission(client, app, world):
    """
    Setting what a block's tenants are fined used to require properties:edit,
    so anyone who could rename the block could also change its penalty rules.
    """
    _, headers = _member(app, world, {"properties": (True, True)})

    response = client.put(
        f"/api/properties/{world['properties'][0].id}/penalty-policy",
        headers=headers, json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
              "trigger_type": "day_of_month", "trigger_day": 5},
    )

    assert response.status_code == 403


def test_penalties_edit_can_change_the_policy(client, app, world):
    _, headers = _member(app, world, {"penalties": (True, True)})

    response = client.put(
        f"/api/properties/{world['properties'][0].id}/penalty-policy",
        headers=headers, json={"is_enabled": True, "mode": "fixed", "fixed_amount": 500,
              "trigger_type": "day_of_month", "trigger_day": 5},
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# The caretaker could not record a meter reading
# ---------------------------------------------------------------------------
# Nothing refused the WRITE — /api/utilities/ accepted it. What failed was
# filling the form in: the page loads a property list and a utility-category
# list first, and a caretaker could reach neither. So the reported "the
# caretaker cannot add utilities" was two missing READ permissions, which is
# why it looked like the feature was broken rather than like a permission.

def test_a_caretaker_can_load_the_utility_category_dropdown(client, app, world):
    """
    /charge-categories carried @require_permission("invoices","view") AND an
    inner check that picked the module from ?kind=. The decorator ran first and
    refused, making the inner rule dead code — so the Water/Electricity dropdown
    was empty for the one role whose whole job is meter readings.
    """
    _, headers = _member(app, world, {"utilities": (True, True)},
                         scoped_to=world["properties"][0])

    response = client.get("/api/charge-categories/?kind=utility", headers=headers)

    assert response.status_code == 200


def test_utilities_permission_does_not_open_the_invoice_catalogue(client, app, world):
    """Removing the decorator must not have widened the endpoint."""
    _, headers = _member(app, world, {"utilities": (True, True)},
                         scoped_to=world["properties"][0])

    response = client.get("/api/charge-categories/?kind=invoice", headers=headers)

    assert response.status_code == 403


def test_the_caretaker_preset_grants_what_the_utilities_page_needs(app):
    """
    A preset that grants edit on a page whose form cannot be filled in is not a
    working grant. Pin the full set the page actually loads.
    """
    from services.team_preset_service import permission_rows_for

    granted = {row["module"]: row for row in permission_rows_for("caretaker")}

    assert granted["utilities"]["can_edit"] is True
    # ...and the reads the form depends on:
    assert granted["properties"]["can_view"] is True
    assert granted["units"]["can_view"] is True
    # Still not a licence to bill anyone — raising invoices stays elsewhere.
    assert "invoices" not in granted


def test_a_caretaker_still_cannot_generate_invoices(client, app, world):
    """
    Recording consumption and charging for it are different jobs. The caretaker
    reads meters; somebody else turns that into money.
    """
    _, headers = _member(app, world, {"utilities": (True, True), "properties": (True, False)},
                         scoped_to=world["properties"][0])

    response = client.post("/api/utilities/bulk-upload/generate-invoices",
                           headers=headers, json={"reading_month": "2026-08"})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# An accountant records and edits payments
# ---------------------------------------------------------------------------

def test_payments_edit_lets_a_member_record_and_amend_a_payment(client, app, world):
    """
    "If it's edit, you can do anything on the page" — for the payments module
    that means creating one and correcting it afterwards, all of it attributed
    in the audit trail.
    """
    _, headers = _member(app, world, {"payments": (True, True), "tenants": (True, False)})

    created = client.post("/api/payments/", headers=headers, json={
        "tenant_id": world["tenants"][0].id, "amount": 1500,
        "payment_date": str(date(2026, 8, 5)),
        "payment_method": "cash", "source": "manual", "allocations": [],
    })
    assert created.status_code == 201

    payment_id = created.get_json()["id"]
    amended = client.put(f"/api/payments/{payment_id}", headers=headers,
                         json={"notes": "corrected reference"})
    assert amended.status_code == 200


def test_payments_view_only_cannot_record_a_payment(client, app, world):
    _, headers = _member(app, world, {"payments": (True, False), "tenants": (True, False)})

    response = client.post("/api/payments/", headers=headers, json={
        "tenant_id": world["tenants"][0].id, "amount": 1500,
        "payment_date": str(date(2026, 8, 5)),
        "payment_method": "cash", "source": "manual", "allocations": [],
    })

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Maintenance: the tenant's photo has to survive the whole trip
# ---------------------------------------------------------------------------

def test_a_portal_request_records_the_landlord_from_the_tenant_row(client, app, db_session, world):
    """
    _get_portal_tenant() took landlord_id from the JWT CLAIM. A token issued
    without it — or carrying a stale one — produced landlord_id=None, which did
    not fail loudly: it flowed into the insert and hit a NOT NULL violation that
    reached the tenant as a generic "record already exists" 409, after the photo
    had already been stored under a path containing the literal string "None".
    The tenant row knows its own landlord, so that is where it now comes from.
    """
    from flask_jwt_extended import create_access_token

    tenant = world["tenants"][0]
    with app.app_context():
        # Deliberately omit landlord_id — the shape that used to break.
        token = create_access_token(identity=str(tenant.user_id),
                                    additional_claims={"role": "tenant",
                                                       "tenant_id": tenant.id})

    response = client.post("/api/portal/maintenance",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"summary": "Ceiling leak", "category": "plumbing"})

    assert response.status_code == 201
    from models import MaintenanceRequest
    created = db_session.get(MaintenanceRequest,
                             response.get_json()["request"]["id"])
    assert created.landlord_id == world["landlord"].id


def test_the_office_list_carries_the_photo_and_who_reported_it(client, app, db_session, world):
    """
    The API always returned image_url; nothing in the portal rendered it, so a
    request arrived in the office as text with no way to see the photo. The
    detail view depends on these fields being present in the list payload.
    """
    from flask_jwt_extended import create_access_token
    from models import MaintenanceRequest

    tenant = world["tenants"][0]
    request_row = MaintenanceRequest(
        landlord_id=world["landlord"].id,
        property_id=world["properties"][0].id,
        unit_id=tenant.unit_id,
        tenant_id=tenant.id,
        summary="Ceiling leak above the sink",
        description="Dripping since Friday.",
        category="plumbing", status="open",
        image_url="/uploads/maintenance/1/abc_leak.jpg",
    )
    db_session.add(request_row)
    db_session.flush()

    _, headers = _member(app, world, {"maintenance": (True, True)})
    payload = client.get("/api/maintenance/", headers=headers).get_json()
    row = next(r for r in payload["requests"] if r["id"] == request_row.id)

    assert row["image_url"] == "/uploads/maintenance/1/abc_leak.jpg"
    assert row["tenant_name"]
    assert row["unit_name"]
    assert row["property_name"]


def test_maintenance_status_moves_in_both_directions(client, app, db_session, world):
    """
    open -> in_progress -> closed is the normal path, but a request reopened
    after a bad repair is ordinary, so the transition must not be one-way.
    """
    from models import MaintenanceRequest

    tenant = world["tenants"][0]
    row = MaintenanceRequest(
        landlord_id=world["landlord"].id, property_id=world["properties"][0].id,
        unit_id=tenant.unit_id, tenant_id=tenant.id,
        summary="Blocked drain", category="plumbing", status="open")
    db_session.add(row)
    db_session.flush()

    _, headers = _member(app, world, {"maintenance": (True, True)})
    for status in ("in_progress", "closed", "open"):
        response = client.put(f"/api/maintenance/{row.id}", headers=headers,
                              json={"status": status})
        assert response.status_code == 200
        assert response.get_json()["status"] == status


def test_view_only_maintenance_cannot_change_the_status(client, app, db_session, world):
    from models import MaintenanceRequest

    tenant = world["tenants"][0]
    row = MaintenanceRequest(
        landlord_id=world["landlord"].id, property_id=world["properties"][0].id,
        unit_id=tenant.unit_id, tenant_id=tenant.id,
        summary="Broken light", category="electrical", status="open")
    db_session.add(row)
    db_session.flush()

    _, headers = _member(app, world, {"maintenance": (True, False)})
    response = client.put(f"/api/maintenance/{row.id}", headers=headers,
                          json={"status": "closed"})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Maintenance comments
# ---------------------------------------------------------------------------
# A status says where a job is; it cannot say "plumber booked for Tuesday".
# The is_internal split is the part worth pinning: an office note about what a
# contractor quoted must never reach the tenant, and the filtering happens
# server-side so a client that forgets to check cannot leak it.

def _request_for(db_session, world, **kw):
    from models import MaintenanceRequest

    tenant = world["tenants"][0]
    row = MaintenanceRequest(
        landlord_id=world["landlord"].id, property_id=world["properties"][0].id,
        unit_id=tenant.unit_id, tenant_id=tenant.id,
        summary=kw.get("summary", "Kitchen tap dripping"),
        category="plumbing", status="open")
    db_session.add(row)
    db_session.flush()
    return row


def test_a_note_is_visible_to_the_tenant_by_default(client, app, db_session, world):
    """
    Defaulting to internal would quietly hide updates from the one person
    waiting for them, so "visible" is the default and internal is the opt-in.
    """
    row = _request_for(db_session, world)
    _, headers = _member(app, world, {"maintenance": (True, True)})

    response = client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                           json={"body": "Plumber booked for Tuesday 9am."})

    assert response.status_code == 201
    assert response.get_json()["is_internal"] is False


def test_an_internal_note_never_reaches_the_tenant(client, app, db_session, world):
    from flask_jwt_extended import create_access_token

    row = _request_for(db_session, world)
    _, headers = _member(app, world, {"maintenance": (True, True)})

    client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                json={"body": "Visible: plumber booked Tuesday."})
    client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                json={"body": "Quote was 4,500 — bill the owner.", "is_internal": True})

    tenant = world["tenants"][0]
    with app.app_context():
        token = create_access_token(identity=str(tenant.user_id),
                                    additional_claims={"role": "tenant",
                                                       "tenant_id": tenant.id})
    payload = client.get("/api/portal/maintenance",
                         headers={"Authorization": f"Bearer {token}"}).get_json()
    mine = next(r for r in payload["requests"] if r["id"] == row.id)

    bodies = [c["body"] for c in mine["comments"]]
    assert any("plumber booked" in b.lower() for b in bodies)
    assert not any(c["is_internal"] for c in mine["comments"])
    assert not any("4,500" in b for b in bodies)

    # The office still sees both.
    office = client.get(f"/api/maintenance/{row.id}/comments", headers=headers).get_json()
    assert len(office["comments"]) == 2


def test_the_tenant_can_reply_on_their_own_request(client, app, db_session, world):
    from flask_jwt_extended import create_access_token

    row = _request_for(db_session, world)
    tenant = world["tenants"][0]
    with app.app_context():
        token = create_access_token(identity=str(tenant.user_id),
                                    additional_claims={"role": "tenant",
                                                       "tenant_id": tenant.id})

    response = client.post(f"/api/portal/maintenance/{row.id}/comments",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"body": "I'll be home Tuesday, thanks."})

    assert response.status_code == 201
    # A tenant's own note is never internal — hiding it from them is incoherent.
    assert response.get_json()["is_internal"] is False
    assert response.get_json()["author_role"] == "tenant"


def test_a_tenant_cannot_comment_on_someone_elses_request(client, app, db_session, world):
    from flask_jwt_extended import create_access_token

    row = _request_for(db_session, world)          # belongs to tenants[0]
    other = world["tenants"][1]
    with app.app_context():
        token = create_access_token(identity=str(other.user_id),
                                    additional_claims={"role": "tenant",
                                                       "tenant_id": other.id})

    response = client.post(f"/api/portal/maintenance/{row.id}/comments",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"body": "Not mine."})

    assert response.status_code == 404


def test_view_only_maintenance_cannot_add_a_note(client, app, db_session, world):
    row = _request_for(db_session, world)
    _, headers = _member(app, world, {"maintenance": (True, False)})

    response = client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                           json={"body": "Should be refused."})

    assert response.status_code == 403


def test_an_empty_note_is_rejected(client, app, db_session, world):
    row = _request_for(db_session, world)
    _, headers = _member(app, world, {"maintenance": (True, True)})

    response = client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                           json={"body": "   "})

    assert response.status_code == 400


def test_deleting_a_request_takes_its_notes_with_it(client, app, db_session, world):
    """The child table must not strand rows that block the delete."""
    from models import MaintenanceComment

    row = _request_for(db_session, world)
    _, headers = _member(app, world, {"maintenance": (True, True)})
    client.post(f"/api/maintenance/{row.id}/comments", headers=headers,
                json={"body": "A note."})
    request_id = row.id

    assert client.delete(f"/api/maintenance/{request_id}", headers=headers).status_code == 200
    assert db_session.query(MaintenanceComment).filter_by(request_id=request_id).count() == 0


# ---------------------------------------------------------------------------
# Per-report permissions
# ---------------------------------------------------------------------------
# `reports: view` was one grant over a bucket holding both a property statement
# an owner is entitled to and the payments report, arrears list and portfolio
# comparatives for the whole managed book. Giving an owner their statement meant
# handing over all of it, so in practice owners were given nothing.

def _reports_member(app, world, allowed, *, can_edit=False):
    member, headers = _member(app, world, {"reports": (True, can_edit)})
    row = next(p for p in member.permissions if p.module == "reports")
    row.allowed_reports = allowed
    world["session"].flush()
    return member, headers


def test_null_allowed_reports_means_every_report(client, app, world):
    """
    What every pre-existing row means. NULL must NOT be read as "none",
    otherwise deploying this silently revoked reports from everyone.
    """
    _, headers = _reports_member(app, world, None)

    assert client.get("/api/reports/payments", headers=headers).status_code == 200
    assert client.get(
        f"/api/reports/statements/property/{world['properties'][0].id}",
        headers=headers).status_code == 200


def test_a_narrowed_grant_allows_only_the_listed_report(client, app, world):
    _, headers = _reports_member(app, world, ["property"])

    assert client.get(
        f"/api/reports/statements/property/{world['properties'][0].id}",
        headers=headers).status_code == 200
    assert client.get("/api/reports/payments", headers=headers).status_code == 403
    assert client.get("/api/reports/statements/arrears", headers=headers).status_code == 403


def test_an_empty_list_means_no_reports_at_all(client, app, world):
    """[] is a real choice and must be distinguishable from NULL."""
    _, headers = _reports_member(app, world, [])

    assert client.get("/api/reports/payments", headers=headers).status_code == 403
    assert client.get(
        f"/api/reports/statements/property/{world['properties'][0].id}",
        headers=headers).status_code == 403


def test_the_owner_preset_grants_only_the_property_statement(app):
    """
    The whole point of the change: an owner login exists to see one block's
    figures, not the managing agent's payments report.
    """
    from services.team_preset_service import permission_rows_for

    reports_row = next(r for r in permission_rows_for("owner") if r["module"] == "reports")
    assert reports_row["allowed_reports"] == ["property"]


def test_staff_presets_are_not_narrowed(app):
    """An accountant pulling a month-on-month is doing their job."""
    from services.team_preset_service import permission_rows_for

    reports_row = next(r for r in permission_rows_for("accountant") if r["module"] == "reports")
    assert reports_row["allowed_reports"] is None


def test_a_landlord_is_never_narrowed(client, app, world):
    """This is a delegation control, not a licence check."""
    from flask_jwt_extended import create_access_token

    with app.app_context():
        token = create_access_token(
            identity=str(world["landlord"].user_id),
            additional_claims={"role": "landlord", "landlord_id": world["landlord"].id})

    assert client.get("/api/reports/payments",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_without_the_reports_module_nothing_opens(client, app, world):
    """The finer grant narrows the module; it cannot substitute for it."""
    _, headers = _member(app, world, {"tenants": (True, True)})

    assert client.get("/api/reports/payments", headers=headers).status_code == 403


def test_unknown_report_keys_are_dropped_rather_than_rejected(app):
    """
    Renaming a report later must not make an existing permission row
    unsaveable — drop what we no longer recognise and keep the rest.
    """
    from services import report_access

    assert report_access.normalise(["property", "not_a_report"]) == ["property"]
    assert report_access.normalise(None) is None
    assert report_access.normalise([]) == []


def test_the_catalogue_covers_every_gated_report(app):
    """
    A report gated on a key the catalogue does not offer can never be granted,
    which reads as a broken permission rather than a missing checkbox.
    """
    from services import report_access

    keys = {r["key"] for r in report_access.catalogue()}
    assert keys == set(report_access.REPORT_KEYS)
    # The ones the landlord specifically asked to control separately.
    assert {"property", "payments", "arrears", "penalties"} <= keys
