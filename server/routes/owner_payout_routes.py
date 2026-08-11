"""
routes/owner_payout_routes.py — Owner Payouts (property-manager remittances)
Blueprint: owner_payout_bp  |  Prefix: /api/owner-payouts

A property management company collects every tenant's rent into its own
paybill and then remits each property owner their share. This is the ledger of
those remittances.

A payout is NOT an expense — it is the owner's own money changing hands — so it
never enters expense totals, taxable income, or the commission base. The
property statement shows it as an informational "Remitted to owner" line that
closes the loop: net income − remitted = retained.

Permission module: `payments` (whoever may record money movements may record
remittances). Property-scoped like every other money endpoint, so an owner
team member restricted to their own block only ever sees their own payouts.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import OwnerPayout, Property
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service import record_audit

owner_payout_bp = Blueprint("owner_payouts", __name__, url_prefix="/api/owner-payouts")

VALID_METHODS = ("mpesa", "bank", "cash", "other")


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _owned_property(landlord_id: int, property_id):
    """The caller's property, honouring team-member property scoping."""
    if not property_id:
        return None
    query = Property.query.filter_by(
        id=property_id, landlord_id=landlord_id, is_deleted=False
    )
    if g.get("accessible_property_ids") is not None:
        query = query.filter(Property.id.in_(g.accessible_property_ids))
    return query.first()


def _get_or_404(landlord_id: int, payout_id: int):
    query = OwnerPayout.query.filter_by(id=payout_id, landlord_id=landlord_id)
    if g.get("accessible_property_ids") is not None:
        query = query.filter(OwnerPayout.property_id.in_(g.accessible_property_ids))
    return query.first()


