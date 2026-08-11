"""
routes/unit_routes.py — Unit Management
Blueprint: unit_bp  |  Prefix: /api/units

CRUD for Unit records.  Soft-delete only.
tax_rate is optional on create — when NULL it inherits from the parent Property.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, abort, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Unit, Property
from decorators import (
    accessible_property_ids,
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service import record_audit

unit_bp = Blueprint("units", __name__, url_prefix="/api/units")


# ---------------------------------------------------------------------------
# GET /api/units/
# ---------------------------------------------------------------------------
@unit_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "view")
@scope_to_accessible_properties
def list_units():
    """
    List all non-deleted units for the current landlord.
    Returns a summary (total_properties, total_units, total_vacancies).

    Filters: ?property_id=, ?is_occupied=(true|false), ?page=, ?per_page=
    ---
    tags: [Units]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated unit list + summary.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)
    prop_filter = request.args.get("property_id", type=int)
    occ_filter  = request.args.get("is_occupied", "").lower()

    query = (
        Unit.query
        .join(Property, Property.id == Unit.property_id)
        .filter(
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
            Unit.is_deleted.is_(False),
        )
    )

    if g.accessible_property_ids is not None:
        query = query.filter(Unit.property_id.in_(g.accessible_property_ids))

    if prop_filter:
        query = query.filter(Unit.property_id == prop_filter)
    if occ_filter == "true":
        query = query.filter(Unit.is_occupied.is_(True))
    elif occ_filter == "false":
        query = query.filter(Unit.is_occupied.is_(False))

    # Summary
    total_units     = query.count()
    total_vacancies = query.filter(Unit.is_occupied.is_(False)).count()

    paginated = query.order_by(Unit.property_id, Unit.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for u in paginated.items:
        d              = u.to_dict()
        d["property_name"] = u.property.name if u.property else None
        # Resolve effective tax rate
        d["effective_tax_rate"] = float(u.tax_rate) if u.tax_rate is not None \
            else (float(u.property.tax_rate) if u.property else None)
        items.append(d)

    return jsonify({
        "summary": {
            "total_units":     total_units,
            "total_vacancies": total_vacancies,
        },
        "units":        items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/units/
# ---------------------------------------------------------------------------
@unit_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "edit")
def create_unit():
    """
    Create a new unit.
    Required: property_id, name, rent_amount.
    Optional: tax_rate (inherits property when omitted), notes.
    ---
    tags: [Units]
    security:
      - Bearer: []
    responses:
      201: {description: Unit created.}
      400: {description: Validation error or duplicate name within property.}
      404: {description: Property not found.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    property_id = data.get("property_id")
    name        = (data.get("name") or "").strip()
    rent_amount = data.get("rent_amount")

    if not property_id or not name or rent_amount is None:
        return jsonify({"error": "property_id, name, and rent_amount are required."}), 400

    prop = Property.query.filter_by(
        id=property_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not prop:
        return jsonify({"error": "Property not found."}), 404

    # Uniqueness within property
    if Unit.query.filter_by(property_id=property_id, name=name, is_deleted=False).first():
        return jsonify({"error": f"Unit '{name}' already exists in this property."}), 400

    unit = Unit(
        property_id = property_id,
        name        = name,
        rent_amount = rent_amount,
        tax_rate    = data.get("tax_rate"),
        notes       = data.get("notes"),
        is_occupied = False,
    )
    db.session.add(unit)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_unit",
        entity_type="unit",
        entity_id=unit.id,
        description=f"Unit '{unit.name}' created in property '{prop.name}'.",
        after_data=unit.to_dict(),
    )
    db.session.commit()

    return jsonify(unit.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/units/<id>
# ---------------------------------------------------------------------------
@unit_bp.route("/<int:unit_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "view")
@scope_to_accessible_properties
def get_unit(unit_id):
    """
    Return detail for a single unit including property name and tenant info.
    ---
    tags: [Units]
    security:
      - Bearer: []
    responses:
      200: {description: Unit detail.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    unit        = _get_or_404(landlord_id, unit_id)

    d = unit.to_dict()
    d["property_name"]    = unit.property.name if unit.property else None
    d["effective_tax_rate"] = float(unit.tax_rate) if unit.tax_rate is not None \
        else (float(unit.property.tax_rate) if unit.property else None)
    # Current active tenant
    active_tenant = next(
        (t for t in unit.tenants if not t.is_deleted and not t.move_out_date), None
    )
    d["current_tenant"] = active_tenant.to_dict() if active_tenant else None

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/units/<id>
# ---------------------------------------------------------------------------
@unit_bp.route("/<int:unit_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "edit")
def update_unit(unit_id):
    """
    Update an existing unit's fields (partial update — only present keys are changed).
    ---
    tags: [Units]
    security:
      - Bearer: []
    responses:
      200: {description: Unit updated.}
      400: {description: Duplicate name.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    unit        = _get_or_404(landlord_id, unit_id)
    data        = request.get_json(silent=True) or {}
    before      = unit.to_dict()

    # Name uniqueness check if name is being changed
    if "name" in data and data["name"] != unit.name:
        if Unit.query.filter_by(
            property_id=unit.property_id, name=data["name"], is_deleted=False
        ).first():
            return jsonify({"error": f"Unit '{data['name']}' already exists in this property."}), 400

    for field in ["name", "rent_amount", "tax_rate", "notes"]:
        if field in data:
            setattr(unit, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_unit",
        entity_type="unit",
        entity_id=unit.id,
        description=f"Unit '{unit.name}' updated.",
        before_data=before,
        after_data=unit.to_dict(),
    )
    db.session.commit()

    return jsonify(unit.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/units/<id>  (soft delete)
# ---------------------------------------------------------------------------
@unit_bp.route("/<int:unit_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "edit")
def delete_unit(unit_id):
    """
    Soft-delete a unit.
    ---
    tags: [Units]
    security:
      - Bearer: []
    responses:
      200: {description: Unit soft-deleted.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    unit        = _get_or_404(landlord_id, unit_id)
    before      = unit.to_dict()

    unit.is_deleted = True
    unit.deleted_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_unit",
        entity_type="unit",
        entity_id=unit.id,
        description=f"Unit '{unit.name}' soft-deleted.",
        before_data=before,
    )
    db.session.commit()

    return jsonify({"message": f"Unit '{unit.name}' has been deleted."}), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, unit_id: int) -> Unit:
    unit = (
        Unit.query
        .join(Property, Property.id == Unit.property_id)
        .filter(
            Unit.id == unit_id,
            Property.landlord_id == landlord_id,
            Unit.is_deleted.is_(False),
        )
    )
    # Property scope: a team member restricted to specific properties must not
    # be able to open an object from another property by guessing its id — under
    # a property manager that is one owner reading a rival owner's records. This
    # resolves the caller's scope on demand, so it holds even on routes that
    # never applied @scope_to_accessible_properties.
    allowed = accessible_property_ids()
    if allowed is not None:
        unit = unit.filter(Unit.property_id.in_(allowed))
    unit = unit.first()
    if not unit:
        abort(404, description="Unit not found or access denied.")
    accessible = getattr(g, "accessible_property_ids", None)
    if accessible is not None and unit.property_id not in accessible:
        abort(404, description="Unit not found or access denied.")
    return unit