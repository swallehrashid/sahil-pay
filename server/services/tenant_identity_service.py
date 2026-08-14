"""
services/tenant_identity_service.py — one person, several tenancies.

The same human can hold several units: two in one block, or units under three
different landlords who have never heard of each other. Each occupancy is its
own Tenant row with its own account number, and that separation is deliberate —
it is exactly what stops payments from ever mixing up. An M-Pesa payment is
matched by account number, so three units mean three account numbers and three
independent ledgers, whoever the landlord is.

What was missing is the identity layer above it: a way to recognise that those
rows are one person, so their single phone can sign in and see all of them, and
so a landlord can be told "this tenant also holds two other units here".

IDENTITY RULE
    Tenant rows belong to the same person when they share a normalised phone
    number, or a lowercased email address.

That is the same fact OTP login already proves: a tenant authenticates by
demonstrating control of a phone or an inbox. Anyone who can receive that code
is entitled to every tenancy registered against it — no more, no less. Rows are
never linked on name or national ID alone, which are not proofs of control.
"""

from __future__ import annotations

import re


def normalise_phone(phone: str | None) -> str | None:
    """
    Digits only, compared on the last 9 (the Kenyan subscriber number).

    '+254712345678', '254712345678', '0712345678' and '0712 345 678' are one
    person; storing them differently is a data-entry accident, not a different
    human. Comparing the tail avoids a false split on the country code while
    still being specific enough to be a real match.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return digits[-9:] if len(digits) >= 9 else digits


def normalise_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def sibling_tenant_query(tenant):
    """
    A query for every ACTIVE tenant row belonging to the same person as
    *tenant* — including *tenant* itself.

    Deliberately not landlord-scoped: the point is that one login reaches every
    tenancy the person holds, including ones under different landlords. Demo
    shadow landlords are excluded, as everywhere else.
    """
    from extensions import db
    from models import Landlord, Tenant

    phone = normalise_phone(tenant.phone)
    email = normalise_email(tenant.email)

    clauses = [Tenant.id == tenant.id]
    if phone:
        # Compare on the normalised tail so stored formats can differ.
        digits_only = db.func.regexp_replace(Tenant.phone, r"\D", "", "g")
        clauses.append(db.func.right(digits_only, 9) == phone)
    if email:
        clauses.append(db.func.lower(Tenant.email) == email)

    return (
        Tenant.query
        .join(Landlord, Landlord.id == Tenant.landlord_id)
        .filter(
            Tenant.is_deleted.is_(False),
            Landlord.is_demo.is_(False),
            db.or_(*clauses),
        )
    )


def sibling_tenants(tenant) -> list:
    """Every tenancy this person holds, ordered by landlord then property."""
    from sqlalchemy.orm import joinedload

    from models import Tenant, Unit

    return (
        sibling_tenant_query(tenant)
        .options(joinedload(Tenant.unit).joinedload(Unit.property))
        .order_by(Tenant.landlord_id, Tenant.unit_id)
        .all()
    )


def sibling_tenant_ids(tenant) -> set[int]:
    """
    The ids a portal session authenticated as *tenant* is allowed to act on.

    SECURITY: this is the authorisation set for the tenant portal's unit
    switcher. A request asking for a tenant_id outside it must be refused —
    otherwise the switcher becomes a way to read any tenant in the database.
    """
    from models import Tenant

    return {row.id for row in sibling_tenant_query(tenant).with_entities(Tenant.id).all()}


def same_landlord_siblings(tenant) -> list:
    """
    The person's OTHER tenancies under the SAME landlord.

    This is what the landlord portal shows as "also holds N units here". A
    landlord may only be told about tenancies in their own account — telling
    them their tenant also rents from a competitor would leak another
    landlord's business.
    """
    return [
        row for row in sibling_tenants(tenant)
        if row.landlord_id == tenant.landlord_id and row.id != tenant.id
    ]


def occupancy_summary(tenant) -> dict:
    """
    A compact multi-unit badge for the landlord/admin tenant views.

    `unit_count` counts only this landlord's tenancies; `total_unit_count`
    counts them all and is exposed to admins alone.
    """
    same = same_landlord_siblings(tenant)
    return {
        "unit_count": len(same) + 1,
        "other_units": [
            {
                "tenant_id":     row.id,
                "unit_name":     row.unit.name if row.unit else None,
                "property_name": row.unit.property.name if (row.unit and row.unit.property) else None,
                "account_number": row.account_number,
                "balance":       float(row.balance or 0),
            }
            for row in same
        ],
    }


def link_tenant_to_user(tenant) -> None:
    """
    Attach a tenant row to the login User that already owns the same phone or
    email, so a person who signs in once reaches every unit they hold.

    Called when a tenant is created or their contact details change. No-op when
    no matching user exists — an OTP-only tenant has no User row at all, which
    is supported (the portal authorises off the tenant_id claim).
    """
    from extensions import db
    from models import User, UserRole

    if tenant.user_id:
        return

    email = normalise_email(tenant.email)
    phone = normalise_phone(tenant.phone)

    user = None
    if email:
        user = User.query.filter(
            db.func.lower(User.email) == email,
            User.role == UserRole.tenant.value,
        ).first()
    if user is None and phone:
        digits_only = db.func.regexp_replace(User.phone, r"\D", "", "g")
        user = User.query.filter(
            db.func.right(digits_only, 9) == phone,
            User.role == UserRole.tenant.value,
        ).first()

    if user is not None:
        tenant.user_id = user.id
        db.session.flush()
