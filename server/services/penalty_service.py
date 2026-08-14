"""
services/penalty_service.py — late-payment penalties.

WHAT A PENALTY IS HERE
----------------------
A charge raised against a tenant who is still in rent arrears when their
property's due day passes. It is an invoice like any other, filed under the
protected "Penalty" charge category.

THREE RULES THAT ARE NOT NEGOTIABLE, AND WHY
--------------------------------------------
1. NEVER COMMISSIONABLE. The charge is filed under the Penalty category, which
   is not the Rent category, and services/commission_service.py computes
   commission from rent collected only. A manager therefore cannot earn a
   percentage of a fine. This is enforced by WHERE the money is filed, not by a
   flag — there is no field anywhere that could switch it on.

2. AT MOST ONCE PER MONTH, AUTOMATICALLY. Enforced by a partial unique index on
   penalty_charges, so a retried Celery job or two workers racing physically
   cannot double-charge. A human may still add a further charge on top; that is
   recorded with source='manual' and sits outside the index on purpose.

3. ARREARS MEANS NEGATIVE. tenant.balance < 0 is money owed (see
   services/report_generators.py). The previous implementation filtered
   `balance > 0` and so charged tenants who were in CREDIT while letting real
   debtors alone. Every arrears figure in this module goes through
   `arrears_of()` so that inversion cannot come back.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
Nothing compounds. A tenant who owes for four months has four separate monthly
penalties, each computed on the arrears standing at the time — not a penalty on
a penalty. `max_penalty` caps percentage and tiered modes so a long-running
arrear cannot produce a figure nobody intended.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from extensions import db
from models import (
    Invoice, InvoiceLineItem, PenaltyCharge, PenaltyMode, PenaltySource,
    PenaltyTier, PenaltyTrigger, Property, PropertyPenaltyPolicy, Tenant,
)
from utils import ApiError

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")
PENALTY_CATEGORY_NAME = "Penalty"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Arrears
# ---------------------------------------------------------------------------

def arrears_of(tenant) -> Decimal:
    """
    How much this tenant OWES, as a positive number. Zero if settled or in
    credit.

    The single place the ledger's sign convention is interpreted. Everything
    else in this module asks this function rather than comparing balances
    itself, because getting the sign backwards silently penalises the wrong
    people — which is exactly what happened before.
    """
    balance = Decimal(str(tenant.balance or 0))
    return _money(-balance) if balance < 0 else ZERO


# ---------------------------------------------------------------------------
# Policy resolution
# ---------------------------------------------------------------------------

def policy_for(property_id: int) -> PropertyPenaltyPolicy | None:
    return (
        db.session.query(PropertyPenaltyPolicy)
        .filter_by(property_id=property_id)
        .first()
    )


def is_due_today(policy, today: date, invoice_due_date: date | None = None) -> bool:
    """
    Whether *today* is the day this policy charges.

    day_of_month   — the configured day, clamped to the last day of a short
                     month so a policy set to the 28th still fires in February
                     and a 31st-of-the-month policy is not skipped in April.
    days_after_due  — N days after the tenant's own invoice due date, so each
                     tenant is judged against their own billing cycle.
    """
    if policy is None or not policy.is_enabled:
        return False

    if policy.trigger_type == PenaltyTrigger.days_after_due.value:
        if invoice_due_date is None or policy.grace_days is None:
            return False
        return today >= invoice_due_date + timedelta(days=int(policy.grace_days))

    day = policy.trigger_day
    if not day:
        return False
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.day == min(int(day), last_day)


# ---------------------------------------------------------------------------
# Amount
# ---------------------------------------------------------------------------

def tier_for(policy, arrears: Decimal) -> PenaltyTier | None:
    """
    The band *arrears* falls into. Bands are half-open [min, max), so adjacent
    tiers can never both match and the result is never ambiguous.
    """
    for tier in sorted(policy.tiers, key=lambda t: Decimal(str(t.min_balance))):
        low = Decimal(str(tier.min_balance))
        high = Decimal(str(tier.max_balance)) if tier.max_balance is not None else None
        if arrears >= low and (high is None or arrears < high):
            return tier
    return None


def amount_for(policy, arrears: Decimal) -> Decimal:
    """
    What to charge a tenant owing *arrears* under *policy*. Zero means "do not
    charge" — below the minimum balance, no matching tier, or nothing set.
    """
    if policy is None or arrears <= ZERO:
        return ZERO

    if policy.min_balance is not None and arrears < Decimal(str(policy.min_balance)):
        return ZERO

    mode = policy.mode
    if mode == PenaltyMode.fixed.value:
        amount = _money(policy.fixed_amount)

    elif mode == PenaltyMode.percentage.value:
        rate = Decimal(str(policy.percentage_rate or 0))
        amount = _money(arrears * rate / Decimal("100"))

    elif mode == PenaltyMode.tiered.value:
        tier = tier_for(policy, arrears)
        if tier is None:
            return ZERO
        if tier.amount_type == PenaltyMode.percentage.value:
            amount = _money(arrears * Decimal(str(tier.amount)) / Decimal("100"))
        else:
            amount = _money(tier.amount)
    else:
        return ZERO

    if policy.max_penalty is not None:
        amount = min(amount, _money(policy.max_penalty))
    return max(amount, ZERO)


# ---------------------------------------------------------------------------
# Charging
# ---------------------------------------------------------------------------

def already_charged(tenant_id: int, year: int, month: int) -> bool:
    """Has an AUTOMATIC penalty already been raised this month?"""
    return (
        db.session.query(PenaltyCharge.id)
        .filter(PenaltyCharge.tenant_id == tenant_id,
                PenaltyCharge.period_year == year,
                PenaltyCharge.period_month == month,
                PenaltyCharge.source == PenaltySource.auto.value)
        .first()
        is not None
    )


def _penalty_category_id(landlord_id: int) -> int | None:
    from models import ChargeCategory

    row = (
        db.session.query(ChargeCategory.id)
        .filter_by(landlord_id=landlord_id, name=PENALTY_CATEGORY_NAME)
        .first()
    )
    return row[0] if row else None


def charge_tenant(tenant, policy, amount: Decimal, *, today: date,
                  source: str = PenaltySource.auto.value,
                  actor_user_id: int | None = None,
                  note: str | None = None) -> PenaltyCharge | None:
    """
    Raise one penalty: an invoice, the ledger effect, and the audit row.

    Returns None when there is nothing to charge. Flushes but does not commit —
    the caller owns the transaction, matching every other service here.
    """
    from tasks.invoice_tasks import _create_invoice

    amount = _money(amount)
    if amount <= ZERO:
        return None

    unit = tenant.unit
    if unit is None or unit.property is None:
        return None

    arrears = arrears_of(tenant)
    category_id = _penalty_category_id(tenant.landlord_id)

    invoice = _create_invoice(
        tenant.landlord_id, tenant, unit, unit.property, "penalty", today, None,
        [{
            "item": "Late payment penalty",
            "unit_price": amount,
            # Filing it under the Penalty category is what keeps it out of the
            # commissionable rent bucket, and what lets the penalties report
            # and the category reports see it at all.
            "category_id": category_id,
        }],
        title="Late Payment Penalty",
    )

    charge = PenaltyCharge(
        landlord_id   = tenant.landlord_id,
        property_id   = unit.property_id,
        unit_id       = unit.id,
        tenant_id     = tenant.id,
        invoice_id    = invoice.id if invoice else None,
        policy_id     = policy.id if policy is not None else None,
        period_year   = today.year,
        period_month  = today.month,
        source        = source,
        basis_balance = arrears,
        amount        = amount,
        note          = note,
        applied_by    = actor_user_id,
    )
    db.session.add(charge)
    db.session.flush()
    return charge


def apply_for_property(prop, *, today: date, actor_user_id: int | None = None,
                       dry_run: bool = False) -> dict:
    """
    Run one property's policy across its tenants for *today*.

    Returns a summary rather than raising: one tenant's bad data must not stop
    the rest of the estate being charged.
    """
    policy = policy_for(prop.id)
    result = {"property_id": prop.id, "property": prop.name,
              "charged": 0, "skipped": 0, "total": ZERO, "tenants": []}

    if policy is None or not policy.is_enabled:
        return result

    tenants = (
        db.session.query(Tenant)
        .filter(Tenant.landlord_id == prop.landlord_id,
                Tenant.is_deleted.is_(False))
        .join(Tenant.unit)
        .filter_by(property_id=prop.id)
        .all()
    )

    for tenant in tenants:
        arrears = arrears_of(tenant)
        if arrears <= ZERO:
            result["skipped"] += 1
            continue

        due_date = _latest_due_date(tenant)
        if not is_due_today(policy, today, invoice_due_date=due_date):
            result["skipped"] += 1
            continue

        if already_charged(tenant.id, today.year, today.month):
            result["skipped"] += 1
            continue

        amount = amount_for(policy, arrears)
        if amount <= ZERO:
            result["skipped"] += 1
            continue

        result["tenants"].append({
            "tenant_id": tenant.id,
            "name": f"{tenant.first_name} {tenant.last_name}".strip(),
            "arrears": float(arrears),
            "amount": float(amount),
        })
        result["total"] += amount
        result["charged"] += 1

        if not dry_run:
            charge_tenant(tenant, policy, amount, today=today,
                          actor_user_id=actor_user_id)

    result["total"] = float(result["total"])
    return result


def _latest_due_date(tenant) -> date | None:
    """The due date of this tenant's most recent rent invoice."""
    row = (
        db.session.query(Invoice.due_date)
        .filter(Invoice.tenant_id == tenant.id,
                Invoice.is_deleted.is_(False),
                Invoice.due_date.isnot(None))
        .order_by(Invoice.due_date.desc())
        .first()
    )
    return row[0] if row else None


