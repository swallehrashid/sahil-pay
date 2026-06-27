"""
SahilPay — decorators.py
=========================
Route-facing security guards. The real logic already lives in utils.py
(require_role, require_permission, current_landlord_id, get_jwt_user) —
this module is the thin, route-facing surface that routes/*.py imports,
kept separate so routes stay decoupled from utils' internal organization.

Every route applies these AFTER @jwt_required():

    @bp.route("/...")
    @jwt_required()
    @require_landlord_or_team()
    @require_permission("properties", "view")
    def my_view(): ...
"""

from __future__ import annotations

from utils import (
    ApiError, current_landlord_id, get_jwt_user, require_permission, require_role,
    scope_to_accessible_properties,
)

__all__ = [
    "require_landlord_or_team",
    "require_permission",
    "get_current_landlord_id",
    "_check_permission",
    "scope_to_accessible_properties",
]


def require_landlord_or_team():
    """
    Decorator: allow landlord, property_manager, and team_member callers.
    system_admin is also allowed so an admin's impersonation session can
    reach landlord-scoped routes (current_landlord_id() resolves the
    impersonated landlord's id for them — see utils.active_impersonation).
    """
    return require_role("landlord", "property_manager", "team_member", "system_admin")


def get_current_landlord_id() -> int:
    """
    Resolve the effective landlord_id for this request, raising ApiError(403)
    if the caller has no landlord scope at all (e.g. a tenant, or a
    system_admin who isn't currently impersonating anyone). Every
    landlord-scoped route calls this exactly once, near the top of the
    handler, and filters its queries by the returned id.
    """
    landlord_id = current_landlord_id()
    if landlord_id is None:
        raise ApiError(
            "This action requires a landlord account.",
            status=403,
            code="no_landlord_scope",
        )
    return landlord_id


def _check_permission(module: str, action: str) -> None:
    """
    Non-decorator version of require_permission() — call inline when a
    single GET/PUT-style handler only needs the permission check on part of
    its body (e.g. PUT branches that mutate after a freely-readable GET).

    Mirrors require_permission()'s decorator body exactly: landlord /
    property_manager / system_admin pass through unconditionally; a
    team_member must have a team_member_permissions row for *module* with
    can_view (for "view") or can_edit (for "edit") set. Raises ApiError(403)
    on failure.
    """
    from extensions import db
    from models import TeamMemberPermission

    user = get_jwt_user()

    if user.role in ("landlord", "property_manager", "system_admin"):
        return

    if user.role != "team_member":
        raise ApiError("Access denied.", status=403, code="forbidden_role")

    tm = user.team_member_profile
    if tm is None:
        raise ApiError("Team member profile not found.", status=403)

    perm = (
        db.session.query(TeamMemberPermission)
        .filter(
            TeamMemberPermission.team_member_id == tm.id,
            TeamMemberPermission.module == module,
        )
        .first()
    )

    if perm is None:
        raise ApiError(
            f"You do not have access to the '{module}' module.",
            status=403,
            code="no_module_permission",
        )
    if action == "edit" and not perm.can_edit:
        raise ApiError(
            f"You do not have edit permission for '{module}'.",
            status=403,
            code="no_edit_permission",
        )
    if action == "view" and not (perm.can_view or perm.can_edit):
        raise ApiError(
            f"You do not have view permission for '{module}'.",
            status=403,
            code="no_view_permission",
        )
