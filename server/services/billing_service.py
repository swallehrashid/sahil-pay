"""
SahilPay — services/billing_service.py
======================================
Turns the admin's pricing packages into what a landlord actually owes.

The admin defines Packages as unit bands with a per-unit price (e.g. 1–10 units
→ 120/unit, 11–30 → 100/unit). This service:

  * counts a landlord's units,
  * categorises them into the matching ACTIVE package by that count,
  * computes subscription_cost = units × package.price_per_unit (or flat_price),
  * auto-derives next_billing_date from the landlord's registration date, and
  * sets amount_due.

Derived truths (unit_count, package, subscription_cost) are always refreshed.
next_billing_date and amount_due are only auto-filled when unset — so an admin's
manual override of the cycle/due/amount persists.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

ZERO = Decimal("0.00")


def count_units(landlord_id: int) -> int:
    from models import Property, Unit

    return (
        Unit.query.join(Property, Property.id == Unit.property_id)
        .filter(Property.landlord_id == landlord_id, Unit.is_deleted.is_(False), Property.is_deleted.is_(False))
        .count()
    )


def resolve_package(unit_count: int):
    """The active package whose [min_units, max_units] band contains unit_count."""
    from models import Package

    candidates = (
        Package.query.filter(Package.is_active.is_(True), Package.min_units <= unit_count)
        .order_by(Package.min_units.desc())
        .all()
    )
    for pkg in candidates:
        if pkg.max_units is None or unit_count <= pkg.max_units:
            return pkg
    return None


def _cost_for(package, unit_count: int) -> Decimal:
    if package is None:
        return ZERO
    if package.price_per_unit is not None:
        return (Decimal(str(package.price_per_unit)) * unit_count).quantize(Decimal("0.01"))
    if package.flat_price is not None:
        return Decimal(str(package.flat_price))
    return ZERO


def _next_billing_from_registration(landlord) -> date:
    """The next monthly anniversary of the registration date that is >= today."""
    reg = (landlord.created_at.date() if landlord.created_at else date.today())
    nb = reg
    today = date.today()
    # advance to the first anniversary not in the past
    while nb < today:
        nb += relativedelta(months=1)
    return nb


def recompute_subscription(landlord):
    """
    Categorise the landlord into the right package by unit count and refresh
    the derived billing figures. Returns the Subscription (creating one if the
    landlord somehow lacks it). Does NOT commit — the caller commits.
    """
    from extensions import db
    from models import Subscription, SubscriptionStatus

    unit_count = count_units(landlord.id)
    package = resolve_package(unit_count)
    cost = _cost_for(package, unit_count)

    sub = landlord.subscription
    if sub is None:
        sub = Subscription(
            landlord_id=landlord.id,
            unit_count=unit_count,
            subscription_cost=cost,
            status=SubscriptionStatus.trial.value if landlord.is_on_trial else SubscriptionStatus.active.value,
        )
        db.session.add(sub)

    # Derived truths — always refreshed.
    sub.unit_count = unit_count
    sub.subscription_cost = cost
    if package is not None:
        landlord.package_id = package.id

    # Auto-filled only when unset, so an admin override sticks.
    if sub.next_billing_date is None:
        sub.next_billing_date = _next_billing_from_registration(landlord)
    if sub.amount_due is None or sub.amount_due == ZERO:
        sub.amount_due = cost

    return sub
