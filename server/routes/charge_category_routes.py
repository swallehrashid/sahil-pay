"""
routes/charge_category_routes.py — Charge-category catalogue CRUD
Blueprint: charge_category_bp  |  Prefix: /api/charge-categories

The unified catalogue behind BOTH the Utilities page (kind=utility) and the
Invoices page (kind=invoice). Every category implicitly owns three subcategories
(deposit / balance / current) — see models.ChargeCategory. Permissions are gated by
kind: utility categories use the "utilities" module, invoice categories "invoices".
See CATEGORY_RESTRUCTURE_SPEC.md §4.1.
"""

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import ChargeCategory, ChargeCategoryKind, InvoiceLineItem
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id, _check_permission,
)
from services.audit_service import record_audit
from services.category_service import seed_default_categories

charge_category_bp = Blueprint("charge_categories", __name__, url_prefix="/api/charge-categories")

_KINDS = {k.value for k in ChargeCategoryKind}


def _module_for(kind: str) -> str:
    return "utilities" if kind == ChargeCategoryKind.utility.value else "invoices"


def _validate_metered_autobill(is_metered: bool, auto_bill: bool):
    if is_metered and auto_bill:
        return "A metered category can't auto-bill monthly — its amount isn't known in advance."
    return None


@charge_category_bp.route("", methods=["GET"])
@charge_category_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def list_categories():
    """List the landlord's charge categories. ?kind=utility|invoice&include_inactive="""
    landlord_id = get_current_landlord_id()
    kind = request.args.get("kind")
    # Which permission applies depends on WHICH catalogue is being asked for, so
    # the check is here rather than in a decorator.
    #
    # There used to be a @require_permission("invoices", "view") above as well,
    # which ran first and refused before this line could apply the kind-specific
    # rule — making the rule dead code. The visible effect was that a caretaker,
    # whose whole job is meter readings, got an empty Water/Electricity dropdown
    # on the Utilities page and so could not record a reading at all: the
    # backend allowed the write, but the form could not be filled in.
    _check_permission(_module_for(kind) if kind in _KINDS else "invoices", "view")

    # Never show an empty catalogue — lazily seed the protected defaults.
    if ChargeCategory.query.filter_by(landlord_id=landlord_id).first() is None:
        seed_default_categories(landlord_id, commit=True)

    query = ChargeCategory.query.filter_by(landlord_id=landlord_id)
    if kind in _KINDS:
        query = query.filter_by(kind=kind)
    # request.args.get(...) returns the string "0" for ?include_inactive=0, which is
    # truthy in Python — every caller that explicitly opts OUT (the common case: every
    # category dropdown across Invoices/Utilities passes include_inactive=0) was silently
    # getting inactive categories back. Parse it as a real boolean instead.
    include_inactive = request.args.get("include_inactive", "").lower() in ("1", "true", "yes")
    if not include_inactive:
        query = query.filter_by(is_active=True)
    cats = query.order_by(ChargeCategory.is_default.desc(), ChargeCategory.name.asc()).all()
    return jsonify({"categories": [c.to_dict() for c in cats]}), 200


@charge_category_bp.route("", methods=["POST"])
@charge_category_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def create_category():
    """Create a category. Body: { name, kind, description?, is_metered?, default_rate?, auto_bill_monthly? }"""
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    kind = data.get("kind")

    if not name:
        return jsonify({"error": "name is required."}), 400
    if kind not in _KINDS:
        return jsonify({"error": f"kind must be one of: {sorted(_KINDS)}."}), 400
    _check_permission(_module_for(kind), "edit")

    is_metered = bool(data.get("is_metered")) if kind == ChargeCategoryKind.utility.value else False
    auto_bill  = bool(data.get("auto_bill_monthly"))
    if (err := _validate_metered_autobill(is_metered, auto_bill)):
        return jsonify({"error": err}), 400
    if ChargeCategory.query.filter_by(landlord_id=landlord_id, name=name).first():
        return jsonify({"error": f"A category named '{name}' already exists."}), 400

    cat = ChargeCategory(
        landlord_id=landlord_id, name=name, kind=kind,
        description=data.get("description"),
        is_metered=is_metered,
        default_rate=data.get("default_rate") or None,
        auto_bill_monthly=auto_bill,
        is_default=False, is_active=True,
    )
    db.session.add(cat)
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="create_charge_category", entity_type="charge_category", entity_id=cat.id,
        description=f"{kind.capitalize()} category '{name}' created.", after_data=cat.to_dict(),
    )
    db.session.commit()
    return jsonify(cat.to_dict()), 201


@charge_category_bp.route("/<int:category_id>", methods=["PATCH", "PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def update_category(category_id):
    """Update a category. Body: any of { name, description, is_metered, default_rate, auto_bill_monthly, is_active }"""
    landlord_id = get_current_landlord_id()
    cat = ChargeCategory.query.filter_by(id=category_id, landlord_id=landlord_id).first()
    if not cat:
        abort(404, description="Category not found.")
    _check_permission(_module_for(cat.kind), "edit")

    data = request.get_json(silent=True) or {}
    before = cat.to_dict()

    if "name" in data and (data["name"] or "").strip():
        new_name = data["name"].strip()
        if cat.is_default and new_name != cat.name:
            return jsonify({"error": "A default category can't be renamed."}), 400
        clash = ChargeCategory.query.filter_by(landlord_id=landlord_id, name=new_name).first()
        if clash and clash.id != cat.id:
            return jsonify({"error": f"A category named '{new_name}' already exists."}), 400
        cat.name = new_name
    if "description" in data:
        cat.description = data["description"]
    if "is_metered" in data and cat.kind == ChargeCategoryKind.utility.value:
        cat.is_metered = bool(data["is_metered"])
    if "default_rate" in data:
        cat.default_rate = data["default_rate"] or None
    if "auto_bill_monthly" in data:
        cat.auto_bill_monthly = bool(data["auto_bill_monthly"])
    if "is_active" in data:
        cat.is_active = bool(data["is_active"])

    if (err := _validate_metered_autobill(cat.is_metered, cat.auto_bill_monthly)):
        return jsonify({"error": err}), 400

    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="update_charge_category", entity_type="charge_category", entity_id=cat.id,
        description=f"Category '{cat.name}' updated.", before_data=before, after_data=cat.to_dict(),
    )
    db.session.commit()
    return jsonify(cat.to_dict()), 200


@charge_category_bp.route("/<int:category_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def delete_category(category_id):
    """
    Delete a category. Protected defaults and categories already used on invoices can't
    be deleted (409) — deactivate them instead so history stays intact.
    """
    landlord_id = get_current_landlord_id()
    cat = ChargeCategory.query.filter_by(id=category_id, landlord_id=landlord_id).first()
    if not cat:
        abort(404, description="Category not found.")
    _check_permission(_module_for(cat.kind), "edit")

    if cat.is_default:
        return jsonify({"error": "Default categories can't be deleted — deactivate them instead.",
                        "code": "protected_default"}), 409
    if InvoiceLineItem.query.filter_by(category_id=cat.id).first() is not None:
        return jsonify({"error": "This category is used on invoices — deactivate it instead of deleting.",
                        "code": "category_in_use"}), 409

    db.session.delete(cat)
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="delete_charge_category", entity_type="charge_category", entity_id=category_id,
        description=f"Category '{cat.name}' deleted.",
    )
    db.session.commit()
    return jsonify({"message": "Category deleted."}), 200
