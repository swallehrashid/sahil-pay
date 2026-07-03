"""
routes/property_group_routes.py — Property Groupings & Manager Assignments
Blueprint: group_bp  |  Prefix: /api/property-groups

Covers §4.10 (property groupings) and §4.5 (manager assignments).
Groups are optional organisational containers for properties.
A manager (TeamMember) can be scoped to a unit, property, or group
via the manager_assignments table.
"""

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    PropertyGroup, Property, ManagerAssignment,
    TeamMember, ManagerScopeType,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit

group_bp = Blueprint("property_groups", __name__, url_prefix="/api/property-groups")


# ---------------------------------------------------------------------------
# GET /api/property-groups/
# ---------------------------------------------------------------------------
@group_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("groups", "view")
def list_groups():
    """
    List all property groups for the current landlord with property counts
    and assigned manager information.
    ---
    tags: [Property Groups]
    security:
      - Bearer: []
    responses:
      200: {description: List of groups.}
    """
    landlord_id = get_current_landlord_id()

    groups = PropertyGroup.query.filter_by(landlord_id=landlord_id).all()

    result = []
    for g in groups:
        d = g.to_dict()
        d["property_count"] = Property.query.filter_by(
            property_group_id=g.id, is_deleted=False
        ).count()
        # Managers assigned at group scope
        assignments = ManagerAssignment.query.filter_by(
            property_group_id=g.id, scope_type=ManagerScopeType.group.value
        ).all()
        d["managers"] = [
            {
                "team_member_id": a.team_member_id,
                "team_member_name": _tm_name(a.team_member_id),
            }
            for a in assignments
        ]
        result.append(d)

    return jsonify({"groups": result, "total": len(result)}), 200


# ---------------------------------------------------------------------------
# POST /api/property-groups/
# ---------------------------------------------------------------------------
@group_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("groups", "edit")
def create_group():
    """
    Create a property group and optionally attach properties to it.
    Body: { name: str, property_ids: [int] }
    ---
    tags: [Property Groups]
    security:
      - Bearer: []
    responses:
      201: {description: Group created.}
      400: {description: Name required.}
    """
    landlord_id  = get_current_landlord_id()
    data         = request.get_json(silent=True) or {}
    name         = (data.get("name") or "").strip()
    property_ids = data.get("property_ids", [])

    if not name:
        return jsonify({"error": "Group name is required."}), 400

    group = PropertyGroup(landlord_id=landlord_id, name=name)
    db.session.add(group)
    db.session.flush()

    # Attach properties
    if property_ids:
        props = Property.query.filter(
            Property.id.in_(property_ids),
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
        ).all()
        for p in props:
            p.property_group_id = group.id

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_property_group",
        entity_type="property",
        entity_id=group.id,
        description=f"Property group '{group.name}' created.",
        after_data=group.to_dict(),
    )
    db.session.commit()

    d = group.to_dict()
    d["property_count"] = len(property_ids)
    return jsonify(d), 201


