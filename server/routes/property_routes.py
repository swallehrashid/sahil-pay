"""
routes/property_routes.py — Property Management
Blueprint: property_bp  |  Prefix: /api/properties

CRUD for Property records plus the ability to add units directly
from the property page.  All writes are audit-logged.  Deletes
are soft (is_deleted = True) — the DB never loses property history.

Accessible by landlords and team members with the 'properties'
permission enabled.
"""

from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required

from extensions import db
from models import Property, Unit, ManagerAssignment
from decorators import (
    require_landlord_or_team,
    require_permission,
    get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service import record_audit
from datetime import datetime

property_bp = Blueprint("properties", __name__, url_prefix="/api/properties")


# ---------------------------------------------------------------------------
# GET /api/properties/
# ---------------------------------------------------------------------------
@property_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
@scope_to_accessible_properties
def list_properties():
    """
    List all active properties for the current landlord.
    Returns a summary (total_properties, total_units, total_vacancies)
    plus a paginated table.

    Filters: ?city=, ?name=, ?page=, ?per_page=
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated property list + summary.}
    """
    landlord_id = get_current_landlord_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    city     = request.args.get("city", "").strip()
    name     = request.args.get("name", "").strip()

    query = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    all_props_query = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    unit_totals_query = (
        db.session.query(
            db.func.count(Unit.id).label("total"),
            db.func.sum(
                db.cast(db.and_(Unit.is_occupied.is_(False), Unit.is_deleted.is_(False)), db.Integer)
            ).label("vacancies"),
        )
        .join(Property, Property.id == Unit.property_id)
        .filter(Property.landlord_id == landlord_id, Property.is_deleted.is_(False))
    )

    # Property-scoped team members (property_access_all=False) only ever see
    # their assigned subset — applied to both the list and its summary so the
    # numbers shown always match what's actually browsable.
    if g.accessible_property_ids is not None:
        query = query.filter(Property.id.in_(g.accessible_property_ids))
        all_props_query = all_props_query.filter(Property.id.in_(g.accessible_property_ids))
        unit_totals_query = unit_totals_query.filter(Property.id.in_(g.accessible_property_ids))

    if city:
        query = query.filter(Property.city.ilike(f"%{city}%"))
    if name:
        query = query.filter(Property.name.ilike(f"%{name}%"))

    # Summary aggregates
    total_properties = all_props_query.count()
    unit_totals = unit_totals_query.first()
    total_units     = unit_totals.total     or 0
    total_vacancies = unit_totals.vacancies or 0

    paginated = query.order_by(Property.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Unit counts and manager assignments for the whole page in two queries
    # rather than three per row — at 100 properties that was the difference
    # between 6 queries and 300.
    page_ids = [p.id for p in paginated.items]

    unit_counts = {}
    if page_ids:
        for row in (
            db.session.query(
                Unit.property_id,
                db.func.count(Unit.id).label("total"),
                db.func.sum(db.cast(Unit.is_occupied.is_(False), db.Integer)).label("vacant"),
            )
            .filter(Unit.property_id.in_(page_ids), Unit.is_deleted.is_(False))
            .group_by(Unit.property_id)
            .all()
        ):
            unit_counts[row.property_id] = (row.total or 0, row.vacant or 0)

    managers_by_property = {}
    if page_ids:
        for a in ManagerAssignment.query.filter(
            ManagerAssignment.property_id.in_(page_ids)
        ).all():
            managers_by_property.setdefault(a.property_id, []).append(
                {"team_member_id": a.team_member_id, "scope_type": a.scope_type}
            )

    items = []
    for p in paginated.items:
        d = p.to_dict()
        total, vacant = unit_counts.get(p.id, (0, 0))
        d["unit_count"]   = total
        d["vacant_count"] = vacant
        d["managers"]     = managers_by_property.get(p.id, [])
        items.append(d)

    return jsonify({
        "summary": {
            "total_properties": total_properties,
            "total_units":      total_units,
            "total_vacancies":  total_vacancies,
        },
        "properties":   items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/properties/
# ---------------------------------------------------------------------------
@property_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
def create_property():
    """
    Create a new property.
    Required: name, number_of_units, city.
    Optional: water_rate, electricity_rate, mpesa_details,
              rent_payment_penalty, tax_rate, management_fee, commission_rate,
              owner_phone, notes, street_name, property_group_id.
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      201: {description: Property created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    name            = (data.get("name") or "").strip()
    number_of_units = data.get("number_of_units")
    city            = (data.get("city") or "").strip()

    if not name or not city:
        return jsonify({"error": "name and city are required."}), 400
    if number_of_units is None:
        return jsonify({"error": "number_of_units is required."}), 400

    prop = Property(
        landlord_id         = landlord_id,
        name                = name,
        number_of_units     = int(number_of_units),
        city                = city,
        street_name         = data.get("street_name"),
        water_rate          = data.get("water_rate"),
        electricity_rate    = data.get("electricity_rate"),
        mpesa_details       = data.get("mpesa_details"),
        rent_payment_penalty = data.get("rent_payment_penalty"),
        tax_rate            = data.get("tax_rate", 7.50),
        management_fee      = data.get("management_fee"),
        commission_rate     = data.get("commission_rate"),
        owner_phone         = data.get("owner_phone"),
        notes               = data.get("notes"),
        property_group_id   = data.get("property_group_id"),
    )
    db.session.add(prop)
    db.session.commit()

    record_audit(
        actor_user_id=_actor_id(),
        landlord_id=landlord_id,
        action="create_property",
        entity_type="property",
        entity_id=prop.id,
        description=f"Property '{prop.name}' created in {prop.city}.",
        after_data=prop.to_dict(),
    )
    db.session.commit()

    return jsonify(prop.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/properties/<id>
# ---------------------------------------------------------------------------
@property_bp.route("/<int:property_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
@scope_to_accessible_properties
def get_property(property_id):
    """
    Return detail for a single property including unit count and managers.
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      200: {description: Property detail.}
      404: {description: Not found or access denied.}
    """
    landlord_id = get_current_landlord_id()
    prop        = _get_or_404(landlord_id, property_id)

    d = prop.to_dict()
    d["units"]    = [u.to_dict() for u in prop.units if not u.is_deleted]
    assignments   = ManagerAssignment.query.filter_by(property_id=prop.id).all()
    d["managers"] = [
        {"team_member_id": a.team_member_id, "scope_type": a.scope_type}
        for a in assignments
    ]
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/properties/<id>
# ---------------------------------------------------------------------------
@property_bp.route("/<int:property_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
@scope_to_accessible_properties
def update_property(property_id):
    """
    Update an existing property's fields.
    Only the fields present in the request body are updated.
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      200: {description: Property updated.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    prop        = _get_or_404(landlord_id, property_id)
    data        = request.get_json(silent=True) or {}
    before      = prop.to_dict()

    editable = [
        "name", "number_of_units", "city", "street_name",
        "water_rate", "electricity_rate", "mpesa_details",
        "rent_payment_penalty", "tax_rate", "management_fee", "commission_rate",
        "owner_phone", "notes", "property_group_id",
    ]
    for field in editable:
        if field in data:
            setattr(prop, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=_actor_id(),
        landlord_id=landlord_id,
        action="update_property",
        entity_type="property",
        entity_id=prop.id,
        description=f"Property '{prop.name}' updated.",
        before_data=before,
        after_data=prop.to_dict(),
    )
    db.session.commit()

    return jsonify(prop.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/properties/<id>  (soft delete)
# ---------------------------------------------------------------------------
@property_bp.route("/<int:property_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "edit")
@scope_to_accessible_properties
def delete_property(property_id):
    """
    Soft-delete a property (sets is_deleted=True, records deleted_at).
    Associated units and tenants are NOT automatically deleted —
    callers should resolve occupancy first.
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      200: {description: Property soft-deleted.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    prop        = _get_or_404(landlord_id, property_id)
    before      = prop.to_dict()

    prop.is_deleted = True
    prop.deleted_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=_actor_id(),
        landlord_id=landlord_id,
        action="delete_property",
        entity_type="property",
        entity_id=prop.id,
        description=f"Property '{prop.name}' soft-deleted.",
        before_data=before,
    )
    db.session.commit()

    return jsonify({"message": f"Property '{prop.name}' has been deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/properties/<id>/units  — add units from property page
# ---------------------------------------------------------------------------
@property_bp.route("/<int:property_id>/units", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "edit")
@scope_to_accessible_properties
def add_unit_to_property(property_id):
    """
    Add one or more units to a property directly from the property page.
    Accepts a single unit object or an array under key 'units'.
    Required per unit: name, rent_amount.
    Optional: tax_rate, notes.
    ---
    tags: [Properties]
    security:
      - Bearer: []
    responses:
      201: {description: Unit(s) created.}
      400: {description: Validation error or duplicate name.}
      404: {description: Property not found.}
    """
    landlord_id = get_current_landlord_id()
    prop        = _get_or_404(landlord_id, property_id)
    data        = request.get_json(silent=True) or {}

    # Accept a single unit dict OR a list under "units"
    units_payload = data.get("units")
    if units_payload is None:
        units_payload = [data]

    created = []
    for u_data in units_payload:
        name        = (u_data.get("name") or "").strip()
        rent_amount = u_data.get("rent_amount")

        if not name or rent_amount is None:
            return jsonify({"error": "Each unit requires 'name' and 'rent_amount'."}), 400

        # Enforce unique name within property
        existing = Unit.query.filter_by(property_id=prop.id, name=name, is_deleted=False).first()
        if existing:
            return jsonify({"error": f"Unit '{name}' already exists in this property."}), 400

        unit = Unit(
            property_id = prop.id,
            name        = name,
            rent_amount = rent_amount,
            tax_rate    = u_data.get("tax_rate"),
            notes       = u_data.get("notes"),
            is_occupied = False,
        )
        db.session.add(unit)
        db.session.flush()
        created.append(unit)

    db.session.commit()

    for unit in created:
        record_audit(
            actor_user_id=_actor_id(),
            landlord_id=landlord_id,
            action="create_unit",
            entity_type="unit",
            entity_id=unit.id,
            description=f"Unit '{unit.name}' added to property '{prop.name}'.",
            after_data=unit.to_dict(),
        )
    db.session.commit()

    return jsonify([u.to_dict() for u in created]), 201


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, property_id: int) -> Property:
    prop = Property.query.filter_by(
        id=property_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not prop:
        from flask import abort
        abort(404, description="Property not found or access denied.")
    # A property-scoped team member can't reach a property outside their
    # assigned set by guessing its id directly (the caller must apply
    # @scope_to_accessible_properties for g.accessible_property_ids to be set).
    accessible = getattr(g, "accessible_property_ids", None)
    if accessible is not None and prop.id not in accessible:
        from flask import abort
        abort(404, description="Property not found or access denied.")
    return prop


def _actor_id() -> int:
    from flask_jwt_extended import get_jwt_identity
    return int(get_jwt_identity())