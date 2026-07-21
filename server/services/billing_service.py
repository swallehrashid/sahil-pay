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

from datetime import date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta

ZERO = Decimal("0.00")

# Canonical discount/tenor table for a subscription payment. Kept here (not in
# billing_routes.py) so both the legacy self-reported endpoint and the verified
# STK endpoint compute identical figures, and so affiliate_service can read
# cycle_months() when it needs "months_covered" for a transaction it didn't
# create context_json for (defensive fallback only — see accrue_for_transaction).
_CYCLE_DISCOUNTS = {
    "monthly":   Decimal("0.00"),
    "quarterly": Decimal("10.00"),
    "annual":    Decimal("15.00"),
}
_CYCLE_MONTHS = {
    "monthly":   1,
    "quarterly": 3,
    "annual":    12,
}


def valid_cycles() -> list[str]:
    return list(_CYCLE_DISCOUNTS.keys())


def cycle_months(billing_cycle: str) -> int:
    return _CYCLE_MONTHS[billing_cycle]


def cycle_discount(billing_cycle: str) -> Decimal:
    return _CYCLE_DISCOUNTS[billing_cycle]


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
    """
    The landlord's first billing date.

    #15 — billing begins the day the trial ends: for a landlord with a trial end
    date still in the future, that date IS the first billing cycle. Otherwise fall
    back to the next monthly anniversary of the registration date.
    """
    today = date.today()
    trial_end = landlord.trial_ends_at.date() if landlord.trial_ends_at else None
    if trial_end is not None and trial_end >= today:
        return trial_end

    reg = (landlord.created_at.date() if landlord.created_at else today)
    nb = reg
    # advance to the first anniversary not in the past
    while nb < today:
        nb += relativedelta(months=1)
    return nb


def recompute_subscription(landlord):
    """
    Categorise the landlord into the right package by unit count and refresh
    the derived billing figures. Returns the Subscription (creating one if the
    landlord somehow lacks it). Does NOT commit — the caller commits.

    DEMO_MODE_SPEC.md §3.4 — a demo shadow landlord is never billed: it has no
    real subscription to keep in sync (its Billing settings page is hidden in
    the UI too). No-op, returning whatever Subscription row it already has
    (none, ordinarily) rather than creating or mutating one.
    """
    if getattr(landlord, "is_demo", False):
        return landlord.subscription

    from extensions import db
    from models import Subscription, SubscriptionStatus

    unit_count = count_units(landlord.id)

    # #17 — a landlord in the Custom package is NOT auto-recategorised by unit band;
    # they keep Custom, and their cost uses the admin-set per-unit override.
    current_pkg = landlord.package
    is_custom = bool(current_pkg and getattr(current_pkg, "is_custom", False))
    if is_custom:
        package = current_pkg
    else:
        package = resolve_package(unit_count)

    # A per-unit price override on the landlord (set for Custom or negotiated deals)
    # supersedes the package's own price.
    if landlord.per_unit_price is not None:
        cost = (Decimal(str(landlord.per_unit_price)) * unit_count).quantize(Decimal("0.01"))
    else:
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
    # Only auto-assign the band package for non-custom landlords.
    if not is_custom and package is not None:
        landlord.package_id = package.id

    # Auto-filled only when unset, so an admin override sticks.
    if sub.next_billing_date is None:
        sub.next_billing_date = _next_billing_from_registration(landlord)
    if sub.amount_due is None or sub.amount_due == ZERO:
        sub.amount_due = cost

    return sub


# ---------------------------------------------------------------------------
# Verified-payment pipeline (AFFILIATE_PROGRAM_SPEC.md §3)
# ---------------------------------------------------------------------------
# Two entry points create a subscription BillingTransaction:
#   1. pay_subscription      (legacy, self-reported reference) — activates the
#      subscription IMMEDIATELY for UX continuity, but is_verified stays False.
#   2. pay_subscription_stk  (new, Daraja STK to Sahil's own paybill) — creates
#      a PENDING transaction; subscription activation is DEFERRED until
#      finalize_subscription_payment() runs from the webhook (or simulation).
#
# Both funnel through finalize_subscription_payment() to flip is_verified=True
# and fire affiliate commission accrual — the ONLY path into
# affiliate_service.accrue_for_transaction(). A transaction with is_verified
# still False can never earn an affiliate a shilling.

def preview_subscription_cost(subscription, billing_cycle: str, new_package_id: int | None = None):
    """
    Pure calculation — does NOT mutate the subscription or landlord.
    Returns (amount_due: Decimal, months: int, discount: Decimal).
    Raises ValueError if new_package_id is supplied but not found/active.
    """
    from models import Package

    if billing_cycle not in _CYCLE_DISCOUNTS:
        raise ValueError(f"billing_cycle must be one of: {valid_cycles()}.")

    base_cost = Decimal(str(subscription.subscription_cost or 0))
    if new_package_id:
        pkg = Package.query.filter_by(id=new_package_id, is_active=True).first()
        if not pkg:
            raise ValueError("Package not found.")
        unit_count = subscription.unit_count or 0
        if pkg.price_per_unit is not None:
            base_cost = Decimal(str(pkg.price_per_unit)) * unit_count
        elif pkg.flat_price is not None:
            base_cost = Decimal(str(pkg.flat_price))

    months     = _CYCLE_MONTHS[billing_cycle]
    discount   = _CYCLE_DISCOUNTS[billing_cycle]
    amount_due = (base_cost * months * (1 - discount / 100)).quantize(Decimal("0.01"))
    return amount_due, months, discount


