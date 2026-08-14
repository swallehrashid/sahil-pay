"""
Cross-portal access control — the isolation suite (OPUS_EXECUTION_SPEC Phase 3.1).

This is the security regression net for the whole platform. It builds one of
every kind of caller and then asserts, route by route, that none of them can
reach data belonging to somebody else:

  * an unauthenticated caller gets 401 everywhere,
  * a tenant can never reach a landlord or admin route,
  * a landlord can never reach an admin route,
  * a team member can never reach an admin route,
  * landlord B can never read landlord A's objects by id (cross-account IDOR),
  * a team member scoped to property A never sees rows from property B
    (in-account IDOR — the property-manager case, where an owner login must not
    see a rival owner's block),
  * tenant B can never read tenant A's portal data.

The historical bug class here is real: an OTP login once resolved to the wrong
account entirely (commit d91fd5d). Treat any failure here as a genuine defect.
"""

import uuid

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    User, SystemAdmin, Landlord, LandlordSettings, AutomationSettings,
    Property, Unit, Tenant, TeamMember, TeamMemberPermission,
    TeamMemberPropertyAccess, Invoice, InvoiceLineItem, Payment, Expense,
    PermissionModule, InvoiceStatus, InvoiceType, PaymentStatus, PaymentSource,
    Affiliate,
)


def _uniq() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# World builder
# ---------------------------------------------------------------------------

