"""
routes/utility_routes.py — Utility Readings
Blueprint: utility_bp  |  Prefix: /api/utilities

Utility items: water / electricity / garbage / security
One reading per (unit, utility_item, reading_month).
current_reading >= previous_reading (DB CheckConstraint + server validation).
consumption = current_reading - previous_reading (computed on write).
"""

from decimal import Decimal

from flask import Blueprint, request, jsonify, abort, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    UtilityReading, Unit, Property, Tenant, UtilityItem,
    LandlordUtilityType, UtilityCategory,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service import record_audit

utility_bp = Blueprint("utilities", __name__, url_prefix="/api/utilities")


# ===========================================================================
# #6 — Landlord utility catalogue (the utilities a landlord defines/manages).
# ===========================================================================

# Seeded for any landlord that has none yet, so the catalogue is never empty.
_DEFAULT_UTILITY_TYPES = [
    ("Water",         UtilityCategory.current_utility.value, True),
    ("Electricity",   UtilityCategory.current_utility.value, True),
    ("Garbage",       UtilityCategory.current_utility.value, False),
    ("Security",      UtilityCategory.current_utility.value, False),
    ("Rent deposit",   UtilityCategory.deposit.value, False),
    ("Rental balance", UtilityCategory.balance.value, False),
]


def _ensure_utility_types(landlord_id: int):
    """Lazily seed the default catalogue for a landlord that has none."""
    exists = LandlordUtilityType.query.filter_by(landlord_id=landlord_id).first()
    if exists:
        return
    for name, category, metered in _DEFAULT_UTILITY_TYPES:
        db.session.add(LandlordUtilityType(
            landlord_id=landlord_id, name=name, category=category, is_metered=metered,
        ))
    db.session.commit()


@utility_bp.route("/types", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "view")
def list_utility_types():
    """List the landlord's utility catalogue. ?category=&include_inactive="""
    landlord_id = get_current_landlord_id()
    _ensure_utility_types(landlord_id)
    query = LandlordUtilityType.query.filter_by(landlord_id=landlord_id)
    if not request.args.get("include_inactive"):
        query = query.filter_by(is_active=True)
    if cat := request.args.get("category"):
        query = query.filter_by(category=cat)
    types = query.order_by(LandlordUtilityType.category, LandlordUtilityType.name).all()
    return jsonify({"utility_types": [t.to_dict() for t in types]}), 200


@utility_bp.route("/types", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def create_utility_type():
    """Create a utility type. Body: { name, category, is_metered?, default_rate? }"""
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = data.get("category")
    if not name or not category:
        return jsonify({"error": "name and category are required."}), 400
    if category not in [c.value for c in UtilityCategory]:
        return jsonify({"error": f"category must be one of: {[c.value for c in UtilityCategory]}."}), 400
    if LandlordUtilityType.query.filter_by(landlord_id=landlord_id, name=name).first():
        return jsonify({"error": f"A utility named '{name}' already exists."}), 400

    ut = LandlordUtilityType(
        landlord_id=landlord_id, name=name, category=category,
        is_metered=bool(data.get("is_metered")),
        default_rate=data.get("default_rate") or None,
    )
    db.session.add(ut)
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="create_utility_type", entity_type="utility", entity_id=ut.id,
        description=f"Utility type '{name}' ({category}) created.", after_data=ut.to_dict(),
    )
    db.session.commit()
    return jsonify(ut.to_dict()), 201


@utility_bp.route("/types/<int:type_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def update_utility_type(type_id):
    """Update a utility type. Body: any of { name, category, is_metered, default_rate, is_active }"""
    landlord_id = get_current_landlord_id()
    ut = LandlordUtilityType.query.filter_by(id=type_id, landlord_id=landlord_id).first()
    if not ut:
        abort(404, description="Utility type not found.")
    data = request.get_json(silent=True) or {}
    before = ut.to_dict()
    if "name" in data and data["name"]:
        ut.name = data["name"].strip()
    if "category" in data and data["category"] in [c.value for c in UtilityCategory]:
        ut.category = data["category"]
    if "is_metered" in data:
        ut.is_metered = bool(data["is_metered"])
    if "default_rate" in data:
        ut.default_rate = data["default_rate"] or None
    if "is_active" in data:
        ut.is_active = bool(data["is_active"])
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="update_utility_type", entity_type="utility", entity_id=ut.id,
        description=f"Utility type '{ut.name}' updated.", before_data=before, after_data=ut.to_dict(),
    )
    db.session.commit()
    return jsonify(ut.to_dict()), 200


