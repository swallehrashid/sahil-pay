"""
Communications — the in-app channel and messaging your own team.

Two gaps this closes. The channel enum offered sms/whatsapp/email only, so the
one delivery route that is free, instant and survives a lost handset could not
be chosen. And `RecipientType.team_member` and `CommunicationLog.team_member_id`
had existed since the first migration, but the send endpoint accepted
`tenant_ids` only — the schema was ready and the route never used it.

The scoping tests are the important ones. A property manager's team runs from
accountants to caretakers, each restricted to their own blocks, so "whose
tenants may this person message?" must be answered from the caller's own
property access and never from the ids they put in the request body.
"""

import uuid
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    CommunicationLog, Landlord, LandlordSettings, MessageChannel, Property,
    TeamMember, TeamMemberPermission, TeamMemberPropertyAccess, Tenant, Unit,
    User,
)


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def world(app, db_session):
    """A landlord, two blocks each with a tenant, and a team member scoped to one."""
    s = db_session
    n = _uniq()

    owner = User(email=f"cm-{n}@test.sahilpay", phone=f"2547{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="landlord", is_verified=True, is_active=True)
    s.add(owner)
    s.flush()

    landlord = Landlord(user_id=owner.id, company_name=f"CM {n}",
                        currency="KES", sms_balance=500)
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.flush()

    props, tenants = [], []
    for i in range(2):
        prop = Property(landlord_id=landlord.id, name=f"Block {i}-{n}", city="Nairobi")
        s.add(prop)
        s.flush()
        unit = Unit(property_id=prop.id, name=f"U{i}{n[:3]}", rent_amount=Decimal("20000"))
        s.add(unit)
        s.flush()
        tuser = User(email=f"cmt{i}-{n}@test.sahilpay", phone=f"2541{i}{n[:6]}",
                     password_hash=generate_password_hash("Testpass1"),
                     role="tenant", is_verified=True, is_active=True)
        s.add(tuser)
        s.flush()
        tenant = Tenant(landlord_id=landlord.id, unit_id=unit.id, user_id=tuser.id,
                        first_name=f"Ten{i}", last_name=n[:4],
                        phone=f"25470{i}{n[:6]}", email=f"ten{i}-{n}@test.sahilpay",
                        account_number=f"C{i}{n}", balance=Decimal("-1000"))
        s.add(tenant)
        s.flush()
        props.append(prop)
        tenants.append(tenant)

    def _member(label, scoped_to):
        muser = User(email=f"cmm{label}-{n}@test.sahilpay", phone=f"2542{label}{n[:6]}",
                     password_hash=generate_password_hash("Testpass1"),
                     role="team_member", is_verified=True, is_active=True)
        s.add(muser)
        s.flush()
        member = TeamMember(user_id=muser.id, landlord_id=landlord.id,
                            username=f"m{label}-{n}", first_name=f"M{label}",
                            last_name="Member", phone=f"2543{label}{n[:6]}",
                            is_active=True,
                            property_access_all=scoped_to is None)
        s.add(member)
        s.flush()
        if scoped_to is not None:
            s.add(TeamMemberPropertyAccess(team_member_id=member.id,
                                           property_id=scoped_to.id))
        for module in ("messages", "tenants"):
            s.add(TeamMemberPermission(team_member_id=member.id, module=module,
                                       can_view=True, can_edit=True))
        s.flush()
        return member, muser

    scoped_member, scoped_user = _member("1", props[0])
    other_member, _ = _member("2", props[1])

    with app.app_context():
        landlord_token = create_access_token(
            identity=str(owner.id),
            additional_claims={"role": "landlord", "landlord_id": landlord.id})
        scoped_token = create_access_token(
            identity=str(scoped_user.id),
            additional_claims={"role": "team_member", "landlord_id": landlord.id,
                               "team_member_id": scoped_member.id})

    return {"landlord": landlord, "properties": props, "tenants": tenants,
            "scoped_member": scoped_member, "other_member": other_member,
            "landlord_token": landlord_token, "scoped_token": scoped_token}


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _logs_for(landlord_id):
    return db.session.query(CommunicationLog).filter_by(landlord_id=landlord_id).all()


# ---------------------------------------------------------------------------
# The in-app channel
# ---------------------------------------------------------------------------

def test_in_app_is_an_available_channel():
    assert MessageChannel.in_app.value == "in_app"
    assert "in_app" in {c.value for c in MessageChannel}


def test_sending_in_app_to_a_tenant(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app",
                            "tenant_ids": [world["tenants"][0].id],
                            "content": "The water will be off on Friday."})
    assert res.status_code == 200, res.get_data(as_text=True)

    logs = [l for l in _logs_for(world["landlord"].id) if l.message_type == "in_app"]
    assert len(logs) == 1
    assert logs[0].recipient_type == "tenant"
    assert logs[0].status == "delivered"


