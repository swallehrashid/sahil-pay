"""
services/category_service.py — landlord charge-category catalogue helpers.

The protected default categories every landlord starts with. Each is `is_default`
(deactivatable, never deletable). Rent auto-bills monthly; Lease Agreement and
Penalty do not; utilities (Water/Electricity metered, Security flat) bill only when
recorded. See CATEGORY_RESTRUCTURE_SPEC.md §0.
"""

from __future__ import annotations

from extensions import db
from models import ChargeCategory

# (name, kind, is_metered, auto_bill_monthly)
DEFAULT_CATEGORIES: list[tuple[str, str, bool, bool]] = [
    ("Rent",            "invoice", False, True),
    ("Lease Agreement", "invoice", False, False),
    ("Penalty",         "invoice", False, False),
    ("Water",           "utility", True,  False),
    ("Electricity",     "utility", True,  False),
    ("Security",        "utility", False, False),
]


RENT_CATEGORY_NAME = "Rent"

# The subcategories that represent real rent income — this month's rent and rent
# arrears carried forward. `deposit` is deliberately absent: a deposit is held,
# refundable money, never income and never commissionable (Kenyan practice, and
# the rule Phase 2's commission maths and Phase 4's tenant score both rely on).
RENT_INCOME_SUBCATEGORIES: tuple[str, ...] = ("current", "balance")


def rent_category_id(landlord_id: int) -> int | None:
    """
    The landlord's canonical Rent category id.

    Prefers the protected default row (is_default=True, name 'Rent') and falls
    back to any category named 'Rent' for landlords whose catalogue predates the
    defaults seeding. Returns None when the landlord has no Rent category at all
    — callers must treat that as "no rent charges exist" rather than an error.
    """
    row = (
        ChargeCategory.query
        .filter_by(landlord_id=landlord_id, name=RENT_CATEGORY_NAME)
        .order_by(ChargeCategory.is_default.desc(), ChargeCategory.id.asc())
        .first()
    )
    return row.id if row else None


def seed_default_categories(landlord_id: int, *, commit: bool = False) -> list[ChargeCategory]:
    """
    Idempotently create the protected default categories for a landlord.
    Skips any whose name already exists (defaults or landlord-created). Flushes so
    the new rows get ids; commits only if asked (callers usually own the transaction).
    """
    existing = {
        c.name for c in ChargeCategory.query.filter_by(landlord_id=landlord_id).all()
    }
    created: list[ChargeCategory] = []
    for name, kind, is_metered, auto_bill in DEFAULT_CATEGORIES:
        if name in existing:
            continue
        cat = ChargeCategory(
            landlord_id=landlord_id,
            name=name,
            kind=kind,
            is_metered=is_metered,
            auto_bill_monthly=auto_bill,
            is_default=True,
            is_active=True,
        )
        db.session.add(cat)
        created.append(cat)

    if created:
        db.session.flush()
    if commit and created:
        db.session.commit()
    return created
