"""
services/pay_code_service.py — unit pay-codes (spec §4.3).

A pay-code is the reference a tenant quotes when paying. It is the ONLY thing
that makes a payment unambiguous: a phone number identifies a tenant but never
says which of their units, whereas a pay-code names exactly one lease.

Three rules the spec is explicit about, and the reasons they matter:

  HYBRID GENERATION  the system proposes {prefix}-{suffix}; the owner may
                     rewrite the human part. A code nobody can pronounce over
                     the phone doesn't get used.

  STAYS EDITABLE     even after payments have quoted it. Locking a code the
                     moment money touches it traps an owner with a typo
                     forever.

  ALIAS HISTORY      because of the above, an old code keeps arriving for
                     months — saved in M-Pesa, written on a lease. Retiring a
                     code files it in unit_pay_code_aliases and the resolver
                     keeps honouring it, while reminders quote only the current
                     one.
"""

from __future__ import annotations

import re

from extensions import db
from utils import ApiError

# Deliberately narrow: a pay-code is read aloud, typed on a feature phone
# keypad, and copied off a printed notice.
_PAY_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,29}$")

MAX_LENGTH = 30


def normalise(value) -> str | None:
    """Clean a user-entered code. Blank returns None (no code set)."""
    if value is None:
        return None
    code = re.sub(r"\s+", "", str(value)).upper()
    if not code:
        return None
    if len(code) > MAX_LENGTH:
        raise ApiError(f"A pay code can be at most {MAX_LENGTH} characters.",
                       status=422, errors={"pay_code": "too_long"})
    if not _PAY_CODE_RE.match(code):
        raise ApiError(
            "A pay code can contain letters, numbers and hyphens only, and must "
            "start with a letter or number.",
            status=422, errors={"pay_code": "invalid_characters"},
        )
    return code


def _prefix_for(prop) -> str:
    """Two-letter shorthand from the property name, e.g. 'Palm View' -> 'PA'."""
    letters = re.sub(r"[^A-Za-z0-9]", "", prop.name or "")[:2].upper()
    return letters or "U"


def propose(unit, prop=None) -> str:
    """
    A collision-free code for *unit*.

    Suffixed with the unit id rather than a counter: ids are already unique, so
    this needs no second query and cannot race another unit being created at
    the same moment.
    """
    prop = prop or unit.property
    return f"{_prefix_for(prop)}-{unit.id}"


def is_available(landlord_id: int, code: str, exclude_unit_id: int | None = None) -> bool:
    """
    Whether *code* is free for this ACCOUNT — checking both live codes and
    retired aliases, since the resolver honours both and a reused alias would
    make an old payment ambiguous all over again.
    """
    from models import Unit, UnitPayCodeAlias

    unit_query = db.session.query(Unit.id).filter(
        Unit.landlord_id == landlord_id,
        Unit.pay_code == code,
        Unit.is_deleted.is_(False),
    )
    if exclude_unit_id is not None:
        unit_query = unit_query.filter(Unit.id != exclude_unit_id)
    if unit_query.first() is not None:
        return False

    alias_query = db.session.query(UnitPayCodeAlias.id).filter(
        UnitPayCodeAlias.landlord_id == landlord_id,
        UnitPayCodeAlias.old_code == code,
    )
    if exclude_unit_id is not None:
        alias_query = alias_query.filter(UnitPayCodeAlias.unit_id != exclude_unit_id)
    return alias_query.first() is None


def assign(unit, requested=None, *, landlord_id: int | None = None):
    """
    Set or change a unit's pay-code, filing the previous one as an alias.

    Duplicates are HARD-BLOCKED rather than silently suffixed: if an owner
    thinks two units share a code, payments for one of them are about to go to
    the other, and quietly renaming theirs would hide that.
    """
    from models import UnitPayCodeAlias

    landlord_id = landlord_id or unit.landlord_id
    code = normalise(requested) or propose(unit)

    if code == unit.pay_code:
        return unit.pay_code

    if not is_available(landlord_id, code, exclude_unit_id=unit.id):
        raise ApiError(
            f"The pay code '{code}' is already in use on this account.",
            status=409, errors={"pay_code": "duplicate"}, code="pay_code_duplicate",
        )

    previous = unit.pay_code
    unit.pay_code = code
    if previous:
        db.session.add(UnitPayCodeAlias(
            unit_id=unit.id, landlord_id=landlord_id, old_code=previous,
        ))
    db.session.flush()
    return code


def resolve_unit(landlord_id: int, reference: str):
    """
    The unit a reference names — current code first, then retired aliases.

    Returns None when nothing matches, which the resolver turns into suspense
    rather than a guess.
    """
    from models import Unit, UnitPayCodeAlias

    code = re.sub(r"\s+", "", str(reference or "")).upper()
    if not code:
        return None

    unit = (
        db.session.query(Unit)
        .filter(Unit.landlord_id == landlord_id,
                Unit.pay_code == code,
                Unit.is_deleted.is_(False))
        .first()
    )
    if unit is not None:
        return unit

    alias = (
        db.session.query(UnitPayCodeAlias)
        .filter(UnitPayCodeAlias.landlord_id == landlord_id,
                UnitPayCodeAlias.old_code == code)
        .order_by(UnitPayCodeAlias.retired_at.desc())
        .first()
    )
    if alias is None:
        return None
    unit = db.session.get(Unit, alias.unit_id)
    return unit if unit is not None and not unit.is_deleted else None


def backfill_account(landlord_id: int) -> int:
    """Give every code-less unit on an account a proposed code. Returns the count."""
    from models import Property, Unit

    units = (
        db.session.query(Unit)
        .join(Property, Property.id == Unit.property_id)
        .filter(Property.landlord_id == landlord_id,
                Unit.is_deleted.is_(False),
                Unit.pay_code.is_(None))
        .all()
    )
    for unit in units:
        candidate = propose(unit)
        if is_available(landlord_id, candidate, exclude_unit_id=unit.id):
            unit.pay_code = candidate
    db.session.flush()
    return len(units)
