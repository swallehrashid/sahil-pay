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
