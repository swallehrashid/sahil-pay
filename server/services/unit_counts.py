"""
services/unit_counts.py — keeping properties.number_of_units true.

WHY THIS EXISTS
---------------
`properties.number_of_units` is a stored integer that was meant to say how many
units a block has. Nothing kept it in step with the units that actually exist:

  * bulk import created every property with the column at its default of 0 and
    then added the units without ever coming back to it, so importing 100
    properties and 1,000 units left every single property reading "0 units";
  * creating a property through the API REQUIRED the number up front, which is
    a question nobody can answer correctly at that moment and which is wrong
    the first time a unit is added or removed;
  * deleting a unit never decremented it.

The number is not a fact anyone should be typing in. A property has as many
units as there are units pointing at it, and that is knowable at any moment.

WHY THE COLUMN IS NOT SIMPLY DELETED
------------------------------------
It is read all over the place — the property list, exports, backups, the API
contract that the Co-pilot app and any saved report rely on — and computing it
per row on read is an N+1 query on a screen that already lists a hundred
properties. So it stays as a CACHE, and this module is the one thing allowed to
write it: recompute from the units table whenever units change. One statement,
however many properties, so calling it after a bulk import of a thousand units
costs a single round trip.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from extensions import db
from models import Property, Unit

logger = logging.getLogger(__name__)


def recount(property_ids=None, *, landlord_id: int | None = None) -> int:
    """
    Recompute number_of_units from the units that actually exist.

    Pass `property_ids` to fix specific blocks, `landlord_id` to fix a whole
    account, or neither to fix everything. Returns how many rows were touched.

    Deleted units do not count — a soft-deleted unit is not a unit the landlord
    has — and a property whose units have all been deleted correctly lands on 0
    rather than keeping its last non-zero value.
    """
    counts = (
        select(Unit.property_id, func.count(Unit.id).label("n"))
        .where(Unit.is_deleted.is_(False))
        .group_by(Unit.property_id)
        .subquery()
    )

    target = Property.__table__.update().values(
        number_of_units=func.coalesce(
            select(counts.c.n).where(counts.c.property_id == Property.id).scalar_subquery(),
            0,
        )
    )

    if property_ids is not None:
        ids = [int(i) for i in property_ids if i is not None]
        if not ids:
            return 0
        target = target.where(Property.id.in_(ids))
    elif landlord_id is not None:
        target = target.where(Property.landlord_id == landlord_id)

    result = db.session.execute(target)
    changed = result.rowcount or 0
    logger.info("unit_counts.recount: refreshed %s property row(s)", changed)
    return changed


def recount_for_units(units) -> int:
    """Recount the properties behind a set of units (a bulk import, say)."""
    ids = {getattr(u, "property_id", None) for u in units or []}
    ids.discard(None)
    return recount(ids) if ids else 0
