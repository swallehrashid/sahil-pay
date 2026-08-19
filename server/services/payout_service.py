"""
services/payout_service.py — three-level commission + the payout ledger
(sahilpay_payment_allocation_spec.md §4.8, §4.9, §4.10).

WHAT A PAYOUT IS
----------------
A property manager collects every tenant's rent into their own paybill, then
remits each owner their share. This module works out that share.

    total_collected   every shilling of the INCLUDED charge types collected for
                      that owner in the period (see below)
    rent_collected_base
                      rent only (current + arrears). The base MRI is computed
                      on, and the default base for commission.
    commission_base   what commission was actually charged on — the rent base,
                      or the whole included total, per `commission_basis`
    commission        the most-specific matching rule, applied to that base
    tax_amount        7.5% of rent_collected_base — DISPLAY ONLY unless the
                      account has withholding switched on
    net_payable       total_collected − commission − other_deductions
                      [− tax if withheld]

WHAT COUNTS AS "COLLECTED" IS A DECISION, NOT A CONSTANT
--------------------------------------------------------
"Collected" used to mean every shilling that arrived. But a managing agent does
not always remit everything they hold: a water float, a deposit, a penalty they
keep — which of those belongs on an owner's statement is a commercial
arrangement, not arithmetic. So the run takes an explicit set of charge types
(`include`) and totals only those.

RENT IS ALWAYS IN. A payout with no rent in it is not a payout, and the rent
base is what tax is computed on either way — so `rent` is forced into the set
whatever the caller passes.

A DEPOSIT PASSES THROUGH IN FULL when it is included. It is the tenant's
refundable money: it can sit in `total_collected` because the manager is
physically holding it, but it is never in the tax base, and it only enters the
commission base if the account has deliberately chosen the "everything
collected" basis.

COMMISSION BASIS
----------------
`commission_basis="rent"` (the default) charges commission on rent alone, which
is ordinary Kenyan practice and the conservative reading. `"collected"` charges
it on the whole included total. It is an explicit switch on the run rather than
a hidden setting, because the two produce materially different invoices and the
person generating the run is the person who should be choosing.

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

# The two buckets that are not a charge category of their own. `rent` is the
# Rent category narrowed to real rent income (this month + arrears); `deposit`
# is a subcategory that can appear under any category and must never be folded
# into the one it was billed under.
RENT_KEY = "rent"
DEPOSIT_KEY = "deposit"
UNCATEGORISED_KEY = "uncategorised"


def category_key(category_id) -> str:
    """Stable bucket key for a charge category. Ids, not names — a landlord may
    rename a category and the run must still add up the same way."""
    return f"cat:{category_id}" if category_id is not None else UNCATEGORISED_KEY


def normalise_include(include) -> set[str] | None:
    """
    The set of buckets to total, with rent forced in.

    None means "everything", which is what a caller that passes nothing gets —
    the pre-existing behaviour, so an API client written before this existed is
    unaffected.
    """
    if include is None:
        return None
    if isinstance(include, str):
        include = [part.strip() for part in include.split(",")]
    keys = {str(k).strip() for k in include if str(k).strip()}
    keys.add(RENT_KEY)          # rent is never optional
    return keys


def collections_by_unit(landlord_id: int, property_ids: set[int],
                        start: date, end: date) -> dict[int, dict]:
    """
    Per-unit collections in the window, split per charge type.

    Reads payment_allocations rather than payment totals, because only the
    allocation knows WHICH charge a shilling cleared — a 20,000 payment might
    be 12,000 rent and 8,000 deposit, and commissioning the whole thing would
    be unlawful.

    Each unit's dict carries a `buckets` map keyed as above, plus the labels to
    show them under. The caller decides which buckets count.

    Credit re-applications are excluded: that money was already counted as
    collected when it first arrived.
    """
    from models import (
        ChargeCategory, InvoiceLineItem, NON_CASH_PAYMENT_SOURCES, Payment,
        PaymentAllocation, PaymentStatus,
    )
    from services.category_service import RENT_INCOME_SUBCATEGORIES, rent_category_id

    if not property_ids:
        return {}

    rent_cat_id = rent_category_id(landlord_id)
    names = {
        c.id: c.name
        for c in db.session.query(ChargeCategory)
                  .filter(ChargeCategory.landlord_id == landlord_id).all()
    }

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
    labels: dict[str, str] = {RENT_KEY: "Rent", DEPOSIT_KEY: "Deposit"}
    for unit_id, tenant_id, category_id, subcategory, amount in rows:
        bucket = by_unit.setdefault(unit_id, {
            "unit_id": unit_id, "tenant_id": tenant_id, "buckets": {}, "labels": labels,
        })
        value = _D(amount)
        sub = (subcategory or "").lower()
        if sub == "deposit":
            key = DEPOSIT_KEY
        elif rent_cat_id is not None and category_id == rent_cat_id \
                and sub in RENT_INCOME_SUBCATEGORIES:
            key = RENT_KEY
        else:
            key = category_key(category_id)
            if key not in labels:
                name = names.get(category_id) or "Other charges"
                # A rent-category line that is not rent income — a rent-billed
                # penalty, say. Labelled apart so "Rent" never appears twice.
                labels[key] = (f"{name} (other charges)"
                               if category_id == rent_cat_id else name)
        bucket["buckets"][key] = bucket["buckets"].get(key, ZERO) + value
    return by_unit


def _split(buckets: dict, include: set[str] | None) -> tuple:
    """(rent, deposits, other, included_total) for one unit's buckets."""
    rent = _D(buckets.get(RENT_KEY))
    deposits = _D(buckets.get(DEPOSIT_KEY)) if (include is None or DEPOSIT_KEY in include) else ZERO
    other = ZERO
    for key, value in buckets.items():
        if key in (RENT_KEY, DEPOSIT_KEY):
            continue
        if include is None or key in include:
            other += _D(value)
    return rent, deposits, other, rent + deposits + other


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


