"""
services/team_preset_service.py — team-member role presets.

A property manager running 100+ properties creates hundreds of team members
(one owner login per property, two caretakers per block, plus office staff).
Hand-ticking a 12-module × view/edit matrix for each is unusable at that scale,
so a preset pre-fills the matrix and the property scope.

Presets are SHORTCUTS, never a ceiling: after applying one, every module
permission and every property assignment remains individually editable, which is
the whole point of the permission matrix (the landlord must be able to grant or
hide anything, finely). Nothing in the permission checks
(utils.require_permission / decorators._check_permission) consults the preset —
it is a labelling + bootstrap convenience only, and the
team_member_permissions rows stay the single source of truth for access.

This module is the ONE definition of the presets; the frontend fetches it from
GET /api/team/presets rather than keeping its own copy, so the two can never
drift apart.
"""

from __future__ import annotations

from services.report_access import OWNER_DEFAULT_REPORTS

# Permission modules (models.PermissionModule) each preset grants.
#   "edit" implies view (the app-level rule in TeamMemberPermission's docstring
#   and set_permissions(): can_edit=True forces can_view=True).
#
# scope:
#   "specific" — the member MUST be restricted to named properties. The UI
#                forces a property selection and disables "all properties"; an
#                owner who could see every property under the manager would be
#                reading their competitors' books.
#   "all"      — defaults to all properties, freely narrowed afterwards.
PRESETS: dict[str, dict] = {
    "owner": {
        "label": "Owner (view only)",
        "description": (
            "A property owner whose block you manage. Sees everything about "
            "their own properties and can change nothing."
        ),
        "role": "viewer",
        "scope": "specific",
        "view": [
            "properties", "units", "tenants", "payments",
            "invoices", "reports", "expenses", "maintenance",
            # Their own tenancy agreements and the notices they receive. NOT
            # penalties: chasing a late fee is the managing agent's job, and an
            # owner seeing it invites them to contact the tenant directly.
            "leases", "notifications",
        ],
        "edit": [],
        # `reports` on its own would hand an owner the payments report and the
        # portfolio comparatives alongside their statement. Narrow it to the one
        # report the login exists for; the landlord can tick more per member.
        "reports": list(OWNER_DEFAULT_REPORTS),
    },
    "caretaker": {
        "label": "Caretaker",
        "description": (
            "On-site caretaker. Records utility readings for their own "
            "properties and nothing else."
        ),
        "role": "editor",
        "scope": "specific",
        # `properties` view is not optional decoration: the Utilities page asks
        # which block a meter is in, so without it the property dropdown is
        # empty and a reading cannot be recorded at all. Property SCOPE still
        # limits them to their own blocks, so this reveals nothing extra.
        # Notifications are view-only — a caretaker is told about a maintenance
        # job, but does not broadcast to tenants.
        "view": ["units", "tenants", "properties", "notifications"],
        "edit": ["utilities", "unit_utilities"],
    },
    "accountant": {
        "label": "Accountant",
        "description": (
            "Handles money: records payments, raises invoices, books expenses "
            "and pulls reports."
        ),
        "role": "editor",
        "scope": "all",
        "view": ["tenants", "properties", "units", "leases"],
        # Penalties are money owed, so they belong with the rest of the ledger
        # this role already runs.
        "edit": ["payments", "invoices", "expenses", "reports",
                 "penalties", "notifications"],
    },
    "secretary": {
        "label": "Secretary",
        "description": (
            "Front-office: manages tenant records, messages and maintenance "
            "requests."
        ),
        "role": "editor",
        "scope": "all",
        "view": ["units", "properties"],
        # The front office issues tenancy agreements and sends the notices, so
        # both are edit here — this is the role the missing `notifications`
        # module was blocking most visibly.
        "edit": ["tenants", "messages", "maintenance", "leases", "notifications"],
    },
    "custom": {
        "label": "Custom",
        "description": "Start from an empty matrix and grant exactly what you choose.",
        "role": None,
        "scope": "all",
        "view": [],
        "edit": [],
    },
}

VALID_PRESETS = tuple(PRESETS.keys())


def normalise_preset(value) -> str | None:
    """The stored preset key for a client-supplied value, or None when absent/unknown."""
    if not value:
        return None
    key = str(value).strip().lower()
    return key if key in PRESETS else None


def allowed_reports_for(preset: str) -> list[str] | None:
    """
    Which reports a preset grants, or None for "every report".

    Only the owner preset narrows this today. Staff roles keep None, because an
    accountant pulling a month-on-month is doing their job.
    """
    spec = PRESETS.get(preset) or {}
    return spec.get("reports")


def permission_rows_for(preset: str) -> list[dict]:
    """
    The [{module, can_view, can_edit}] a preset grants — the exact shape
    PUT /api/team/<id>/permissions accepts, so the frontend can send it straight
    back after letting the landlord tweak it.
    """
    spec = PRESETS.get(preset)
    if not spec:
        return []

    rows: dict[str, dict] = {}
    for module in spec["view"]:
        rows[module] = {"module": module, "can_view": True, "can_edit": False}
    for module in spec["edit"]:
        # edit implies view — mirrors set_permissions()'s own normalisation.
        rows[module] = {"module": module, "can_view": True, "can_edit": True}

    # null on the reports row means every report; a preset may narrow it.
    if "reports" in rows:
        rows["reports"]["allowed_reports"] = spec.get("reports")
    return list(rows.values())


def apply_preset_permissions(team_member, preset: str) -> list:
    """
    Replace *team_member*'s permission rows with the preset's grant.
    Flushes but does NOT commit — the caller owns the transaction, matching
    every other service here.
    """
    from extensions import db
    from models import TeamMemberPermission

    rows = permission_rows_for(preset)
    if not rows:
        return []

    TeamMemberPermission.query.filter_by(team_member_id=team_member.id).delete()

    created = []
    for row in rows:
        perm = TeamMemberPermission(
            team_member_id=team_member.id,
            module=row["module"],
            can_view=row["can_view"],
            can_edit=row["can_edit"],
            allowed_reports=row.get("allowed_reports"),
        )
        db.session.add(perm)
        created.append(perm)

    db.session.flush()
    return created


def to_public_list() -> list[dict]:
    """The preset catalogue for the client (GET /api/team/presets)."""
    return [
        {
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "role": spec["role"],
            "scope": spec["scope"],
            "permissions": permission_rows_for(key),
        }
        for key, spec in PRESETS.items()
    ]