def run_for_landlord(landlord_id: int, *, today: date | None = None,
                     actor_user_id: int | None = None,
                     dry_run: bool = False) -> dict:
    """Every enabled property on one account."""
    today = today or date.today()
    properties = (
        db.session.query(Property)
        .filter(Property.landlord_id == landlord_id,
                Property.is_deleted.is_(False))
        .all()
    )

    summaries, charged, total = [], 0, ZERO
    for prop in properties:
        summary = apply_for_property(prop, today=today,
                                     actor_user_id=actor_user_id, dry_run=dry_run)
        if summary["charged"]:
            summaries.append(summary)
            charged += summary["charged"]
            total += Decimal(str(summary["total"]))

    return {"landlord_id": landlord_id, "date": today.isoformat(),
            "charged": charged, "total": float(total),
            "properties": summaries, "dry_run": dry_run}


# ---------------------------------------------------------------------------
# Policy writes (validated)
# ---------------------------------------------------------------------------

def save_policy(prop, data: dict) -> PropertyPenaltyPolicy:
    """
    Create or update a property's policy from validated request data.

    Validation is deliberately strict: a policy that is enabled but has no
    usable amount would run nightly, charge nothing, and look like a bug to the
    owner who switched it on.
    """
    mode = (data.get("mode") or PenaltyMode.fixed.value).strip()
    if mode not in {m.value for m in PenaltyMode}:
        raise ApiError(f"Unknown penalty mode '{mode}'.", status=422,
                       errors={"mode": "invalid"})

    trigger = (data.get("trigger_type") or PenaltyTrigger.day_of_month.value).strip()
    if trigger not in {t.value for t in PenaltyTrigger}:
        raise ApiError(f"Unknown trigger '{trigger}'.", status=422,
                       errors={"trigger_type": "invalid"})

    policy = policy_for(prop.id)
    if policy is None:
        policy = PropertyPenaltyPolicy(landlord_id=prop.landlord_id, property_id=prop.id)
        db.session.add(policy)

    policy.is_enabled      = bool(data.get("is_enabled", False))
    policy.mode            = mode
    policy.fixed_amount    = data.get("fixed_amount")
    policy.percentage_rate = data.get("percentage_rate")
    policy.trigger_type    = trigger
    policy.trigger_day     = data.get("trigger_day")
    policy.grace_days      = data.get("grace_days")
    policy.min_balance     = data.get("min_balance")
    policy.max_penalty     = data.get("max_penalty")

    if trigger == PenaltyTrigger.day_of_month.value:
        day = policy.trigger_day
        if day is None or not (1 <= int(day) <= 28):
            raise ApiError(
                "Choose a day between 1 and 28. Later days are not offered "
                "because they would not exist in February.",
                status=422, errors={"trigger_day": "out_of_range"})
        policy.grace_days = None
    else:
        if policy.grace_days is None or int(policy.grace_days) < 0:
            raise ApiError("Set how many days after the due date to charge.",
                           status=422, errors={"grace_days": "required"})
        policy.trigger_day = None

    # Replace the tiers wholesale — editing bands in place invites overlaps.
    if "tiers" in data:
        policy.tiers.clear()
        db.session.flush()
        for raw in data.get("tiers") or []:
            policy.tiers.append(PenaltyTier(
                min_balance = raw.get("min_balance") or 0,
                max_balance = raw.get("max_balance"),
                amount_type = raw.get("amount_type") or PenaltyMode.fixed.value,
                amount      = raw.get("amount") or 0,
            ))

    _validate_usable(policy)
    db.session.flush()
    return policy