COMMISSION_BASIS_RENT = "rent"
COMMISSION_BASIS_COLLECTED = "collected"
COMMISSION_BASES = (COMMISSION_BASIS_RENT, COMMISSION_BASIS_COLLECTED)


def normalise_basis(basis) -> str:
    """Anything unrecognised falls back to rent — the conservative base."""
    basis = (basis or "").strip().lower()
    return basis if basis in COMMISSION_BASES else COMMISSION_BASIS_RENT


def available_categories(landlord_id: int, start: date, end: date,
                         property_ids=None) -> list[dict]:
    """
    Every charge type that actually produced money in the window, with its
    total — the checklist the operator ticks before generating a run.

    Only what was collected is offered. A list of every category the account has
    ever defined would be mostly zeros and would make the choice harder, not
    easier. Rent is always first and always marked required.
    """
    totals: dict[str, Decimal] = {}
    labels: dict[str, str] = {RENT_KEY: "Rent", DEPOSIT_KEY: "Deposit"}

    for props in _owner_groups(landlord_id, property_ids).values():
        by_unit = collections_by_unit(landlord_id, {p.id for p in props}, start, end)
        for bucket in by_unit.values():
            labels.update(bucket["labels"])
            for key, value in bucket["buckets"].items():
                totals[key] = totals.get(key, ZERO) + _D(value)

    rows = [{
        "key":      key,
        "label":    labels.get(key, "Other charges"),
        "amount":   _money(amount),
        "required": key == RENT_KEY,
    } for key, amount in totals.items()]

    # Rent first, then the rest by size — the biggest number is the one most
    # likely to be argued about, so it should not be at the bottom of the list.
    rows.sort(key=lambda r: (not r["required"], -float(r["amount"]), r["label"]))
    return rows


