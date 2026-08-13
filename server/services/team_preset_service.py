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
        ],
        "edit": [],
    },
    "caretaker": {
        "label": "Caretaker",
        "description": (
            "On-site caretaker. Records utility readings for their own "
            "properties and nothing else."
        ),
        "role": "editor",
        "scope": "specific",
        "view": ["units", "tenants"],
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
        "view": ["tenants", "properties", "units"],
        "edit": ["payments", "invoices", "expenses", "reports"],
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
        "edit": ["tenants", "messages", "maintenance"],
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
