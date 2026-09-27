"""
routes/lookup_routes.py — the complete option lists behind form dropdowns.
Blueprint: lookup_bp  |  Prefix: /api/lookups

The list endpoints (/api/properties, /api/units, /api/tenants) are paginated
for their pages — 20 rows at a time. Forms used to call those same endpoints to
fill their dropdowns and therefore only ever saw the first 20: at 100
properties and 1,000 tenants, the other 980 were impossible to pick or find.

These return EVERY row the caller may see, unpaginated, in the same row shape
and under the same key as the list endpoint, so a form swaps the hook and
nothing else. Scope is identical to the lists: the landlord's own, non-deleted
records, narrowed to the team member's accessible properties.

Access is deliberately broader than the owning module. A caretaker entering
meter readings holds `utilities`, not `properties`, and still has to pick a
property; the dropdown only needs the names. So any team member holding at
least one module may read property and unit options, and tenant options need
one of the modules that act on tenants.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy.orm import joinedload, selectinload

from decorators import get_current_landlord_id, require_landlord_or_team
from extensions import db
from models import Property, TeamMember, TeamMemberPermission, Tenant, Unit
from utils import ApiError, accessible_property_ids, get_jwt_user

lookup_bp = Blueprint("lookups", __name__, url_prefix="/api/lookups")

TENANT_MODULES = (
    "tenants", "payments", "invoices", "messages", "notifications", "leases",
    "maintenance", "utilities", "unit_utilities", "penalties", "reports",
)
TEAM_MODULES = ("messages", "notifications", "groups", "properties")


def _require_any_view(modules=None) -> None:
    """Owners pass; a team member needs view (or edit) on at least one of *modules*
    (any module at all when *modules* is None)."""
    user = get_jwt_user()
    if user.role != "team_member":
        return
    tm = user.team_member_profile
    if tm is None:
        raise ApiError("Team member profile not found.", status=403)
    q = db.session.query(TeamMemberPermission.id).filter(
        TeamMemberPermission.team_member_id == tm.id,
        db.or_(TeamMemberPermission.can_view.is_(True), TeamMemberPermission.can_edit.is_(True)),
    )
    if modules:
        q = q.filter(TeamMemberPermission.module.in_(modules))
    if q.first() is None:
        raise ApiError("You do not have access to this list.", status=403, code="no_module_permission")


@lookup_bp.route("/properties", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def property_options():
    _require_any_view()
    landlord_id = get_current_landlord_id()
    query = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(Property.id.in_(allowed))
    rows = [p.to_dict() for p in query.order_by(Property.name).all()]
    return jsonify({"properties": rows, "total": len(rows)}), 200


@lookup_bp.route("/units", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def unit_options():
    _require_any_view()
    landlord_id = get_current_landlord_id()
    query = (
        Unit.query
        .join(Property, Property.id == Unit.property_id)
        .options(joinedload(Unit.property))
        .filter(Property.landlord_id == landlord_id,
                Property.is_deleted.is_(False),
                Unit.is_deleted.is_(False))
    )
    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(Unit.property_id.in_(allowed))
    if prop_id := request.args.get("property_id", type=int):
        query = query.filter(Unit.property_id == prop_id)

    rows = []
    for u in query.order_by(Property.name, Unit.name).all():
        d = u.to_dict()
        d["property_name"] = u.property.name if u.property else None
        rows.append(d)
    return jsonify({"units": rows, "total": len(rows)}), 200


@lookup_bp.route("/tenants", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def tenant_options():
    _require_any_view(TENANT_MODULES)
    landlord_id = get_current_landlord_id()
    query = (
        Tenant.query
        .join(Unit, Unit.id == Tenant.unit_id)
        .join(Property, Property.id == Unit.property_id)
        .options(joinedload(Tenant.unit).joinedload(Unit.property))
        .filter(Tenant.landlord_id == landlord_id,
                Tenant.is_deleted.is_(False),
                Unit.is_deleted.is_(False),
                Property.is_deleted.is_(False))
    )
    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(Unit.property_id.in_(allowed))
    if prop_id := request.args.get("property_id", type=int):
        query = query.filter(Unit.property_id == prop_id)
    if unit_id := request.args.get("unit_id", type=int):
        query = query.filter(Tenant.unit_id == unit_id)

    rows = []
    for t in query.order_by(Tenant.first_name, Tenant.last_name).all():
        d = t.to_dict()
        d["unit_name"] = t.unit.name
        d["property_name"] = t.unit.property.name
        d["property_id"] = t.unit.property_id
        rows.append(d)
    return jsonify({"tenants": rows, "total": len(rows)}), 200


@lookup_bp.route("/team-members", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def team_member_options():
    _require_any_view(TEAM_MODULES)
    landlord_id = get_current_landlord_id()
    members = (
        TeamMember.query
        .options(selectinload(TeamMember.user))
        .filter_by(landlord_id=landlord_id)
        .order_by(TeamMember.first_name, TeamMember.username)
        .all()
    )
    rows = []
    for tm in members:
        d = tm.to_dict()
        d["email"] = tm.user.email if tm.user else None
        rows.append(d)
    return jsonify({"team_members": rows, "total": len(rows)}), 200
