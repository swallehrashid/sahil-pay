"""
Tenancy agreements.

This is the feature where being wrong is expensive in a way the others are not:
a lease is the document produced when there is a dispute. So the tests below
concentrate on the three things that decide whether the record holds up.

  THE STATE MACHINE. A stale browser tab pressing Approve on a lease that has
  since been returned to the tenant would otherwise record an approval of a
  document nobody signed.

  THE SIGNATURE'S PROVENANCE. Typed name, timestamp, IP and user agent,
  captured at submission. If a landlord could set those, the record would prove
  nothing at all.

  WHO MAY SEE IT. A tenant sees their own lease and only after it is sent; a
  scoped team member sees only their own block's.
"""

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    DocumentTemplate, Landlord, LandlordSettings, LeaseAgreement, LeaseSource,
    LeaseStatus, Property, TeamMember, TeamMemberPermission,
    TeamMemberPropertyAccess, Tenant, Unit, User,
)
from services import lease_service as leases
from utils import ApiError


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def _clean_lease_files(app):
    """
    Remove the lease PDFs these tests render to disk.

    db_session rolls the database back, but nothing rolls back the filesystem,
    and leases are deliberately stored locally rather than on the image CDN.
    Left alone every run would leave another handful behind for good.
    """
    import os
    import shutil

    root = os.path.join(app.root_path, "uploads", "leases")
    before = set(os.listdir(root)) if os.path.isdir(root) else set()
    yield
    if not os.path.isdir(root):
        return
    for name in set(os.listdir(root)) - before:
        path = os.path.join(root, name)
        shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else None


@pytest.fixture()
def world(app, db_session):
    """A landlord with two blocks, a tenant in each, and a scoped team member."""
    s = db_session
    n = _uniq()

    owner = User(email=f"ls-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()
    landlord = Landlord(user_id=owner.id, company_name=f"Lease Co {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.flush()

    props, tenants, tenant_users = [], [], []
    for i in range(2):
        prop = Property(landlord_id=landlord.id, name=f"Block {i}-{n}",
                        city="Nairobi", street_name="Ngong Road")
        s.add(prop)
        s.flush()
        unit = Unit(property_id=prop.id, name=f"U{i}{n[:3]}", rent_amount=Decimal("25000"))
        s.add(unit)
        s.flush()
        tuser = User(email=f"lst{i}-{n}@test.sahilpay", phone=f"2541{i}{n[:6]}",
                     password_hash=generate_password_hash("Testpass1"),
                     role="tenant", is_verified=True, is_active=True)
        s.add(tuser)
        s.flush()
        tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, user_id=tuser.id,
                        first_name=f"Ten{i}", last_name=n[:4],
                        phone=f"25470{i}{n[:6]}", email=f"lt{i}-{n}@test.sahilpay",
                        account_number=f"L{i}{n}", national_id=f"ID{n}",
                        deposit_amount=Decimal("25000"),
                        lease_start_date=date(2026, 1, 1),
                        lease_expiry_date=date(2026, 12, 31),
                        balance=Decimal("0"))
        s.add(tenant)
        s.flush()
        props.append(prop); tenants.append(tenant); tenant_users.append(tuser)

    muser = User(email=f"lsm-{n}@test.sahilpay", phone=f"2549{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="team_member", is_verified=True, is_active=True)
    s.add(muser)
    s.flush()
    member = TeamMember(user_id=muser.id, landlord_id=landlord.id,
                        username=f"lm-{n}", first_name="Scoped", last_name="Member",
                        is_active=True, property_access_all=False)
    s.add(member)
    s.flush()
    s.add(TeamMemberPropertyAccess(team_member_id=member.id, property_id=props[0].id))
    s.add(TeamMemberPermission(team_member_id=member.id, module="tenants",
                               can_view=True, can_edit=True))
    s.flush()

    with app.app_context():
        landlord_token = create_access_token(
            identity=str(owner.id),
            additional_claims={"role": "landlord", "landlord_id": landlord.id})
        member_token = create_access_token(
            identity=str(muser.id),
            additional_claims={"role": "team_member", "landlord_id": landlord.id,
                               "team_member_id": member.id})
        tenant_tokens = [
            create_access_token(identity=f"tenant:{t.id}",
                                additional_claims={"role": "tenant", "tenant_id": t.id,
                                                   "landlord_id": landlord.id})
            for t in tenants
        ]

    return {"landlord": landlord, "properties": props, "tenants": tenants,
            "landlord_token": landlord_token, "member_token": member_token,
            "tenant_tokens": tenant_tokens}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_placeholders_are_filled_from_the_tenancy(db_session, world):
    tenant = world["tenants"][0]
    context = leases.field_context(tenant)
    body = leases.render_body(
        "<p>{tenant_name} rents {unit_name} at {property_name} for KES {rent_amount}.</p>",
        context,
    )
    assert tenant.first_name in body
    assert tenant.unit.name in body
    assert "25,000.00" in body


def test_an_unknown_placeholder_is_left_alone(db_session, world):
    """
    Legal prose contains braces. Blanking anything brace-shaped would silently
    eat clauses, which is worse than showing a stray token.
    """
    body = leases.render_body("<p>Clause {not_a_field} stands.</p>",
                              leases.field_context(world["tenants"][0]))
    assert "{not_a_field}" in body


def test_values_are_escaped_into_the_document(db_session, world):
    """A tenant's name is user input and this string becomes a PDF and HTML."""
    tenant = world["tenants"][0]
    tenant.first_name = "<script>alert(1)</script>"
    db_session.flush()

    body = leases.render_body("<p>{tenant_name}</p>", leases.field_context(tenant))
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_the_default_template_is_usable_as_shipped(app):
    """
    A landlord who never writes their own must still get a real agreement —
    an empty default would fail exactly the people who most need one.
    """
    html = leases.default_template_html()
    for clause in ("TENANCY AGREEMENT", "Rent", "Deposit", "Ending the tenancy"):
        assert clause in html
    assert "laws of Kenya" in html


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def test_the_happy_path_runs_draft_to_approved(db_session, world):
    tenant = world["tenants"][0]
    lease = leases.create_for_tenant(tenant)
    assert lease.status == LeaseStatus.draft.value

    leases.send_to_tenant(lease)
    assert lease.status == LeaseStatus.sent.value
    assert lease.awaiting_tenant is True

    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="41.90.1.1", user_agent="Chrome/Android")
    assert lease.status == LeaseStatus.submitted.value

    leases.approve(lease, actor_user_id=None)
    assert lease.status == LeaseStatus.approved.value
    assert lease.is_downloadable is True


@pytest.mark.parametrize("start,target", [
    (LeaseStatus.draft.value,     LeaseStatus.approved.value),
    (LeaseStatus.draft.value,     LeaseStatus.submitted.value),
    (LeaseStatus.sent.value,      LeaseStatus.approved.value),
    (LeaseStatus.approved.value,  LeaseStatus.submitted.value),
    (LeaseStatus.approved.value,  LeaseStatus.rejected.value),
    (LeaseStatus.uploaded.value,  LeaseStatus.approved.value),
])
def test_illegal_transitions_are_refused(db_session, world, start, target):
    lease = leases.create_for_tenant(world["tenants"][0])
    lease.status = start
    db_session.flush()
    with pytest.raises(ApiError):
        leases.transition(lease, target)


def test_a_rejected_lease_goes_back_to_the_tenant_with_their_answers(db_session, world):
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru",
                  field_values={"emergency_contact": "0722000000"},
                  ip="41.90.1.1", user_agent="Chrome")

    leases.reject(lease, reason="Your ID number is missing.")
    assert lease.status == LeaseStatus.rejected.value
    assert lease.awaiting_tenant is True
    # Their answers survive — nobody re-types a whole agreement over one field.
    assert lease.field_values["emergency_contact"] == "0722000000"