def build_subscription_context(billing_cycle: str, months: int, discount: Decimal,
                                package_id: int | None, applied: bool) -> dict:
    """The context_json payload stashed on a subscription BillingTransaction."""
    return {
        "billing_cycle": billing_cycle,
        "months":        months,
        "discount":      str(discount),
        "package_id":    package_id,
        "applied":       applied,
    }


def apply_subscription_activation(landlord, subscription, ctx: dict) -> None:
    """Mutates landlord/subscription per a stashed context_json. Idempotency is
    the caller's job (finalize_subscription_payment checks ctx['applied'])."""
    from models import Package, SubscriptionStatus

    new_package_id = ctx.get("package_id")
    if new_package_id:
        pkg = Package.query.filter_by(id=new_package_id, is_active=True).first()
        if pkg:
            landlord.package_id = new_package_id
            unit_count = subscription.unit_count or 0
            if pkg.price_per_unit is not None:
                subscription.subscription_cost = Decimal(str(pkg.price_per_unit)) * unit_count
            elif pkg.flat_price is not None:
                subscription.subscription_cost = Decimal(str(pkg.flat_price))

    subscription.billing_cycle     = ctx["billing_cycle"]
    subscription.discount_rate     = Decimal(str(ctx["discount"]))
    subscription.amount_due        = ZERO
    subscription.status            = SubscriptionStatus.active.value
    subscription.next_billing_date = date.today() + relativedelta(months=ctx["months"])

    if landlord.is_on_trial:
        landlord.is_on_trial = False


def finalize_subscription_payment(txn, admin_id: int | None = None):
    """
    Mark a subscription BillingTransaction verified and, on first call only,
    apply its deferred subscription activation and fire affiliate commission
    accrual. Idempotent — a duplicate Daraja callback or a second admin click
    is a safe no-op (E10/E16 in AFFILIATE_PROGRAM_SPEC.md §10).
    """
    from extensions import db
    from models import BillingTransactionStatus

    if txn.is_verified:
        return txn

    ctx = dict(txn.context_json or {})
    if not ctx.get("applied"):
        landlord     = txn.landlord
        subscription = landlord.subscription if landlord else None
        if subscription is not None and ctx.get("billing_cycle"):
            apply_subscription_activation(landlord, subscription, ctx)
        txn.status = BillingTransactionStatus.paid.value
        ctx["applied"] = True
        txn.context_json = ctx

    txn.is_verified = True
    txn.verified_at  = datetime.utcnow()
    if admin_id:
        txn.verified_by_admin_id = admin_id
    db.session.flush()

    from services.affiliate_service import accrue_for_transaction
    accrue_for_transaction(txn)

    return txn


def finalize_sms_purchase(txn, admin_id: int | None = None):
    """
    Mark an sms_purchase BillingTransaction verified and, on first call only,
    credit the SMS credits to the landlord's balance. Idempotent twin of
    finalize_subscription_payment — no affiliate accrual ever fires for this
    transaction type (accrue_for_transaction ignores non-subscription types).
    """
    from extensions import db
    from models import BillingTransactionStatus

    if txn.is_verified:
        return txn

    ctx = dict(txn.context_json or {})
    if not ctx.get("applied"):
        sms_count = ctx.get("sms_count") or txn.sms_count or 0
        landlord  = txn.landlord
        if landlord is not None and sms_count:
            landlord.sms_balance += sms_count
        txn.status = BillingTransactionStatus.paid.value
        ctx["applied"] = True
        txn.context_json = ctx

    txn.is_verified = True
    txn.verified_at  = datetime.utcnow()
    if admin_id:
        txn.verified_by_admin_id = admin_id
    db.session.flush()

    return txn


def mark_subscription_payment_failed(txn) -> None:
    """STK cancelled/timed out — never verified, never activates anything."""
    from models import BillingTransactionStatus
    if txn.is_verified:
        return
    txn.status = BillingTransactionStatus.failed.value


def reverse_billing_transaction(txn, admin_id: int, reason: str) -> None:
    """
    Admin-initiated reversal of a verified transaction (chargeback, mistaken
    entry). Does not un-apply the subscription activation — the landlord keeps
    the service period they were granted; only the affiliate commission tied
    to this transaction is clawed back (AFFILIATE_PROGRAM_SPEC.md D10/E6).
    """
    from datetime import datetime as _dt
    if txn.is_reversed:
        return
    txn.is_reversed         = True
    txn.reversed_at          = _dt.utcnow()
    txn.reversed_by_admin_id = admin_id
    txn.reversal_reason      = reason

    from services.affiliate_service import reverse_for_transaction
    reverse_for_transaction(txn)
