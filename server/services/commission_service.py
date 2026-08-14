"""
services/commission_service.py — what a property manager may actually charge on.

In Kenya a managing agent earns commission on RENT COLLECTED and nothing else:

  * rent for the current month  → commissionable
  * rent arrears cleared later  → commissionable (it is still rent)
  * rent / security deposits    → NEVER. A deposit is the tenant's money, held
                                  and refundable; collecting it is not income.
  * water, garbage, security,
    penalties, other utilities  → collected on the owner's behalf, but not part
                                  of the commission base by convention.

So a report needs two different notions of "gross":

  "all"        every shilling collected — what a landlord managing their own
               block wants, since they net everything off against expenses.
  "rent_only"  rent current + rent arrears — the managing agent's view, and the
               only lawful base for their percentage.

This module is the single place that split is computed, so the property
statement, the comparative reports and the commission line can never disagree
about what counted as rent.

Cash discipline: allocations funded by a tenant's held credit
(models.NON_CASH_PAYMENT_SOURCES) are re-applications of money already
received, so they are excluded — otherwise the same shilling would be
commissioned twice.
"""

from __future__ import annotations

from decimal import Decimal

ZERO = Decimal("0.00")

GROSS_BASIS_ALL = "all"
GROSS_BASIS_RENT_ONLY = "rent_only"
VALID_GROSS_BASES = (GROSS_BASIS_ALL, GROSS_BASIS_RENT_ONLY)


def normalise_basis(value, default: str = GROSS_BASIS_ALL) -> str:
    """The gross basis for a request — an unknown value falls back to *default*."""
    key = (str(value or "").strip().lower()) or default
    return key if key in VALID_GROSS_BASES else default


def resolve_basis(landlord, requested=None) -> str:
    """
    The basis to use: an explicit request wins, otherwise the landlord's saved
    preference, otherwise "all".
    """
    if requested:
        return normalise_basis(requested)
    settings = getattr(landlord, "landlord_settings", None)
    return normalise_basis(getattr(settings, "report_gross_basis", None))


def collections_breakdown(landlord_id: int, property_id: int | None,
                          date_from=None, date_to=None,
                          allowed_property_ids: set[int] | None = None) -> dict:
    """
    Split CONFIRMED cash collections in a window into:

        rent_collected      allocations to the Rent category, subcategory
                            'current' or 'balance'
        deposits_collected  any allocation to subcategory 'deposit'
        other_collected     everything else (utilities, penalties, custom)
        total_collected     the sum of the three

    Returns Decimals. Amounts come from payment_allocations (not payment
    totals), because only the allocation knows WHICH charge a shilling paid.
    """
    from extensions import db
    from models import (
        Invoice, InvoiceLineItem, NON_CASH_PAYMENT_SOURCES, Payment,
        PaymentAllocation, PaymentStatus,
    )
    from services.category_service import RENT_INCOME_SUBCATEGORIES, rent_category_id

    rent_cat_id = rent_category_id(landlord_id)

    query = (
        db.session.query(
            InvoiceLineItem.category_id.label("category_id"),
            InvoiceLineItem.subcategory.label("subcategory"),
            db.func.coalesce(db.func.sum(PaymentAllocation.amount_allocated), 0).label("amount"),
        )
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(InvoiceLineItem, InvoiceLineItem.id == PaymentAllocation.line_item_id)
        .filter(
            Payment.landlord_id == landlord_id,
            Payment.is_deleted.is_(False),
            Payment.status == PaymentStatus.confirmed.value,
            # Credit re-applications are not new cash.
            db.func.coalesce(Payment.source, "").notin_(tuple(NON_CASH_PAYMENT_SOURCES)),
        )
    )

    if date_from:
        query = query.filter(Payment.payment_date >= date_from)
    if date_to:
        query = query.filter(Payment.payment_date <= date_to)
    if property_id:
        query = query.filter(Payment.property_id == property_id)
    if allowed_property_ids is not None:
        query = query.filter(Payment.property_id.in_(allowed_property_ids))

    rows = query.group_by(InvoiceLineItem.category_id, InvoiceLineItem.subcategory).all()

    rent = deposits = other = ZERO
    for row in rows:
        amount = Decimal(str(row.amount or 0))
        subcategory = (row.subcategory or "").lower()

        if subcategory == "deposit":
            deposits += amount
        elif (
            rent_cat_id is not None
            and row.category_id == rent_cat_id
            and subcategory in RENT_INCOME_SUBCATEGORIES
        ):
            rent += amount
        else:
            other += amount

    return {
        "rent_collected":     rent.quantize(Decimal("0.01")),
        "deposits_collected": deposits.quantize(Decimal("0.01")),
        "other_collected":    other.quantize(Decimal("0.01")),
        "total_collected":    (rent + deposits + other).quantize(Decimal("0.01")),
    }


def gross_for(breakdown: dict, basis: str) -> Decimal:
    """
    The gross a report should net expenses and tax against.

    Deposits are excluded from BOTH bases: held money is never income, so it
    never belongs in a profit figure — the "all" basis means every collection
    that is income, not literally every shilling that moved.
    """
    if normalise_basis(basis) == GROSS_BASIS_RENT_ONLY:
        return breakdown["rent_collected"]
    return (breakdown["rent_collected"] + breakdown["other_collected"]).quantize(Decimal("0.01"))


def commission_for(breakdown: dict, commission_rate) -> Decimal:
    """
    The manager's commission — ALWAYS a percentage of rent collected, whatever
    gross basis the report is displaying. Charging it on deposits or utilities
    would be unlawful, so the basis toggle deliberately cannot change this.
    """
    if commission_rate in (None, ""):
        return ZERO
    try:
        rate = Decimal(str(commission_rate))
    except (TypeError, ValueError):
        return ZERO
    if rate <= 0:
        return ZERO
    return (breakdown["rent_collected"] * rate / Decimal("100")).quantize(Decimal("0.01"))


def owner_payouts_total(landlord_id: int, property_id: int,
                        date_from=None, date_to=None) -> Decimal:
    """Money already remitted to this property's owner in the window."""
    from extensions import db
    from models import OwnerPayout

    query = db.session.query(
        db.func.coalesce(db.func.sum(OwnerPayout.amount), 0)
    ).filter(
        OwnerPayout.landlord_id == landlord_id,
        OwnerPayout.property_id == property_id,
    )
    if date_from:
        query = query.filter(OwnerPayout.payout_date >= date_from)
    if date_to:
        query = query.filter(OwnerPayout.payout_date <= date_to)
    return Decimal(str(query.scalar() or 0)).quantize(Decimal("0.01"))