def test_rejecting_destroys_the_signature(db_session, world):
    """
    A signature on a document that has since been edited proves nothing, and
    keeping it would let an approval later attach to text nobody signed.
    """
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="41.90.1.1", user_agent="Chrome")
    assert lease.signed_name

    leases.reject(lease, reason="Wrong unit.")
    assert lease.signed_name is None
    assert lease.signed_at is None
    assert lease.signed_ip is None
    assert lease.document_url is None


def test_a_rejection_must_say_why(db_session, world):
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="1.1.1.1", user_agent="Chrome")
    with pytest.raises(ApiError):
        leases.reject(lease, reason="   ")


def test_a_corrected_lease_can_be_resubmitted(db_session, world):
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina", field_values={},
                  ip="1.1.1.1", user_agent="Chrome")
    leases.reject(lease, reason="Fix the dates.")

    leases.submit(lease, signed_name="Amina Wanjiru", field_values={"x": "1"},
                  ip="2.2.2.2", user_agent="Firefox")
    assert lease.status == LeaseStatus.submitted.value
    assert lease.rejection_reason is None       # the old note is cleared
    assert lease.signed_name == "Amina Wanjiru"


# ---------------------------------------------------------------------------
# The signature
# ---------------------------------------------------------------------------

def test_submission_records_the_provenance(db_session, world):
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="41.90.64.7", user_agent="Mozilla/5.0 (Android 13)")

    assert lease.signed_name == "Amina Wanjiru"
    assert lease.signed_at is not None
    assert lease.signed_ip == "41.90.64.7"
    assert "Android" in lease.signed_user_agent
    assert lease.submitted_at == lease.signed_at