def preview_payouts(landlord_id: int, start: date, end: date,
                    property_ids=None, *, include=None,
                    commission_basis=COMMISSION_BASIS_RENT) -> list[dict]:
    """
    What each owner is owed for the period. Computes nothing persistent.

    `include` is the set of charge-type keys that count as collected (None =
    all of them, rent always in either way). `commission_basis` decides whether
    commission is charged on rent alone or on the whole included total.
    """
    from models import Landlord, Unit

    landlord = db.session.get(Landlord, landlord_id)
    withhold = bool(getattr(landlord, "tax_withholding_enabled", False))
    include = normalise_include(include)
    basis = normalise_basis(commission_basis)

    previews = []
    for key, props in _owner_groups(landlord_id, property_ids).items():
        prop_ids = {p.id for p in props}
        by_unit = collections_by_unit(landlord_id, prop_ids, start, end)

        lines, rent_base, total = [], ZERO, ZERO
        commission_total, commission_base_total = ZERO, ZERO
        breakdown: dict[str, Decimal] = {}
        labels: dict[str, str] = {}

        for unit_id, bucket in by_unit.items():
            unit = db.session.get(Unit, unit_id) if unit_id else None
            rule = resolve_commission_rule(
                landlord_id,
                unit_id=unit_id,
                property_id=unit.property_id if unit else None,
            )
            rent, deposits, other, included = _split(bucket["buckets"], include)
            # Commission follows the chosen base PER UNIT, because the rule is
            # resolved per unit — totalling first and applying one rule would
            # silently use whichever rule happened to come last.
            base = included if basis == COMMISSION_BASIS_COLLECTED else rent
            commission = commission_for_base(rule, base)

            rent_base += rent
            total += included
            commission_base_total += base
            commission_total += commission
            labels.update(bucket["labels"])
            for bkey, value in bucket["buckets"].items():
                if include is None or bkey in include:
                    breakdown[bkey] = breakdown.get(bkey, ZERO) + _D(value)

            lines.append({
                "unit_id":            unit_id,
                "unit_name":          unit.name if unit else None,
                "tenant_id":          bucket["tenant_id"],
                "rent_collected":     _money(rent),
                "deposits_collected": _money(deposits),
                "other_collected":    _money(other),
                "commission_amount":  commission,
                "commission_rule":    rule.to_dict() if rule else None,
            })

        # Tax stays on RENT, whatever commission was charged on. MRI is a tax on
        # rental income; folding a water float into it would overstate what the
        # owner owes KRA.
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
            "commission_basis":    basis,
            "commission_base":     _money(commission_base_total),
            "commission_amount":   _money(commission_total),
            "tax_amount":          tax,
            "tax_withheld":        withhold,
            "other_deductions":    ZERO,
            "net_payable":         net,
            "included_categories": sorted(include) if include is not None else None,
            "collected_breakdown": [
                {"key": k, "label": labels.get(k, "Other charges"), "amount": _money(v)}
                for k, v in sorted(breakdown.items(),
                                   key=lambda kv: (kv[0] != RENT_KEY, -float(kv[1])))
            ],
            "lines":               lines,
        })

    previews.sort(key=lambda p: p["owner_name"] or "")
    return previews


def generate_payouts(landlord_id: int, start: date, end: date, *,
                     property_ids=None, created_by_user_id=None,
                     include=None,
                     commission_basis=COMMISSION_BASIS_RENT) -> list:
    """
    Persist a pending payout per owner for the period, with its per-unit lines.

    Takes the SAME `include` / `commission_basis` arguments as the preview and
    runs through it, so what is recorded is exactly what was on screen when the
    button was pressed. Both choices are stored on the payout: six months later
    "why is this commission different from that one?" has to be answerable from
    the row itself, not from whoever happened to tick the boxes.

    Skips owners with nothing collected — a zero payout is noise, not a record.
    Flushes; the caller commits.
    """
    from models import OwnerPayout, PayoutLine, PayoutStatus

    created = []
    for preview in preview_payouts(landlord_id, start, end, property_ids,
                                   include=include,
                                   commission_basis=commission_basis):
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
            commission_basis    = preview["commission_basis"],
            commission_base     = preview["commission_base"],
            included_categories = preview["included_categories"],
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