# ---------------------------------------------------------------------------
# GET /api/owner-payouts/
# ---------------------------------------------------------------------------
@owner_payout_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
@scope_to_accessible_properties
def list_payouts():
    """
    List owner payouts with a total.
    Filters: ?property_id=, ?period=YYYY-MM, ?start_date=, ?end_date=,
             ?page=, ?per_page= (default 20, max 100)
    ---
    tags: [Owner Payouts]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated payout list + total.}
    """
    from sqlalchemy.orm import selectinload

    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = min(request.args.get("per_page", 20, type=int), 100)

    query = (
        OwnerPayout.query
        .options(selectinload(OwnerPayout.property))
        .filter_by(landlord_id=landlord_id)
    )

    if g.accessible_property_ids is not None:
        query = query.filter(OwnerPayout.property_id.in_(g.accessible_property_ids))

    if v := request.args.get("property_id", type=int):
        query = query.filter(OwnerPayout.property_id == v)
    if v := request.args.get("period"):
        query = query.filter(OwnerPayout.period == v)
    if d := _parse_date(request.args.get("start_date")):
        query = query.filter(OwnerPayout.payout_date >= d)
    if d := _parse_date(request.args.get("end_date")):
        query = query.filter(OwnerPayout.payout_date <= d)

    # Sum in the database rather than pulling every row (this list is paginated).
    total_amount = float(
        query.with_entities(db.func.coalesce(db.func.sum(OwnerPayout.amount), 0)).scalar() or 0
    )

    paginated = query.order_by(OwnerPayout.payout_date.desc(), OwnerPayout.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "payouts":      [p.to_dict() for p in paginated.items],
        "total_amount": total_amount,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/owner-payouts/
# ---------------------------------------------------------------------------
@owner_payout_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
@scope_to_accessible_properties
def create_payout():
    """
    Record a remittance to a property's owner.
    Required: property_id, amount, payout_date.
    Optional: period (YYYY-MM), method, reference, notes.
    ---
    tags: [Owner Payouts]
    security:
      - Bearer: []
    responses:
      201: {description: Payout recorded.}
      400: {description: Validation error.}
      404: {description: Property not found.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    prop = _owned_property(landlord_id, data.get("property_id"))
    if not prop:
        return jsonify({"error": "Property not found."}), 404

    payout_date = _parse_date(data.get("payout_date"))
    if not payout_date:
        return jsonify({"error": "payout_date is required (YYYY-MM-DD)."}), 400

    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number."}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero."}), 400

    method = (data.get("method") or "").strip().lower() or None
    if method and method not in VALID_METHODS:
        return jsonify({"error": f"method must be one of: {', '.join(VALID_METHODS)}."}), 400

    payout = OwnerPayout(
        landlord_id        = landlord_id,
        property_id        = prop.id,
        amount             = amount,
        payout_date        = payout_date,
        period             = (data.get("period") or payout_date.strftime("%Y-%m")),
        method             = method,
        reference          = data.get("reference"),
        notes              = data.get("notes"),
        created_by_user_id = int(get_jwt_identity()),
    )
    db.session.add(payout)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_owner_payout",
        entity_type="owner_payout",
        entity_id=payout.id,
        description=f"Payout of {amount:,.2f} to the owner of '{prop.name}' recorded.",
        after_data=payout.to_dict(),
    )
    db.session.commit()

    return jsonify(payout.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/owner-payouts/<id>
# ---------------------------------------------------------------------------
@owner_payout_bp.route("/<int:payout_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
@scope_to_accessible_properties
def update_payout(payout_id):
    """
    Update a recorded payout.
    ---
    tags: [Owner Payouts]
    security:
      - Bearer: []
    responses:
      200: {description: Payout updated.}
      404: {description: Payout not found.}
    """
    landlord_id = get_current_landlord_id()
    payout      = _get_or_404(landlord_id, payout_id)
    if not payout:
        return jsonify({"error": "Payout not found."}), 404

    data   = request.get_json(silent=True) or {}
    before = payout.to_dict()

    if "property_id" in data:
        prop = _owned_property(landlord_id, data.get("property_id"))
        if not prop:
            return jsonify({"error": "Property not found."}), 404
        payout.property_id = prop.id

    if "amount" in data:
        try:
            amount = float(data["amount"])
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a number."}), 400
        if amount <= 0:
            return jsonify({"error": "amount must be greater than zero."}), 400
        payout.amount = amount

    if "payout_date" in data:
        d = _parse_date(data["payout_date"])
        if not d:
            return jsonify({"error": "payout_date must be YYYY-MM-DD."}), 400
        payout.payout_date = d

    if "method" in data:
        method = (data.get("method") or "").strip().lower() or None
        if method and method not in VALID_METHODS:
            return jsonify({"error": f"method must be one of: {', '.join(VALID_METHODS)}."}), 400
        payout.method = method

    for field in ("period", "reference", "notes"):
        if field in data:
            setattr(payout, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_owner_payout",
        entity_type="owner_payout",
        entity_id=payout.id,
        description=f"Owner payout #{payout.id} updated.",
        before_data=before,
        after_data=payout.to_dict(),
    )
    db.session.commit()

    return jsonify(payout.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/owner-payouts/<id>
# ---------------------------------------------------------------------------
@owner_payout_bp.route("/<int:payout_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
@scope_to_accessible_properties
def delete_payout(payout_id):
    """
    Delete a recorded payout (hard delete — this is a manual bookkeeping row).
    ---
    tags: [Owner Payouts]
    security:
      - Bearer: []
    responses:
      200: {description: Payout deleted.}
      404: {description: Payout not found.}
    """
    landlord_id = get_current_landlord_id()
    payout      = _get_or_404(landlord_id, payout_id)
    if not payout:
        return jsonify({"error": "Payout not found."}), 404

    before = payout.to_dict()
    db.session.delete(payout)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_owner_payout",
        entity_type="owner_payout",
        entity_id=payout_id,
        description=f"Owner payout #{payout_id} deleted.",
        before_data=before,
    )
    db.session.commit()

    return jsonify({"message": "Payout deleted."}), 200