def test_a_name_too_short_to_be_a_signature_is_refused(db_session, world):
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    for attempt in ("", "  ", "A"):
        with pytest.raises(ApiError):
            leases.submit(lease, signed_name=attempt, field_values={},
                          ip="1.1.1.1", user_agent="Chrome")


def test_the_signature_is_not_in_the_tenant_facing_payload(db_session, world):
    """
    A tenant has no business being shown the IP and browser string recorded
    against them; that is evidence for the landlord, not portal furniture.
    """
    lease = leases.create_for_tenant(world["tenants"][0])
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="41.90.64.7", user_agent="Chrome")

    public = lease.to_dict()
    assert "signed_ip" not in public
    assert "signed_user_agent" not in public
    assert lease.to_audit_dict()["signed_ip"] == "41.90.64.7"


# ---------------------------------------------------------------------------
# Paper leases
# ---------------------------------------------------------------------------

def test_an_uploaded_scan_is_immediately_downloadable(db_session, world):
    """A person witnessed the signing, so there is nothing left to review."""
    tenant = world["tenants"][0]
    lease = leases.attach_scan(
        tenant, io.BytesIO(b"%PDF-1.4 signed lease"), filename="signed.pdf")

    assert lease.status == LeaseStatus.uploaded.value
    assert lease.source == LeaseSource.uploaded.value
    assert lease.is_downloadable is True


def test_the_newest_settled_lease_is_the_current_one(db_session, world):
    """A draft prepared later must not displace the signed agreement."""
    tenant = world["tenants"][0]
    signed = leases.attach_scan(tenant, io.BytesIO(b"%PDF-1.4 x"), filename="a.pdf")
    leases.create_for_tenant(tenant)      # a newer draft

    assert leases.current_for_tenant(tenant.id).id == signed.id


# ---------------------------------------------------------------------------
# API — permissions and scoping
# ---------------------------------------------------------------------------

def test_staff_can_run_the_whole_flow(client, db_session, world):
    tenant = world["tenants"][0]

    created = client.post(f"/api/tenants/{tenant.id}/leases",
                          headers=_auth(world["landlord_token"]),
                          json={"send": True})
    assert created.status_code == 201, created.get_data(as_text=True)
    lease_id = created.get_json()["data"]["id"]
    assert created.get_json()["data"]["status"] == LeaseStatus.sent.value

    submitted = client.post("/api/portal/lease/submit",
                            headers=_auth(world["tenant_tokens"][0]),
                            json={"signed_name": "Amina Wanjiru", "agreed": True})
    assert submitted.status_code == 200, submitted.get_data(as_text=True)

    approved = client.post(f"/api/leases/{lease_id}/approve",
                           headers=_auth(world["landlord_token"]))
    assert approved.status_code == 200
    assert approved.get_json()["data"]["status"] == LeaseStatus.approved.value

    download = client.get("/api/portal/lease/download",
                          headers=_auth(world["tenant_tokens"][0]))
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF")


def test_a_tenant_cannot_sign_without_ticking_the_box(client, db_session, world):
    tenant = world["tenants"][0]
    client.post(f"/api/tenants/{tenant.id}/leases",
                headers=_auth(world["landlord_token"]), json={"send": True})

    res = client.post("/api/portal/lease/submit",
                      headers=_auth(world["tenant_tokens"][0]),
                      json={"signed_name": "Amina Wanjiru"})
    assert res.status_code == 422


def test_a_tenant_cannot_see_a_lease_that_was_never_sent(client, db_session, world):
    tenant = world["tenants"][0]
    client.post(f"/api/tenants/{tenant.id}/leases",
                headers=_auth(world["landlord_token"]), json={})   # left as a draft

    res = client.get("/api/portal/lease", headers=_auth(world["tenant_tokens"][0]))
    assert res.status_code == 200
    assert res.get_json()["data"]["lease"] is None


def test_a_tenant_cannot_download_before_it_is_settled(client, db_session, world):
    tenant = world["tenants"][0]
    client.post(f"/api/tenants/{tenant.id}/leases",
                headers=_auth(world["landlord_token"]), json={"send": True})

    res = client.get("/api/portal/lease/download",
                     headers=_auth(world["tenant_tokens"][0]))
    assert res.status_code == 409


def test_a_tenant_only_ever_sees_their_own_lease(client, db_session, world):
    """The portal resolves the tenant from the token, never from the request."""
    other = world["tenants"][1]
    client.post(f"/api/tenants/{other.id}/leases",
                headers=_auth(world["landlord_token"]), json={"send": True})

    res = client.get("/api/portal/lease", headers=_auth(world["tenant_tokens"][0]))
    assert res.get_json()["data"]["lease"] is None


