"""
services/phone_service.py — one Kenyan number, one stored form.

0712 430 742, 0712430742, 712430742, 254712430742 and +254 712 430 742 are the
same line. Every phone number the system saves is stored as 254XXXXXXXXX
(12 digits, no plus, no spaces), which is also the form the SMS provider is
sent. Lookups compare the last nine digits, so a tenant signing in with 07…
finds a record saved as 254… and the reverse.

The rule, stated once:
    accepted   07XXXXXXXX, 01XXXXXXXX, 7XXXXXXXX, 1XXXXXXXX,
               2547XXXXXXXX, 2541XXXXXXXX (with or without +, spaces, dashes)
    stored     2547XXXXXXXX / 2541XXXXXXXX
    rejected   anything else — including non-Kenyan numbers
"""

from __future__ import annotations

import re

_VALID = re.compile(r"^254[17]\d{8}$")

INVALID_MESSAGE = ("Enter a Kenyan mobile number, e.g. 0712 345 678 or 254712345678.")


def canonical_phone(raw) -> str | None:
    """The 254XXXXXXXXX form of *raw*, or None when it is not a Kenyan mobile number."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10 and digits.startswith("0"):
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    return digits if _VALID.match(digits) else None


def phone_key(raw) -> str | None:
    """Comparison key: the nine-digit subscriber number."""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[-9:] if len(digits) >= 9 else None


def phone_matches(column, raw):
    """SQL clause: *column* holds the same number as *raw*, however either was typed."""
    from extensions import db

    key = phone_key(raw)
    if key is None:
        return db.false()
    return db.func.right(db.func.regexp_replace(column, r"\D", "", "g"), 9) == key


def dialable(raw) -> str:
    """What to hand the SMS provider: the canonical form when *raw* is Kenyan,
    else its digits unchanged."""
    return canonical_phone(raw) or re.sub(r"\D", "", str(raw or ""))