def _validate_usable(policy) -> None:
    """An enabled policy must be able to produce an amount."""
    if not policy.is_enabled:
        return

    if policy.mode == PenaltyMode.fixed.value:
        if not policy.fixed_amount or Decimal(str(policy.fixed_amount)) <= 0:
            raise ApiError("Set the penalty amount before switching this on.",
                           status=422, errors={"fixed_amount": "required"})

    elif policy.mode == PenaltyMode.percentage.value:
        if not policy.percentage_rate or Decimal(str(policy.percentage_rate)) <= 0:
            raise ApiError("Set the percentage before switching this on.",
                           status=422, errors={"percentage_rate": "required"})

    elif policy.mode == PenaltyMode.tiered.value:
        if not policy.tiers:
            raise ApiError("Add at least one band before switching this on.",
                           status=422, errors={"tiers": "required"})
        bands = sorted(policy.tiers, key=lambda t: Decimal(str(t.min_balance)))
        for earlier, later in zip(bands, bands[1:]):
            if earlier.max_balance is None:
                raise ApiError("Only the top band may have no upper limit.",
                               status=422, errors={"tiers": "overlapping"})
            if Decimal(str(earlier.max_balance)) > Decimal(str(later.min_balance)):
                raise ApiError(
                    "Two bands overlap. Each band must start where the "
                    "previous one ends.",
                    status=422, errors={"tiers": "overlapping"})