def test_in_app_costs_no_sms_credit(client, world):
    """Free is the point of the channel — it must never touch the balance."""
    before = world["landlord"].sms_balance
    client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                json={"channel": "in_app", "tenant_ids": [world["tenants"][0].id],
                      "content": "Notice."})
    db.session.refresh(world["landlord"])
    assert world["landlord"].sms_balance == before


def test_an_unknown_channel_is_refused(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "telepathy",
                            "tenant_ids": [world["tenants"][0].id],
                            "content": "Hello."})
    assert res.status_code == 400
    assert "telepathy" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# Team members as recipients
# ---------------------------------------------------------------------------

def test_sending_to_a_team_member(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app",
                            "team_member_ids": [world["scoped_member"].id],
                            "content": "Team meeting Monday at 9."})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["recipients"]["team_members"] == 1

    logs = [l for l in _logs_for(world["landlord"].id)
            if l.recipient_type == "team_member"]
    assert len(logs) == 1
    assert logs[0].team_member_id == world["scoped_member"].id
    assert logs[0].tenant_id is None


def test_tenants_and_team_members_in_one_send(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app",
                            "tenant_ids": [t.id for t in world["tenants"]],
                            "team_member_ids": [world["scoped_member"].id],
                            "content": "Estate-wide notice."})
    assert res.status_code == 200
    counts = res.get_json()["recipients"]
    assert counts == {"tenants": 2, "team_members": 1}


def test_at_least_one_recipient_is_required(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app", "content": "Nobody."})
    assert res.status_code == 400


def test_an_inactive_team_member_is_not_messaged(client, db_session, world):
    """An unaccepted invitation has no working contact route."""
    world["scoped_member"].is_active = False
    db_session.flush()

    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app",
                            "team_member_ids": [world["scoped_member"].id],
                            "content": "Hello."})
    assert res.status_code == 200
    assert res.get_json()["recipients"]["team_members"] == 0


def test_a_team_member_from_another_account_is_not_messaged(client, db_session, world):
    """A real team member, belonging to a DIFFERENT landlord."""
    n = _uniq()
    stranger_user = User(email=f"str-{n}@test.sahilpay", phone=f"2544{n[:7]}",
                         password_hash=generate_password_hash("Testpass1"),
                         role="landlord", is_verified=True, is_active=True)
    db_session.add(stranger_user)
    db_session.flush()
    stranger = Landlord(user_id=stranger_user.id, company_name=f"Other {n}",
                        currency="KES")
    db_session.add(stranger)
    db_session.flush()

    muser = User(email=f"strm-{n}@test.sahilpay", phone=f"2545{n[:7]}",
                 password_hash=generate_password_hash("Testpass1"),
                 role="team_member", is_verified=True, is_active=True)
    db_session.add(muser)
    db_session.flush()
    other = TeamMember(user_id=muser.id, landlord_id=stranger.id,
                       username=f"x-{n}", first_name="X", last_name="Y",
                       is_active=True, property_access_all=True)
    db_session.add(other)
    db_session.flush()

    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app", "team_member_ids": [other.id],
                            "content": "Hello."})
    assert res.status_code == 200
    assert res.get_json()["recipients"]["team_members"] == 0


# ---------------------------------------------------------------------------
# Property scoping
# ---------------------------------------------------------------------------

def test_a_scoped_member_can_message_their_own_tenant(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["scoped_token"]),
                      json={"channel": "in_app",
                            "tenant_ids": [world["tenants"][0].id],
                            "content": "Your block's water is off."})
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["recipients"]["tenants"] == 1


def test_a_scoped_member_cannot_message_another_blocks_tenant(client, world):
    """
    The ids are in the request body, so this is the only place it can be
    stopped — hiding the tenant from their list is not a control.
    """
    res = client.post("/api/communications/send", headers=_auth(world["scoped_token"]),
                      json={"channel": "in_app",
                            "tenant_ids": [world["tenants"][1].id],
                            "content": "Should never arrive."})
    assert res.status_code == 200
    assert res.get_json()["recipients"]["tenants"] == 0

    logs = [l for l in _logs_for(world["landlord"].id)
            if l.tenant_id == world["tenants"][1].id]
    assert logs == []


def test_a_scoped_member_cannot_message_a_colleague_from_another_block(client, world):
    res = client.post("/api/communications/send", headers=_auth(world["scoped_token"]),
                      json={"channel": "in_app",
                            "team_member_ids": [world["other_member"].id],
                            "content": "Should never arrive."})
    assert res.status_code == 200
    assert res.get_json()["recipients"]["team_members"] == 0


def test_the_landlord_is_not_property_scoped(client, world):
    """The account owner sees everything; scoping applies to team members."""
    res = client.post("/api/communications/send", headers=_auth(world["landlord_token"]),
                      json={"channel": "in_app",
                            "tenant_ids": [t.id for t in world["tenants"]],
                            "content": "Everyone."})
    assert res.get_json()["recipients"]["tenants"] == 2


def test_send_requires_authentication(client, world):
    res = client.post("/api/communications/send",
                      json={"channel": "in_app", "tenant_ids": [1], "content": "x"})
    assert res.status_code == 401