@utility_bp.route("/types/<int:type_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def delete_utility_type(type_id):
    """Deactivate a utility type (soft — keeps historical readings/invoices intact)."""
    landlord_id = get_current_landlord_id()
    ut = LandlordUtilityType.query.filter_by(id=type_id, landlord_id=landlord_id).first()
    if not ut:
        abort(404, description="Utility type not found.")
    ut.is_active = False
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
        action="delete_utility_type", entity_type="utility", entity_id=ut.id,
        description=f"Utility type '{ut.name}' deactivated.",
    )
    db.session.commit()
    return jsonify({"message": "Utility type deactivated."}), 200


# ---------------------------------------------------------------------------
# GET /api/utilities/
# ---------------------------------------------------------------------------
@utility_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "view")
@scope_to_accessible_properties
def list_readings():
    """
    List utility readings.
    Filters: ?property_id=, ?unit_id=, ?utility_item=, ?reading_month= (YYYY-MM),
             ?page=, ?per_page=
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated utility readings.}
    """
    landlord_id  = get_current_landlord_id()
    page         = request.args.get("page", 1, type=int)
    per_page     = request.args.get("per_page", 20, type=int)

    query = (
        UtilityReading.query
        .filter_by(landlord_id=landlord_id)
    )

    if g.accessible_property_ids is not None:
        query = query.filter(UtilityReading.property_id.in_(g.accessible_property_ids))

    if v := request.args.get("property_id", type=int):
        query = query.filter(UtilityReading.property_id == v)
    if v := request.args.get("unit_id", type=int):
        query = query.filter(UtilityReading.unit_id == v)
    if v := request.args.get("utility_item"):
        query = query.filter(UtilityReading.utility_item == v)
    if v := request.args.get("reading_month"):
        query = query.filter(UtilityReading.reading_month == v)

    paginated = query.order_by(
        UtilityReading.reading_month.desc(), UtilityReading.id.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for r in paginated.items:
        d = r.to_dict()
        d["property_name"] = r.property.name if r.property else None
        d["unit_name"]     = r.unit.name     if r.unit     else None
        d["invoice_number"] = r.invoice.invoice_number if r.invoice else None
        items.append(d)

    return jsonify({
        "readings":     items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/utilities/
# ---------------------------------------------------------------------------
@utility_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def create_reading():
    """
    Record a single utility reading.
    Body: { property_id, unit_id, utility_item, current_reading,
            reading_month (YYYY-MM), previous_reading? }
    Validation: current_reading >= previous_reading.
    Uniqueness: (unit_id, utility_item, reading_month) is unique.
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      201: {description: Reading recorded.}
      400: {description: Validation error or duplicate.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    property_id      = data.get("property_id")
    unit_id          = data.get("unit_id")
    utility_item     = data.get("utility_item")
    utility_type_id  = data.get("utility_type_id")
    current_reading  = data.get("current_reading")
    reading_month    = data.get("reading_month")
    previous_reading = data.get("previous_reading")
    amount           = data.get("amount")

    # #6 — resolve the catalogue type (preferred). utility_item name is derived from it.
    utype = None
    if utility_type_id:
        utype = LandlordUtilityType.query.filter_by(id=utility_type_id, landlord_id=landlord_id).first()
        if not utype:
            return jsonify({"error": "utility_type_id not found for this landlord."}), 400
        utility_item = utype.name

    if not all([property_id, unit_id, utility_item, reading_month]):
        return jsonify({"error": "property_id, unit_id, utility (type), and reading_month are required."}), 400

    # #8 — readings are OPTIONAL. A metered utility supplies current/previous readings;
    # a flat (non-metered) utility supplies a straight `amount` and no readings.
    has_reading = current_reading not in (None, "")
    has_amount  = amount not in (None, "")
    if not has_reading and not has_amount:
        return jsonify({"error": "Provide either a current_reading (metered) or an amount (flat charge)."}), 400

    if has_reading and previous_reading is not None:
        if Decimal(str(current_reading)) < Decimal(str(previous_reading)):
            return jsonify({"error": "current_reading must be >= previous_reading."}), 400

    # Uniqueness check
    existing = UtilityReading.query.filter_by(
        unit_id=unit_id, utility_item=utility_item, reading_month=reading_month
    ).first()
    if existing:
        return jsonify({"error": f"A {utility_item} reading already exists for this unit in {reading_month}."}), 400

    consumption = None
    if has_reading and previous_reading is not None:
        consumption = Decimal(str(current_reading)) - Decimal(str(previous_reading))

    reading = UtilityReading(
        landlord_id      = landlord_id,
        property_id      = property_id,
        unit_id          = unit_id,
        utility_item     = utility_item,
        utility_type_id  = utype.id if utype else None,
        previous_reading = previous_reading if has_reading else None,
        current_reading  = current_reading if has_reading else None,
        amount           = Decimal(str(amount)) if has_amount else None,
        consumption      = consumption,
        reading_month    = reading_month,
    )
    db.session.add(reading)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_utility_reading",
        entity_type="utility",
        entity_id=reading.id,
        description=f"{utility_item} reading recorded for unit {unit_id} ({reading_month}).",
        after_data=reading.to_dict(),
    )
    db.session.commit()
    return jsonify(reading.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/utilities/<id>
# ---------------------------------------------------------------------------
@utility_bp.route("/<int:reading_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def update_reading(reading_id):
    """Update a utility reading. Re-validates current >= previous."""
    landlord_id = get_current_landlord_id()
    reading     = _get_or_404(landlord_id, reading_id)
    data        = request.get_json(silent=True) or {}
    before      = reading.to_dict()

    if "current_reading" in data:
        current  = Decimal(str(data["current_reading"]))
        previous = Decimal(str(data.get("previous_reading", reading.previous_reading or 0)))
        if current < previous:
            return jsonify({"error": "current_reading must be >= previous_reading."}), 400
        reading.current_reading  = current
        reading.previous_reading = previous
        reading.consumption      = current - previous

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_utility_reading",
        entity_type="utility",
        entity_id=reading.id,
        description="Utility reading updated.",
        before_data=before,
        after_data=reading.to_dict(),
    )
    db.session.commit()
    return jsonify(reading.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/utilities/<id>
# ---------------------------------------------------------------------------
@utility_bp.route("/<int:reading_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def delete_reading(reading_id):
    """Hard-delete a utility reading (no financial history — no soft-delete required)."""
    landlord_id = get_current_landlord_id()
    reading     = _get_or_404(landlord_id, reading_id)
    before      = reading.to_dict()

    db.session.delete(reading)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_utility_reading",
        entity_type="utility",
        entity_id=reading_id,
        description="Utility reading deleted.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": "Utility reading deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/utilities/bulk-upload
# ---------------------------------------------------------------------------
@utility_bp.route("/bulk-upload", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("utilities", "edit")
def bulk_upload_readings():
    """
    Accept bulk utility readings for all tenants in a property.
    Body:
      { property_id, utility_item, reading_month,
        readings: [{ unit_id, current_reading, previous_reading? }] }
    Validates each reading but does NOT generate invoices yet —
    call /bulk-upload/generate-invoices after review.
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      201: {description: Bulk readings recorded.}
      400: {description: Validation error.}
    """
    landlord_id   = get_current_landlord_id()
    data          = request.get_json(silent=True) or {}
    property_id   = data.get("property_id")
    utility_item  = data.get("utility_item")
    reading_month = data.get("reading_month")
    readings_data = data.get("readings", [])

    if not all([property_id, utility_item, reading_month]):
        return jsonify({"error": "property_id, utility_item, and reading_month are required."}), 400
    if not readings_data:
        return jsonify({"error": "readings list is required."}), 400

    created  = []
    errors   = []

    for r_data in readings_data:
        unit_id         = r_data.get("unit_id")
        current_reading = r_data.get("current_reading")
        previous_reading = r_data.get("previous_reading")

        if not unit_id or current_reading is None:
            errors.append({"unit_id": unit_id, "error": "unit_id and current_reading required."})
            continue

        if previous_reading is not None and Decimal(str(current_reading)) < Decimal(str(previous_reading)):
            errors.append({"unit_id": unit_id, "error": "current_reading < previous_reading."})
            continue

        # Skip duplicates silently
        if UtilityReading.query.filter_by(
            unit_id=unit_id, utility_item=utility_item, reading_month=reading_month
        ).first():
            errors.append({"unit_id": unit_id, "error": "Duplicate reading for this month."})
            continue

        consumption = None
        if previous_reading is not None:
            consumption = Decimal(str(current_reading)) - Decimal(str(previous_reading))

        reading = UtilityReading(
            landlord_id      = landlord_id,
            property_id      = property_id,
            unit_id          = unit_id,
            utility_item     = utility_item,
            previous_reading = previous_reading,
            current_reading  = current_reading,
            consumption      = consumption,
            reading_month    = reading_month,
        )
        db.session.add(reading)
        db.session.flush()
        created.append(reading)

    db.session.commit()

    if created:
        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="bulk_upload_utility_readings",
            entity_type="utility",
            entity_id=None,
            description=f"{len(created)} {utility_item} reading(s) uploaded for {reading_month} ({len(errors)} skipped).",
            after_data={"reading_ids": [r.id for r in created]},
        )
        db.session.commit()

    return jsonify({
        "created": len(created),
        "errors":  errors,
        "readings": [r.to_dict() for r in created],
    }), 201


# ---------------------------------------------------------------------------
# POST /api/utilities/bulk-upload/generate-invoices
# ---------------------------------------------------------------------------
@utility_bp.route("/bulk-upload/generate-invoices", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def bulk_generate_utility_invoices():
    """
    Generate utility invoices from bulk-uploaded readings (after review).
    Body:
      { property_id, utility_item, reading_month,
        reading_ids?: [int]  (default: all unlinked readings for this batch) }
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      202: {description: Invoice generation task queued.}
    """
    landlord_id   = get_current_landlord_id()
    data          = request.get_json(silent=True) or {}

    from tasks.invoice_tasks import generate_utility_invoices_task
    task = generate_utility_invoices_task.delay(
        landlord_id,
        data.get("property_id"),
        data.get("utility_item"),
        data.get("reading_month"),
        data.get("reading_ids"),
        int(get_jwt_identity()),
        bool(data.get("combine")),
    )
    return jsonify({"task_id": task.id, "message": "Utility invoice generation queued."}), 202


# ---------------------------------------------------------------------------
# POST /api/utilities/<id>/add-to-invoice
# ---------------------------------------------------------------------------
@utility_bp.route("/<int:reading_id>/add-to-invoice", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def add_reading_to_invoice(reading_id):
    """
    Bill a single utility reading by adding it as a line item to an invoice.
    Body: { mode: "current" | "new", amount? }
      - "current": append to the tenant's open/partial invoice for the reading month
                   (creates one if none exists yet).
      - "new":     always raise a fresh invoice for just this reading.
    Amount defaults to consumption × the property's rate (water/electricity);
    pass `amount` to override (needed for garbage/security, which have no rate).
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      201: {description: Reading billed onto an invoice.}
      400: {description: Already billed, or amount could not be determined.}
    """
    from datetime import date as _date
    from sqlalchemy import extract
    from models import Invoice, InvoiceLineItem, InvoiceStatus
    from tasks.invoice_tasks import _create_invoice

    landlord_id = get_current_landlord_id()
    reading     = _get_or_404(landlord_id, reading_id)
    data        = request.get_json(silent=True) or {}
    mode        = data.get("mode", "current")

    if reading.invoice_id:
        return jsonify({"error": "This reading is already on an invoice."}), 400

    tenant = reading.unit.tenants[0] if reading.unit and reading.unit.tenants else None
    if tenant is None:
        return jsonify({"error": "This unit has no active tenant to bill."}), 400

    # Resolve the amount to bill.
    if data.get("amount") not in (None, ""):
        amount = Decimal(str(data["amount"]))
    elif reading.amount not in (None, ""):
        # #8 — flat (non-metered) utility recorded with an explicit amount.
        amount = Decimal(str(reading.amount))
    else:
        # Metered: consumption × rate. Prefer the catalogue default_rate, then the
        # property's water/electricity rate.
        rate = None
        if reading.utility_type and reading.utility_type.default_rate is not None:
            rate = reading.utility_type.default_rate
        elif reading.utility_item == "water":
            rate = reading.property.water_rate if reading.property else None
        elif reading.utility_item == "electricity":
            rate = reading.property.electricity_rate if reading.property else None
        if rate is None:
            return jsonify({"error": f"No rate configured for {reading.utility_item}; pass an explicit amount."}), 400
        amount = Decimal(str(reading.consumption or 0)) * Decimal(str(rate))

    if amount <= 0:
        return jsonify({"error": "Computed amount is zero — set a consumption/rate or pass an amount."}), 400

    description = f"{reading.reading_month} — {reading.previous_reading or 0} to {reading.current_reading}"

    # Try to append to the tenant's open invoice for that month.
    target = None
    if mode == "current":
        try:
            year, month = (int(x) for x in reading.reading_month.split("-")[:2])
            target = (
                Invoice.query
                .filter_by(tenant_id=tenant.id, landlord_id=landlord_id, is_deleted=False)
                .filter(Invoice.status.in_([InvoiceStatus.open.value, InvoiceStatus.partial.value]))
                .filter(extract("year",  Invoice.issue_date) == year)
                .filter(extract("month", Invoice.issue_date) == month)
                .order_by(Invoice.id.desc())
                .first()
            )
        except (ValueError, AttributeError):
            target = None

    if target is not None:
        db.session.add(InvoiceLineItem(
            invoice_id=target.id, item=reading.utility_item, description=description,
            quantity=Decimal("1"), unit_price=amount, amount=amount, utility_reading_id=reading.id,
        ))
        target.total_amount = (target.total_amount or Decimal("0")) + amount
        target.balance      = target.total_amount - (target.amount_paid or Decimal("0"))
        tenant.balance      = (tenant.balance or Decimal("0")) - amount
        invoice = target
    else:
        # New invoice (also the fallback when no open invoice exists for the month).
        issue_dt = _date.today()
        try:
            year, month = (int(x) for x in reading.reading_month.split("-")[:2])
            issue_dt = _date(year, month, 1)
        except (ValueError, AttributeError):
            pass
        # #6 — a deposit-category utility bills as a deposit invoice so auto-allocation
        # clears it in the deposits bucket; everything else stays a utility invoice.
        inv_type = "deposit" if (reading.utility_type and reading.utility_type.category == "deposit") else "utility"
        invoice = _create_invoice(
            landlord_id, tenant, reading.unit, reading.property, inv_type, issue_dt, None,
            [{
                "item": reading.utility_item, "description": description,
                "quantity": 1, "unit_price": amount, "utility_reading_id": reading.id,
            }],
            title=f"{reading.utility_item.capitalize()} — {reading.reading_month}",
        )

    reading.invoice_id = invoice.id
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="bill_utility_reading",
        entity_type="invoice",
        entity_id=invoice.id,
        description=f"{reading.utility_item} reading billed onto invoice {invoice.invoice_number} ({'combined' if target else 'new'}).",
    )
    db.session.commit()

    return jsonify({"invoice": invoice.to_dict(), "combined": target is not None}), 201


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, reading_id: int) -> UtilityReading:
    r = UtilityReading.query.filter_by(
        id=reading_id, landlord_id=landlord_id
    ).first()
    if not r:
        abort(404, description="Utility reading not found.")
    return r