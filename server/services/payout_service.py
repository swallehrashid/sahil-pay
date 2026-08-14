"""
services/payout_service.py — three-level commission + the payout ledger
(sahilpay_payment_allocation_spec.md §4.8, §4.9, §4.10).

WHAT A PAYOUT IS
----------------
A property manager collects every tenant's rent into their own paybill, then
remits each owner their share. This module works out that share.

    total_collected   every shilling collected for that owner in the period —
                      rent, deposits, utilities, the lot
    rent_collected_base
                      rent only (current + arrears). The ONLY lawful base for
                      commission in Kenya, and the base MRI is computed on too.
    commission        the most-specific matching rule, applied to the base
    tax_amount        7.5% of the base — DISPLAY ONLY unless the account has
                      withholding switched on
    net_payable       total_collected − commission − other_deductions
                      [− tax if withheld]

A DEPOSIT PASSES THROUGH IN FULL. It is the tenant's refundable money: it is in
`total_collected` because the manager is physically holding it, and in neither
the commission nor the tax base because it is not income to anybody.

v1 is TRACK-ONLY — no B2C automation. The manager marks a payout paid with a
date, method and M-Pesa code, and the system produces the statement.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from extensions import db
from utils import ApiError

ZERO = Decimal("0.00")

# Kenya's Monthly Rental Income rate, shared with services/etims_service.py.
MRI_RATE = Decimal("0.075")


def _D(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value) -> Decimal:
    return _D(value).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Commission rules — most specific wins
# ---------------------------------------------------------------------------

def resolve_commission_rule(landlord_id: int, *, unit_id=None, property_id=None):
    """
    The rule that governs a unit: unit → property → landlord (account-wide).

    Returns None when the account has configured nothing, which means no
    commission — never a silent default rate. A manager who hasn't told us what
    they charge must not have a number invented for them.
    """
    from models import CommissionRule, CommissionScopeType

    def _find(scope_type, scope_id):
        query = db.session.query(CommissionRule).filter(
            CommissionRule.landlord_id == landlord_id,
            CommissionRule.scope_type == scope_type,
            CommissionRule.is_active.is_(True),
        )
        query = (query.filter(CommissionRule.scope_id == scope_id) if scope_id is not None
                 else query.filter(CommissionRule.scope_id.is_(None)))
        return query.first()

    if unit_id is not None:
        rule = _find(CommissionScopeType.unit.value, unit_id)
        if rule is not None:
            return rule
    if property_id is not None:
        rule = _find(CommissionScopeType.property.value, property_id)
        if rule is not None:
            return rule
    return _find(CommissionScopeType.landlord.value, None)


def commission_for_base(rule, rent_base) -> Decimal:
    """
    Apply a rule to a rent-collected base.

    A FIXED rule is a flat fee, but it is still capped at the rent actually
    collected: charging a 15,000 flat fee on a month where 4,000 came in would
    hand the owner a negative payout.
    """
    if rule is None:
        return ZERO
    base = _D(rent_base)
    if base <= ZERO:
        return ZERO
    if (rule.rate_type or "percentage") == "fixed":
        return _money(min(_D(rule.rate_value), base))
    return _money(base * _D(rule.rate_value) / Decimal("100"))


# ---------------------------------------------------------------------------
# Collections, split per unit
# ---------------------------------------------------------------------------

def collections_by_unit(landlord_id: int, property_ids: set[int],
                        start: date, end: date) -> dict[int, dict]:
    """
    Per-unit rent / deposits / other actually collected in the window.

    Reads payment_allocations rather than payment totals, because only the
    allocation knows WHICH charge a shilling cleared — a 20,000 payment might
    be 12,000 rent and 8,000 deposit, and commissioning the whole thing would
    be unlawful.

    Credit re-applications are excluded: that money was already counted as
    collected when it first arrived.
    """
    from models import (
        InvoiceLineItem, NON_CASH_PAYMENT_SOURCES, Payment, PaymentAllocation,
        PaymentStatus,
    )
    from services.category_service import RENT_INCOME_SUBCATEGORIES, rent_category_id

    if not property_ids:
        return {}

    rent_cat_id = rent_category_id(landlord_id)

    rows = (
        db.session.query(
            Payment.unit_id,
            Payment.tenant_id,
            InvoiceLineItem.category_id,
            InvoiceLineItem.subcategory,
            db.func.coalesce(db.func.sum(PaymentAllocation.amount_allocated), 0),
        )
        .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
        .join(InvoiceLineItem, InvoiceLineItem.id == PaymentAllocation.line_item_id)
        .filter(Payment.landlord_id == landlord_id,
                Payment.property_id.in_(property_ids),
                Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
                db.func.coalesce(Payment.source, "").notin_(tuple(NON_CASH_PAYMENT_SOURCES)),
                Payment.payment_date >= start,
                Payment.payment_date <= end)
        .group_by(Payment.unit_id, Payment.tenant_id,
                  InvoiceLineItem.category_id, InvoiceLineItem.subcategory)
        .all()
    )

    by_unit: dict[int, dict] = {}
    for unit_id, tenant_id, category_id, subcategory, amount in rows:
        bucket = by_unit.setdefault(unit_id, {
            "unit_id": unit_id, "tenant_id": tenant_id,
            "rent": ZERO, "deposits": ZERO, "other": ZERO,
        })
        value = _D(amount)
        sub = (subcategory or "").lower()
        if sub == "deposit":
            bucket["deposits"] += value
        elif rent_cat_id is not None and category_id == rent_cat_id \
                and sub in RENT_INCOME_SUBCATEGORIES:
            bucket["rent"] += value
        else:
            bucket["other"] += value
    return by_unit


# ---------------------------------------------------------------------------
# Preview / generate
# ---------------------------------------------------------------------------

def _owner_groups(landlord_id: int, property_ids=None) -> dict:
    """
    Properties grouped by the person actually being paid.

    An owner with three blocks gets ONE payout, because that is one remittance
    to one person. Properties with no owner row are grouped per property, which
    is the self-managing landlord's case.
    """
    from models import Property

    query = db.session.query(Property).filter(
        Property.landlord_id == landlord_id,
        Property.is_deleted.is_(False),
    )
    if property_ids:
        query = query.filter(Property.id.in_(property_ids))

    groups: dict = {}
    for prop in query.all():
        key = ("owner", prop.owner_id) if prop.owner_id else ("property", prop.id)
        groups.setdefault(key, []).append(prop)
    return groups


def preview_payouts(landlord_id: int, start: date, end: date,
                    property_ids=None) -> list[dict]:
    """What each owner is owed for the period. Computes nothing persistent."""
    from models import Landlord, Unit

    landlord = db.session.get(Landlord, landlord_id)
    withhold = bool(getattr(landlord, "tax_withholding_enabled", False))

    previews = []
    for key, props in _owner_groups(landlord_id, property_ids).items():
        prop_ids = {p.id for p in props}
        by_unit = collections_by_unit(landlord_id, prop_ids, start, end)

        lines, rent_base, total, commission_total = [], ZERO, ZERO, ZERO
        for unit_id, bucket in by_unit.items():
            unit = db.session.get(Unit, unit_id) if unit_id else None
            rule = resolve_commission_rule(
                landlord_id,
                unit_id=unit_id,
                property_id=unit.property_id if unit else None,
            )
            commission = commission_for_base(rule, bucket["rent"])
            rent_base += bucket["rent"]
            total += bucket["rent"] + bucket["deposits"] + bucket["other"]
            commission_total += commission
            lines.append({
                "unit_id":            unit_id,
                "unit_name":          unit.name if unit else None,
                "tenant_id":          bucket["tenant_id"],
                "rent_collected":     _money(bucket["rent"]),
                "deposits_collected": _money(bucket["deposits"]),
                "other_collected":    _money(bucket["other"]),
                "commission_amount":  commission,
                "commission_rule":    rule.to_dict() if rule else None,
            })

        tax = _money(rent_base * MRI_RATE)
        net = _money(total - commission_total - (tax if withhold else ZERO))
        owner = props[0].owner

        previews.append({
            "key":                 f"{key[0]}:{key[1]}",
            "owner_id":            props[0].owner_id,
            "owner_name":          owner.full_name if owner else props[0].name,
            "property_ids":        sorted(prop_ids),
            "property_names":      [p.name for p in props],
            "period_start":        start.isoformat(),
            "period_end":          end.isoformat(),
            "total_collected":     _money(total),
            "rent_collected_base": _money(rent_base),
            "commission_amount":   _money(commission_total),
            "tax_amount":          tax,
            "tax_withheld":        withhold,
            "other_deductions":    ZERO,
            "net_payable":         net,
            "lines":               lines,
        })

    previews.sort(key=lambda p: p["owner_name"] or "")
    return previews


def generate_payouts(landlord_id: int, start: date, end: date, *,
                     property_ids=None, created_by_user_id=None) -> list:
    """
    Persist a pending payout per owner for the period, with its per-unit lines.

    Skips owners with nothing collected — a zero payout is noise, not a record.
    Flushes; the caller commits.
    """
    from models import OwnerPayout, PayoutLine, PayoutStatus

    created = []
    for preview in preview_payouts(landlord_id, start, end, property_ids):
        if _D(preview["total_collected"]) <= ZERO:
            continue

        # One payout row still needs a property_id (the column is NOT NULL and
        # the property statement joins on it), so an owner spanning several
        # blocks is anchored to the first and the lines carry the detail.
        payout = OwnerPayout(
            landlord_id         = landlord_id,
            property_id         = preview["property_ids"][0],
            owner_id            = preview["owner_id"],
            amount              = preview["net_payable"],
            payout_date         = end,
            period              = start.strftime("%Y-%m"),
            period_start        = start,
            period_end          = end,
            total_collected     = preview["total_collected"],
            rent_collected_base = preview["rent_collected_base"],
            commission_amount   = preview["commission_amount"],
            tax_amount          = preview["tax_amount"],
            tax_withheld        = preview["tax_withheld"],
            other_deductions    = ZERO,
            net_payable         = preview["net_payable"],
            status              = PayoutStatus.pending.value,
            created_by_user_id  = created_by_user_id,
        )
        db.session.add(payout)
        db.session.flush()

        for line in preview["lines"]:
            db.session.add(PayoutLine(
                payout_id          = payout.id,
                unit_id            = line["unit_id"],
                tenant_id          = line["tenant_id"],
                rent_collected     = line["rent_collected"],
                deposits_collected = line["deposits_collected"],
                other_collected    = line["other_collected"],
                commission_amount  = line["commission_amount"],
            ))
        created.append(payout)

    db.session.flush()
    return created


def mark_paid(payout, *, method=None, reference=None, paid_on=None):
    """Record that the money actually went out. v1 has no B2C automation."""
    from models import PayoutStatus

    if payout.status == PayoutStatus.paid.value:
        raise ApiError("That payout is already marked paid.", status=409)

    payout.status = PayoutStatus.paid.value
    payout.paid_at = datetime.utcnow()
    payout.method = method or payout.method
    payout.reference = reference or payout.reference
    if paid_on:
        payout.payout_date = paid_on
    db.session.flush()
    return payout
