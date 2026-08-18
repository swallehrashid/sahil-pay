"""
services/report_access.py — WHICH reports a team member may open.

`reports: view/edit` is too blunt a grant. The reports module contains, in one
bucket: a property statement an owner is entitled to, and the payments report,
arrears list and month-on-month figures for the whole managed portfolio. A
property manager who wants to give an owner their own statement had to hand over
all of it, so in practice they gave owners nothing and mailed PDFs instead.

So the `reports` permission row carries a second, finer grant:

    allowed_reports = NULL   -> every report (what every pre-existing row means)
    allowed_reports = [...]  -> only these keys
    allowed_reports = []     -> none

NULL and [] are deliberately different. Defaulting the column to [] would have
silently revoked reports from every existing member on deploy; NULL preserves
them, and an empty list stays available as a real "none" a landlord can choose.

Landlords, property managers and admins are never narrowed — this is a
delegation control, not a licence check.
"""

from __future__ import annotations

# The catalogue. Keys match the report the client asks for and the route that
# serves it, so a new report cannot quietly appear ungated: it must be added
# here to be grantable, and REPORT_ROUTE_KEYS maps the endpoint back to a key.
REPORTS = (
    ("payments",   "Payments",          "Every payment received, with method and reference."),
    ("tenant",     "Tenant statement",  "One tenant's full charge and payment history."),
    ("property",   "Property statement", "A block's income, expenses and what is owed to its owner."),
    ("arrears",    "Arrears",           "Who owes what, and for how long."),
    ("expenses",   "Expenses",          "Money spent on a property."),
    ("mom",        "Month-on-month",    "Collections compared across months."),
    ("yoy",        "Year-on-year",      "Collections compared across years."),
    ("grouping",   "Grouping",          "Totals rolled up by property group."),
    ("deleted",    "Deleted tenants",   "Tenants removed from the books, and their closing position."),
    ("penalties",  "Penalties",         "Late-payment charges raised and collected."),
    ("kra_monthly", "KRA monthly",      "The monthly rental income return figures."),
)

REPORT_KEYS = tuple(key for key, _label, _hint in REPORTS)

# What an owner-preset member gets by default: the statement for their own
# block and nothing else. They are not staff — the payments report and the
# portfolio-wide comparatives are the managing agent's business, not theirs.
OWNER_DEFAULT_REPORTS = ("property",)


def catalogue() -> list[dict]:
    """The list the permission UI renders as checkboxes."""
    return [{"key": key, "label": label, "description": hint}
            for key, label, hint in REPORTS]


def normalise(value) -> list[str] | None:
    """
    Sanitise an incoming allowed_reports value.

    None stays None ("every report"). A list is filtered to known keys — an
    unknown key is dropped rather than rejected, so renaming a report later
    cannot make an existing member's permission row unsaveable.
    """
    if value is None:
        return None
    if not isinstance(value, (list, tuple, set)):
        return None
    return [key for key in REPORT_KEYS if key in set(map(str, value))]


def allowed_for(user, *, report_key: str | None = None):
    """
    Either the set of report keys *user* may open, or — when *report_key* is
    given — whether they may open that one.

    Returns None for "no restriction", which callers must treat as "everything".
    """
    role = getattr(user, "role", None)
    if role in ("landlord", "property_manager", "system_admin"):
        return None if report_key is None else True

    member = getattr(user, "team_member_profile", None)
    if member is None:
        return set() if report_key is None else False

    row = next((p for p in member.permissions if p.module == "reports"), None)
    if row is None or not (row.can_view or row.can_edit):
        return set() if report_key is None else False

    if row.allowed_reports is None:
        return None if report_key is None else True

    permitted = set(row.allowed_reports)
    return permitted if report_key is None else (report_key in permitted)


def require(report_key: str) -> None:
    """
    Guard for a report endpoint. Raises ApiError(403) when this caller holds the
    reports module but not this particular report.
    """
    from utils import ApiError, get_jwt_user

    if allowed_for(get_jwt_user(), report_key=report_key):
        return
    raise ApiError(
        "You do not have access to this report.",
        status=403,
        code="report_not_permitted",
    )


def require_report(report_key: str):
    """
    Decorator form, applied UNDER @require_permission("reports", "view").

    Two checks rather than one because they answer different questions: the
    module grant decides whether this person does reporting at all, and this
    decides which of the reports they may open. Naming the key at the route
    keeps the mapping visible where the endpoint is defined, so a new report
    added without a key here fails closed at review rather than shipping
    ungated.
    """
    from functools import wraps

    if report_key not in REPORT_KEYS:
        raise ValueError(f"Unknown report key: {report_key!r}")

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            require(report_key)
            return view(*args, **kwargs)
        return wrapper

    return decorator