def _make_landlord(session, label):
    n = _uniq()
    user = User(
        email=f"ac-{label}-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    session.add(user)
    session.flush()
    landlord = Landlord(user_id=user.id, company_name=f"AC {label} {n}", currency="KES")
    session.add(landlord)
    session.flush()
    session.add(LandlordSettings(landlord_id=landlord.id))
    session.add(AutomationSettings(landlord_id=landlord.id))
    session.flush()
    return landlord, user


def _make_property(session, landlord, name):
    prop = Property(
        landlord_id=landlord.id, name=f"{name}-{_uniq()}",
        number_of_units=2, city="Nairobi",
    )
    session.add(prop)
    session.flush()
    return prop


def _make_unit(session, prop, name):
    unit = Unit(property_id=prop.id, name=f"{name}-{_uniq()}", rent_amount=10000)
    session.add(unit)
    session.flush()
    return unit


def _make_tenant(session, landlord, unit):
    n = _uniq()
    tenant = Tenant(
        landlord_id=landlord.id, unit_id=unit.id,
        first_name="AC", last_name=f"T{n}",
        phone=f"+25472{n[:7]}", email=f"ac-t-{n}@test.sahilpay",
        account_number=f"ACC-{n}",
    )
    session.add(tenant)
    session.flush()
    return tenant


def _make_invoice(session, landlord, tenant, prop, unit):
    from datetime import date
    from decimal import Decimal

    inv = Invoice(
        invoice_number=f"INV-{_uniq()}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=prop.id, invoice_type=InvoiceType.rent.value,
        issue_date=date.today(), status=InvoiceStatus.open.value,
        total_amount=Decimal("10000"), amount_paid=Decimal("0"), balance=Decimal("10000"),
        title="Rent",
    )
    session.add(inv)
    session.flush()
    li = InvoiceLineItem(
        invoice_id=inv.id, item="Rent", quantity=1,
        unit_price=10000, amount=10000, subcategory="current",
    )
    session.add(li)
    session.flush()
    return inv, li


def _make_payment(session, landlord, tenant, prop, unit):
    from datetime import date
    from decimal import Decimal

    p = Payment(
        payment_ref=f"PMT-{_uniq()}", landlord_id=landlord.id, tenant_id=tenant.id,
        unit_id=unit.id, property_id=prop.id, amount=Decimal("5000"),
        payment_date=date.today(), status=PaymentStatus.confirmed.value,
        source=PaymentSource.manual.value, payment_method="Manual",
    )
    session.add(p)
    session.flush()
    return p


def _make_expense(session, landlord, prop):
    from datetime import date
    from decimal import Decimal

    e = Expense(
        landlord_id=landlord.id, property_id=prop.id, category="security",
        amount=Decimal("1000"), expense_date=date.today(), status="confirmed",
    )
    session.add(e)
    session.flush()
    return e


def _make_team_member(session, landlord, *, property_ids, modules=None):
    """A team member restricted to `property_ids` with view+edit on `modules`."""
    n = _uniq()
    user = User(
        email=f"ac-tm-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="team_member", is_verified=True, is_active=True,
    )
    session.add(user)
    session.flush()
    tm = TeamMember(
        user_id=user.id, landlord_id=landlord.id, username=f"tm{n}",
        role="editor", preset="owner", property_access_all=False, is_active=True,
    )
    session.add(tm)
    session.flush()
    for module in (modules or [m.value for m in PermissionModule]):
        session.add(TeamMemberPermission(
            team_member_id=tm.id, module=module, can_view=True, can_edit=True,
        ))
    for pid in property_ids:
        session.add(TeamMemberPropertyAccess(team_member_id=tm.id, property_id=pid))
    session.flush()
    return tm, user


def _make_admin(session):
    n = _uniq()
    user = User(
        email=f"ac-admin-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", is_verified=True, is_active=True,
        totp_enabled=True,   # admin routes require the second factor (spec 3.4)
    )
    session.add(user)
    session.flush()
    session.add(SystemAdmin(user_id=user.id, first_name="AC", last_name="Admin"))
    session.flush()
    return user


def _make_affiliate(session):
    n = _uniq()
    user = User(
        email=f"ac-aff-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="affiliate", is_verified=True, is_active=True,
    )
    session.add(user)
    session.flush()
    aff = Affiliate(user_id=user.id, full_name="AC Affiliate",
                    phone=user.phone,
                    referral_code=f"AC{n[:6].upper()}", status="approved")
    session.add(aff)
    session.flush()
    return aff, user


def _token(app, user, *, landlord_id=None, team_member_id=None, affiliate_id=None):
    claims = {"role": user.role}
    if landlord_id:
        claims["landlord_id"] = landlord_id
    if team_member_id:
        claims["team_member_id"] = team_member_id
    if affiliate_id:
        claims["affiliate_id"] = affiliate_id
        claims["affiliate_status"] = "approved"
    with app.app_context():
        return create_access_token(identity=str(user.id), additional_claims=claims)


def _tenant_token(app, tenant):
    """A tenant portal token — identity is namespaced 'tenant:<id>' (see otp_routes)."""
    with app.app_context():
        return create_access_token(
            identity=f"tenant:{tenant.id}",
            additional_claims={"role": "tenant", "tenant_id": tenant.id},
        )


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world(app, db_session):
    """
    Two independent landlords, each with two properties, plus every caller type.

    Landlord A's team member is scoped to property A1 ONLY — the property-manager
    shape where an owner login must never see the manager's other blocks.
    """
    s = db_session

    a, a_user = _make_landlord(s, "A")
    b, b_user = _make_landlord(s, "B")

    a1 = _make_property(s, a, "A1")
    a2 = _make_property(s, a, "A2")
    b1 = _make_property(s, b, "B1")

    a1u = _make_unit(s, a1, "A1U")
    a2u = _make_unit(s, a2, "A2U")
    b1u = _make_unit(s, b1, "B1U")

    a1t = _make_tenant(s, a, a1u)
    a2t = _make_tenant(s, a, a2u)
    b1t = _make_tenant(s, b, b1u)

    a1_inv, a1_li = _make_invoice(s, a, a1t, a1, a1u)
    a2_inv, a2_li = _make_invoice(s, a, a2t, a2, a2u)
    b1_inv, b1_li = _make_invoice(s, b, b1t, b1, b1u)

    a1_pay = _make_payment(s, a, a1t, a1, a1u)
    a2_pay = _make_payment(s, a, a2t, a2, a2u)
    b1_pay = _make_payment(s, b, b1t, b1, b1u)

    a1_exp = _make_expense(s, a, a1)
    a2_exp = _make_expense(s, a, a2)

    tm, tm_user = _make_team_member(s, a, property_ids=[a1.id])
    admin_user = _make_admin(s)
    aff, aff_user = _make_affiliate(s)

    s.commit()

    return {
        "a": a, "b": b, "a_user": a_user, "b_user": b_user,
        "a1": a1, "a2": a2, "b1": b1,
        "a1u": a1u, "a2u": a2u, "b1u": b1u,
        "a1t": a1t, "a2t": a2t, "b1t": b1t,
        "a1_inv": a1_inv, "a2_inv": a2_inv, "b1_inv": b1_inv,
        "a1_pay": a1_pay, "a2_pay": a2_pay, "b1_pay": b1_pay,
        "a1_exp": a1_exp, "a2_exp": a2_exp,
        "tm": tm, "tm_user": tm_user,
        "admin_user": admin_user, "aff": aff, "aff_user": aff_user,
        "tokens": {
            "a": _token(app, a_user, landlord_id=a.id),
            "b": _token(app, b_user, landlord_id=b.id),
            "tm": _token(app, tm_user, landlord_id=a.id, team_member_id=tm.id),
            "admin": _token(app, admin_user),
            "affiliate": _token(app, aff_user, affiliate_id=aff.id),
            "tenant_a": _tenant_token(app, a1t),
            "tenant_b": _tenant_token(app, b1t),
        },
    }


# ---------------------------------------------------------------------------
# 1. Unauthenticated access
# ---------------------------------------------------------------------------

# Routes that are public by design and must NOT require a token.
PUBLIC_PREFIXES = (
    "/api/auth", "/api/otp", "/api/public", "/api/webhooks", "/api/mpesa/callback",
    "/api/receipts/public", "/api/affiliates/signup", "/api/copilot/ingest",
    "/api/copilot/register", "/api/copilot/app",
    # Liveness probe — carries no data, must answer before auth works at all.
    "/api/health",
    # The OpenAPI explorer. Public in dev by design and NOT mounted in
    # production at all (see create_app: ENABLE_API_DOCS / IS_PRODUCTION).
    "/api/docs", "/apispec",
)

# /api/admin/impersonation/landlord/* is landlord-facing despite the prefix: it
# is how a landlord reviews, grants and denies an admin's request for support
# access. A landlord reaching it is the consent workflow working as designed.
ADMIN_PREFIX_EXCEPTIONS = ("/api/admin/impersonation/landlord",)


def _protected_get_routes(app):
    """Every GET route that takes no path params and isn't deliberately public."""
    out = []
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith("/api/"):
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:
            continue
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            continue
        out.append(path)
    return sorted(set(out))


def test_no_token_is_rejected_everywhere(client, app, world):
    """Every protected GET must refuse an anonymous caller."""
    leaks = []
    for path in _protected_get_routes(app):
        resp = client.get(path)
        if resp.status_code not in (401, 422):
            leaks.append((path, resp.status_code))
    assert not leaks, f"Routes reachable without a token: {leaks}"


# ---------------------------------------------------------------------------
# 2. Role separation — wrong portal, wrong role
# ---------------------------------------------------------------------------

def _admin_get_routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        path = str(rule)
        if not path.startswith("/api/admin"):
            continue
        if any(path.startswith(p) for p in ADMIN_PREFIX_EXCEPTIONS):
            continue
        if "GET" not in (rule.methods or set()) or rule.arguments:
            continue
        out.append(path)
    return sorted(set(out))


@pytest.mark.parametrize("caller", ["a", "tm", "tenant_a", "affiliate"])
def test_non_admins_cannot_reach_admin_routes(client, app, world, caller):
    """Only a system admin may touch /api/admin/*."""
    token = world["tokens"][caller]
    leaks = []
    for path in _admin_get_routes(app):
        resp = client.get(path, headers=_auth(token))
        if resp.status_code not in (401, 403, 422):
            leaks.append((path, resp.status_code))
    assert not leaks, f"{caller} reached admin routes: {leaks}"


def test_tenant_cannot_reach_landlord_routes(client, app, world):
    """A tenant token must never open the landlord portal's data."""
    token = world["tokens"]["tenant_a"]
    landlord_paths = [
        "/api/dashboard/summary", "/api/tenants/", "/api/payments/",
        "/api/invoices/", "/api/expenses/", "/api/properties/", "/api/units/",
        "/api/reports/insights", "/api/team/", "/api/billing/",
        "/api/owner-payouts/",
    ]
    leaks = []
    for path in landlord_paths:
        resp = client.get(path, headers=_auth(token))
        if resp.status_code not in (401, 403, 404, 422):
            leaks.append((path, resp.status_code))
    assert not leaks, f"Tenant reached landlord routes: {leaks}"


# ---------------------------------------------------------------------------
# 3. Cross-landlord IDOR — B must never read A's objects by id
# ---------------------------------------------------------------------------

def _object_routes(world):
    """(label, path) for A's objects, to be requested with B's token."""
    w = world
    return [
        ("tenant",            f"/api/tenants/{w['a1t'].id}"),
        ("tenant txns",       f"/api/tenants/{w['a1t'].id}/transactions"),
        ("invoice",           f"/api/invoices/{w['a1_inv'].id}"),
        ("payment",           f"/api/payments/{w['a1_pay'].id}"),
        ("expense",           f"/api/expenses/{w['a1_exp'].id}"),
        ("unit",              f"/api/units/{w['a1u'].id}"),
        ("property",          f"/api/properties/{w['a1'].id}"),
        ("tenant statement",  f"/api/reports/statements/tenant/{w['a1t'].id}"),
        ("property stmt",     f"/api/reports/statements/property/{w['a1'].id}"),
    ]


def test_landlord_b_cannot_read_landlord_a_objects(client, world):
    """The classic cross-account IDOR sweep."""
    token = world["tokens"]["b"]
    leaks = []
    for label, path in _object_routes(world):
        resp = client.get(path, headers=_auth(token))
        if resp.status_code == 200:
            leaks.append((label, path, resp.status_code))
    assert not leaks, f"Landlord B read landlord A's data: {leaks}"


def test_tenant_b_cannot_read_tenant_a_portal_data(client, world):
    """Tenant portal endpoints must resolve strictly from the caller's own token."""
    token = world["tokens"]["tenant_b"]
    resp = client.get("/api/tenant-portal/dashboard", headers=_auth(token))
    if resp.status_code == 200:
        body = resp.get_json() or {}
        blob = str(body)
        assert world["a1t"].account_number not in blob, (
            "Tenant B's dashboard leaked tenant A's account number"
        )
        assert world["a1t"].phone not in blob, (
            "Tenant B's dashboard leaked tenant A's phone"
        )


# ---------------------------------------------------------------------------
# 4. In-account property scoping — the property-manager case
# ---------------------------------------------------------------------------

SCOPED_LIST_ROUTES = [
    "/api/tenants/",
    "/api/payments/",
    "/api/invoices/",
    "/api/expenses/",
    "/api/units/",
    "/api/properties/",
    "/api/maintenance/",
    "/api/owner-payouts/",
    "/api/dashboard/unpaid-tenants",
]


def _collect_ids(payload):
    """Every integer id appearing anywhere in a JSON response."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "id" and isinstance(v, int):
                    found.add(v)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


@pytest.mark.parametrize("path", SCOPED_LIST_ROUTES)
def test_scoped_team_member_never_sees_other_properties(client, world, path):
    """
    A team member granted only property A1 must not receive ANY row belonging to
    property A2 — same landlord, different block. This is the owner-login case: a
    property manager's client must never read a rival client's book.
    """
    token = world["tokens"]["tm"]
    resp = client.get(path, headers=_auth(token))
    if resp.status_code != 200:
        pytest.skip(f"{path} not readable by this member ({resp.status_code})")

    body = resp.get_json() or {}
    blob = str(body)

    # Identifying strings from the OTHER property that must never appear.
    forbidden = {
        "property A2 name":  world["a2"].name,
        "unit A2":           world["a2u"].name,
        "tenant A2 phone":   world["a2t"].phone,
        "tenant A2 account": world["a2t"].account_number,
        "invoice A2":        world["a2_inv"].invoice_number,
        "payment A2":        world["a2_pay"].payment_ref,
    }
    leaked = [label for label, needle in forbidden.items() if needle and needle in blob]
    assert not leaked, f"{path} leaked out-of-scope data to a scoped member: {leaked}"


def test_scoped_team_member_cannot_open_other_property_objects(client, world):
    """Direct object access must respect the member's property scope too."""
    token = world["tokens"]["tm"]
    w = world
    paths = [
        ("tenant in A2",   f"/api/tenants/{w['a2t'].id}"),
        ("invoice in A2",  f"/api/invoices/{w['a2_inv'].id}"),
        ("payment in A2",  f"/api/payments/{w['a2_pay'].id}"),
        ("expense in A2",  f"/api/expenses/{w['a2_exp'].id}"),
        ("unit in A2",     f"/api/units/{w['a2u'].id}"),
        ("property A2",    f"/api/properties/{w['a2'].id}"),
        ("A2 statement",   f"/api/reports/statements/property/{w['a2'].id}"),
    ]
    leaks = []
    for label, path in paths:
        resp = client.get(path, headers=_auth(token))
        if resp.status_code == 200:
            leaks.append((label, path))
    assert not leaks, f"Scoped member opened out-of-scope objects: {leaks}"


def test_dashboard_summary_excludes_out_of_scope_money(client, world):
    """
    The landing page's KPI cards must be computed from the member's own
    properties only — otherwise a caretaker reads the whole portfolio's arrears
    off the first screen they see.
    """
    token = world["tokens"]["tm"]
    resp = client.get("/api/dashboard/summary", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    # The member can see A1 only: 1 unit, 1 tenant.
    assert body["total_units"] == 1, (
        f"Dashboard counted units outside the member's scope: {body['total_units']}"
    )
    assert body["active_tenants"] == 1, (
        f"Dashboard counted tenants outside the member's scope: {body['active_tenants']}"
    )


# ---------------------------------------------------------------------------
# 5. Privilege escalation via the permission matrix
# ---------------------------------------------------------------------------

def test_settings_pseudo_module_cannot_be_granted(client, world):
    """
    'settings' is the marker landlord-only routes (billing, account profile,
    team management) guard themselves with. If it could be granted through the
    permission matrix, a landlord could hand a caretaker the account's money.
    """
    token = world["tokens"]["a"]
    resp = client.put(
        f"/api/team/{world['tm'].id}/permissions",
        headers=_auth(token),
        json={"permissions": [{"module": "settings", "can_view": True, "can_edit": True}]},
    )
    assert resp.status_code == 400, (
        f"'settings' was accepted as a grantable module ({resp.status_code}) — "
        "this is a privilege-escalation path into landlord-only routes."
    )


def test_identity_never_leaks_between_requests_in_one_app_context(app, world):
    """
    Regression: get_jwt_user() and the property-scope resolver both cache on
    `flask.g`, which belongs to the APPLICATION context — and an app context can
    serve many requests (scripts, Celery tasks, a test client driven inside
    app_context). Caching unkeyed there made request #2 inherit request #1's
    identity and scope: a scoped caretaker was answered with the whole
    portfolio's figures. Both caches are now keyed by the JWT identity.
    """
    client = app.test_client()
    tokens = world["tokens"]

    # Landlord first — the wide scope — then the scoped team member, inside the
    # SAME app context, which is what the fixture's app_context gives us.
    landlord_resp = client.get("/api/dashboard/summary", headers=_auth(tokens["a"]))
    assert landlord_resp.status_code == 200
    landlord_units = landlord_resp.get_json()["total_units"]

    member_resp = client.get("/api/dashboard/summary", headers=_auth(tokens["tm"]))
    assert member_resp.status_code == 200
    member_units = member_resp.get_json()["total_units"]

    assert landlord_units == 2, "landlord A owns 2 units — one in A1, one in A2"
    assert member_units == 1, (
        f"the scoped member saw {member_units} units — the previous caller's "
        "identity leaked out of the g cache"
    )


def test_team_member_cannot_spend_account_money(client, world):
    """Billing endpoints move real money and belong to the account owner alone."""
    token = world["tokens"]["tm"]
    leaks = []
    for path in ("/api/billing/", "/api/billing/transactions"):
        resp = client.get(path, headers=_auth(token))
        if resp.status_code == 200:
            leaks.append((path, resp.status_code))
    for path in ("/api/billing/pay-subscription", "/api/billing/buy-sms"):
        resp = client.post(path, headers=_auth(token), json={})
        if resp.status_code not in (401, 403, 422):
            leaks.append((path, resp.status_code))
    assert not leaks, f"Team member reached billing endpoints: {leaks}"
