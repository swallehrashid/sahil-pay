"""
services/search.py — one search rule for every search box in Sahil Pay.

WHY THIS EXISTS
---------------
Every list used to search with a single pattern: `first_name ILIKE '%Alex
Kirui%'`, then `last_name ILIKE '%Alex Kirui%'`. A first name never contains a
space-separated surname, so the moment somebody typed a space the search found
nothing — "Alex" worked, "Alex Kirui" did not.

THE RULE
--------
The text is split into words, and EVERY word must match SOME column. So
"Alex Kirui", "Kirui Alex", "alex kir" and "Kirui 0712" all find Alex Kirui,
and adding a word only ever narrows the result — which is what people expect a
search box to do.

A word that looks like a phone number also matches phones stored as 254…: a
tenant reading "0712 345 678" off their phone means the same digits.
"""

from __future__ import annotations

import re

from extensions import db


def words(text: str | None) -> list[str]:
    """The search terms: split on any whitespace, empty pieces dropped."""
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _phone_digits_clause(digits: str, phone_columns):
    tail = digits[1:] if digits.startswith("0") else digits
    if tail.startswith("254"):
        tail = tail[3:]
    return [db.func.regexp_replace(col, r"\D", "", "g").ilike(f"%{tail}%") for col in phone_columns]


def match_all_words(text: str | None, columns, phone_columns=()):
    """
    A filter clause: every word in *text* matches at least one of *columns*.

    Returns None when there is nothing to search for, so a caller can write
    `if clause is not None: query = query.filter(clause)`.

    A run of digits split by spaces ("0712 345 678") is also tried as ONE
    phone number against *phone_columns*, so typing a phone the way it is read
    aloud still finds it.
    """
    terms = words(text)
    if not terms:
        return None

    clauses = []
    for term in terms:
        like = f"%{_escape_like(term)}%"
        options = [col.ilike(like, escape="\\") for col in columns]
        digits = re.sub(r"\D", "", term)
        if phone_columns and len(digits) >= 3 and digits == term.lstrip("+"):
            options += _phone_digits_clause(digits, phone_columns)
        clauses.append(db.or_(*options))

    whole = db.and_(*clauses)

    # "0712 345 678": each chunk alone is too short to mean much, but together
    # they are a phone number.
    joined = re.sub(r"\D", "", text or "")
    if phone_columns and len(terms) > 1 and len(joined) >= 6 and \
            re.fullmatch(r"[\d\s+]+", (text or "").strip()):
        return db.or_(whole, *_phone_digits_clause(joined, phone_columns))
    return whole
