"""
routes/teammember_routes.py — Team Member Session (Own-Account Routes)
Blueprint: teammember_bp  |  Prefix: /api/team-member

This is the THIN set of routes a team member uses for their own session.
It answers three questions the React RTK layer asks on login:
  1. What modules can I see/edit?  → GET /me/permissions
  2. Which properties can I access? → GET /me/property-access
  3. Who am I?                      → GET /me/profile

All other data (invoices, payments, tenants…) is served by the same
Landlord portal blueprints, gated by @require_permission on those routes.
The UI uses /me/permissions to hide nav items that are not accessible;
the backend enforces every rule independently — the UI hint is never
the security boundary.

A team member may update limited fields on their own profile:
first_name, last_name, phone.  They CANNOT change their email, role,
landlord, or permissions through these routes.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    TeamMember, TeamMemberPermission, TeamMemberPropertyAccess,
    Property, User, UserRole,
)
from services.audit_service import record_audit

teammember_bp = Blueprint("team_member", __name__, url_prefix="/api/team-member")


def _get_team_member_from_jwt() -> TeamMember | None:
    """
    Extract team_member_id from the JWT claims and load the TeamMember row.
    Returns None if the caller is not a team member.
    """
    claims = get_jwt()
    if claims.get("role") != UserRole.team_member.value:
        return None
    tm_id = claims.get("team_member_id")
    if not tm_id:
        return None
    return db.session.get(TeamMember, tm_id)


# ---------------------------------------------------------------------------
# GET /api/team-member/me/permissions
# ---------------------------------------------------------------------------
@teammember_bp.route("/me/permissions", methods=["GET"])
@jwt_required()
def get_my_permissions():
    """
    Return the full permission matrix for the authenticated team member.
    The React app uses this to show/hide navigation modules and
    enable/disable form fields.

    Response shape:
      { permissions: [{ module, can_view, can_edit }], property_access_all: bool }

    The backend still enforces every permission server-side — this
    endpoint only provides the UI hint.
    ---
    tags: [Team Member]
    security:
      - Bearer: []
    responses:
      200: {description: Permission matrix.}
      403: {description: Not a team member.}
    """
    tm = _get_team_member_from_jwt()
    if not tm:
        return jsonify({"error": "This endpoint is for team members only."}), 403

    permissions = [p.to_dict() for p in tm.permissions]

    # Build a convenient module→{can_view, can_edit} map for the frontend
    perm_map = {
        p["module"]: {"can_view": p["can_view"], "can_edit": p["can_edit"]}
        for p in permissions
    }

    return jsonify({
        "permissions":        permissions,
        "permission_map":     perm_map,
        "property_access_all": tm.property_access_all,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/team-member/me/property-access
# ---------------------------------------------------------------------------
@teammember_bp.route("/me/property-access", methods=["GET"])
@jwt_required()
def get_my_property_access():
    """
    Return the list of properties this team member is allowed to access.

    If property_access_all=True: returns all non-deleted properties for
    the landlord (the @scope_to_accessible_properties decorator on data
    routes already handles this, but the UI needs the full list for
    property selectors / dropdown scoping).

    If property_access_all=False: returns only the explicitly granted
    properties from team_member_property_access.
    ---
    tags: [Team Member]
    security:
      - Bearer: []
    responses:
      200: {description: Accessible property list.}
      403: {description: Not a team member.}
    """
    tm = _get_team_member_from_jwt()
    if not tm:
        return jsonify({"error": "This endpoint is for team members only."}), 403

    if tm.property_access_all:
        props = Property.query.filter_by(
            landlord_id=tm.landlord_id, is_deleted=False
        ).order_by(Property.name).all()
        property_list = [{"id": p.id, "name": p.name, "city": p.city} for p in props]
    else:
        accesses  = TeamMemberPropertyAccess.query.filter_by(team_member_id=tm.id).all()
        prop_ids  = [a.property_id for a in accesses]
        props     = Property.query.filter(
            Property.id.in_(prop_ids),
            Property.is_deleted.is_(False),
        ).order_by(Property.name).all()
        property_list = [{"id": p.id, "name": p.name, "city": p.city} for p in props]

    return jsonify({
        "property_access_all": tm.property_access_all,
        "properties":          property_list,
        "total":               len(property_list),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/team-member/me/profile
# ---------------------------------------------------------------------------
@teammember_bp.route("/me/profile", methods=["GET"])
@jwt_required()
def get_my_profile():
    """
    Return the authenticated team member's own profile.
    Includes the user-level email and their role/landlord_id.
    ---
    tags: [Team Member]
    security:
      - Bearer: []
    responses:
      200: {description: Own profile.}
      403: {description: Not a team member.}
    """
    tm = _get_team_member_from_jwt()
    if not tm:
        return jsonify({"error": "This endpoint is for team members only."}), 403

    d = tm.to_dict()
    # Attach user-level fields the frontend needs
    if tm.user:
        d["email"]       = tm.user.email
        d["is_verified"] = tm.user.is_verified
        d["is_active"]   = tm.user.is_active

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/team-member/me/profile
# ---------------------------------------------------------------------------
@teammember_bp.route("/me/profile", methods=["PUT"])
@jwt_required()
def update_my_profile():
    """
    Update limited fields on the team member's own profile.

    Allowed fields: first_name, last_name, phone.
    NOT allowed (rejected silently): role, landlord_id, permissions,
    property_access_all, email (contact landlord to change).

    Password changes go through /api/auth/reset-password.
    ---
    tags: [Team Member]
    security:
      - Bearer: []
    responses:
      200: {description: Profile updated.}
      403: {description: Not a team member.}
    """
    tm   = _get_team_member_from_jwt()
    if not tm:
        return jsonify({"error": "This endpoint is for team members only."}), 403

    data   = request.get_json(silent=True) or {}
    before = tm.to_dict()

    # Strictly limit to safe fields only — anything else is ignored
    for field in ("first_name", "last_name", "phone"):
        if field in data:
            setattr(tm, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=tm.landlord_id,
        action="update_team_member_profile",
        entity_type="team_member",
        entity_id=tm.id,
        description=f"Team member '{tm.username}' updated their own profile.",
        before_data=before,
        after_data=tm.to_dict(),
    )
    db.session.commit()

    d = tm.to_dict()
    if tm.user:
        d["email"] = tm.user.email
    return jsonify(d), 200