# ---------------------------------------------------------------------------
# PUT /api/property-groups/<id>
# ---------------------------------------------------------------------------
@group_bp.route("/<int:group_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("groups", "edit")
def update_group(group_id):
    """
    Update a group's name and/or its attached properties.
    Sends the full desired list of property_ids — any property
    currently in the group but not in the list is detached.
    ---
    tags: [Property Groups]
    security:
      - Bearer: []
    responses:
      200: {description: Group updated.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    group       = _get_group_or_404(landlord_id, group_id)
    data        = request.get_json(silent=True) or {}
    before      = group.to_dict()

    if "name" in data:
        group.name = data["name"]

    if "property_ids" in data:
        new_ids = set(data["property_ids"])
        # Detach all current members then re-attach desired set
        Property.query.filter_by(property_group_id=group.id).update(
            {"property_group_id": None}
        )
        if new_ids:
            Property.query.filter(
                Property.id.in_(new_ids),
                Property.landlord_id == landlord_id,
            ).update({"property_group_id": group.id}, synchronize_session=False)

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_property_group",
        entity_type="property",
        entity_id=group.id,
        description=f"Property group '{group.name}' updated.",
        before_data=before,
        after_data=group.to_dict(),
    )
    db.session.commit()

    return jsonify(group.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/property-groups/<id>
# ---------------------------------------------------------------------------
@group_bp.route("/<int:group_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("groups", "edit")
def delete_group(group_id):
    """
    Delete a property group. Properties inside are detached (not deleted).
    Manager assignments scoped to this group are also removed.
    ---
    tags: [Property Groups]
    security:
      - Bearer: []
    responses:
      200: {description: Group deleted.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    group       = _get_group_or_404(landlord_id, group_id)

    # Detach properties
    Property.query.filter_by(property_group_id=group.id).update({"property_group_id": None})
    # Remove manager assignments at group scope
    ManagerAssignment.query.filter_by(property_group_id=group.id).delete()

    db.session.delete(group)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_property_group",
        entity_type="property",
        entity_id=group_id,
        description=f"Property group '{group.name}' deleted.",
    )
    db.session.commit()

    return jsonify({"message": f"Group '{group.name}' deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/property-groups/<id>/assign-manager
# ---------------------------------------------------------------------------
@group_bp.route("/<int:group_id>/assign-manager", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("groups", "edit")
def assign_manager(group_id):
    """
    Assign a team member as manager scoped to a unit, property, or the whole group.
    Body: { team_member_id, scope_type: 'unit'|'property'|'group',
            unit_id?: int, property_id?: int }
    Exactly one of unit_id / property_id must be supplied for those scope types.
    ---
    tags: [Property Groups]
    security:
      - Bearer: []
    responses:
      201: {description: Manager assigned.}
      400: {description: Validation error.}
      404: {description: Group or team member not found.}
    """
    landlord_id    = get_current_landlord_id()
    group          = _get_group_or_404(landlord_id, group_id)
    data           = request.get_json(silent=True) or {}

    team_member_id = data.get("team_member_id")
    scope_type     = data.get("scope_type", ManagerScopeType.group.value)

    if not team_member_id:
        return jsonify({"error": "team_member_id is required."}), 400
    if scope_type not in [s.value for s in ManagerScopeType]:
        return jsonify({"error": f"scope_type must be one of: unit, property, group."}), 400

    # Validate team member belongs to this landlord
    tm = TeamMember.query.filter_by(id=team_member_id, landlord_id=landlord_id).first()
    if not tm:
        return jsonify({"error": "Team member not found."}), 404

    unit_id     = data.get("unit_id")     if scope_type == ManagerScopeType.unit.value     else None
    property_id = data.get("property_id") if scope_type == ManagerScopeType.property.value else None
    pg_id       = group.id                if scope_type == ManagerScopeType.group.value     else None

    assignment = ManagerAssignment(
        team_member_id    = team_member_id,
        scope_type        = scope_type,
        unit_id           = unit_id,
        property_id       = property_id,
        property_group_id = pg_id,
    )
    db.session.add(assignment)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="assign_manager",
        entity_type="property",
        entity_id=group.id,
        description=f"Team member {tm.username} assigned as manager (scope: {scope_type}).",
        after_data=assignment.to_dict(),
    )
    db.session.commit()

    return jsonify(assignment.to_dict()), 201


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_group_or_404(landlord_id: int, group_id: int) -> PropertyGroup:
    g = PropertyGroup.query.filter_by(id=group_id, landlord_id=landlord_id).first()
    if not g:
        abort(404, description="Property group not found.")
    return g


def _tm_name(team_member_id: int) -> str:
    tm = TeamMember.query.get(team_member_id)
    if not tm:
        return ""
    return f"{tm.first_name or ''} {tm.last_name or ''}".strip() or tm.username