def test_a_scoped_member_cannot_reach_another_blocks_lease(client, db_session, world):
    other = world["tenants"][1]
    created = client.post(f"/api/tenants/{other.id}/leases",
                          headers=_auth(world["landlord_token"]), json={"send": True})
    lease_id = created.get_json()["data"]["id"]

    assert client.get(f"/api/leases/{lease_id}",
                      headers=_auth(world["member_token"])).status_code == 404
    assert client.post(f"/api/leases/{lease_id}/approve",
                       headers=_auth(world["member_token"])).status_code == 404
    assert client.get(f"/api/tenants/{other.id}/leases",
                      headers=_auth(world["member_token"])).status_code == 404


def test_a_scoped_member_sees_only_their_own_block_in_the_list(client, db_session, world):
    for tenant in world["tenants"]:
        client.post(f"/api/tenants/{tenant.id}/leases",
                    headers=_auth(world["landlord_token"]), json={"send": True})

    everything = client.get("/api/leases", headers=_auth(world["landlord_token"]))
    assert everything.get_json()["data"]["count"] == 2

    scoped = client.get("/api/leases", headers=_auth(world["member_token"]))
    rows = scoped.get_json()["data"]["items"]
    assert len(rows) == 1
    assert rows[0]["property_id"] == world["properties"][0].id


def test_approving_a_lease_nobody_signed_is_refused(client, db_session, world):
    """The stale-tab case, over the wire rather than in the service."""
    tenant = world["tenants"][0]
    created = client.post(f"/api/tenants/{tenant.id}/leases",
                          headers=_auth(world["landlord_token"]), json={"send": True})
    lease_id = created.get_json()["data"]["id"]

    res = client.post(f"/api/leases/{lease_id}/approve",
                      headers=_auth(world["landlord_token"]))
    assert res.status_code == 409


def test_uploading_a_signed_scan_over_the_api(client, db_session, world):
    tenant = world["tenants"][0]
    res = client.post(
        f"/api/tenants/{tenant.id}/leases/upload",
        headers=_auth(world["landlord_token"]),
        data={"file": (io.BytesIO(b"%PDF-1.4 signed"), "signed-lease.pdf")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201, res.get_data(as_text=True)
    assert res.get_json()["data"]["status"] == LeaseStatus.uploaded.value

    # Both sides can take a copy straight away.
    assert client.get("/api/portal/lease/download",
                      headers=_auth(world["tenant_tokens"][0])).status_code == 200


def test_lease_endpoints_require_authentication(client, world):
    assert client.get("/api/leases").status_code == 401
    assert client.get("/api/portal/lease").status_code == 401
    assert client.post("/api/portal/lease/submit", json={}).status_code == 401


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def test_a_landlords_own_template_is_used_when_given(db_session, world):
    landlord = world["landlord"]
    template = DocumentTemplate(landlord_id=landlord.id, name="House style",
                                document_type="lease",
                                content="<p>Bespoke terms for {tenant_name}.</p>")
    db_session.add(template)
    db_session.flush()

    lease = leases.create_for_tenant(world["tenants"][0], template_id=template.id)
    assert "Bespoke terms" in lease.body_html


def test_another_accounts_template_cannot_be_used(db_session, world):
    n = _uniq()
    stranger_user = User(email=f"sx-{n}@test.sahilpay", phone=f"2546{n[:7]}",
                         password_hash=generate_password_hash("Testpass1"),
                         role="landlord", is_verified=True, is_active=True)
    db_session.add(stranger_user)
    db_session.flush()
    stranger = Landlord(user_id=stranger_user.id, company_name=f"Other {n}",
                        currency="KES")
    db_session.add(stranger)
    db_session.flush()
    template = DocumentTemplate(landlord_id=stranger.id, name="Theirs",
                                document_type="lease", content="<p>Not yours.</p>")
    db_session.add(template)
    db_session.flush()

    with pytest.raises(ApiError):
        leases.create_for_tenant(world["tenants"][0], template_id=template.id)


def test_the_body_is_snapshotted_so_later_edits_cannot_rewrite_it(db_session, world):
    """
    An agreement somebody signed must not change because the landlord tidied
    the template afterwards.
    """
    template = DocumentTemplate(landlord_id=world["landlord"].id, name="v1",
                                document_type="lease", content="<p>Original wording.</p>")
    db_session.add(template)
    db_session.flush()

    lease = leases.create_for_tenant(world["tenants"][0], template_id=template.id)
    leases.send_to_tenant(lease)
    leases.submit(lease, signed_name="Amina Wanjiru", field_values={},
                  ip="1.1.1.1", user_agent="Chrome")

    template.content = "<p>Completely different wording.</p>"
    db_session.flush()

    assert "Original wording." in lease.body_html
    assert "Completely different" not in lease.body_html
