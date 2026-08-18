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
    UtilityReading, Unit, Property, Tenant, UtilityItem, ChargeCategory,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service import record_audit

utility_bp = Blueprint("utilities", __name__, url_prefix="/api/utilities")


# The landlord utility catalogue now lives in the unified ChargeCategory table —
# see routes/charge_category_routes.py (GET/POST /api/charge-categories?kind=utility).


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
        d["property_name"]  = r.property.name if r.property else None
        d["unit_name"]      = r.unit.name     if r.unit     else None
        d["invoice_number"] = r.invoice.invoice_number if r.invoice else None
        d["category_name"]  = r.category.name if r.category else None
        d["is_metered"]     = r.category.is_metered if r.category else (r.current_reading is not None)
        d["default_rate"]   = str(r.category.default_rate) if r.category and r.category.default_rate is not None else None
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
    category_id      = data.get("category_id") or data.get("utility_type_id")  # utility_type_id: legacy alias
    current_reading  = data.get("current_reading")
    reading_month    = data.get("reading_month")
    previous_reading = data.get("previous_reading")
    amount           = data.get("amount")
    subcategory      = (data.get("subcategory") or "current").strip().lower()

    from models import SubCategory
    valid_subs = {s.value for s in SubCategory}
    if subcategory not in valid_subs:
        return jsonify({"error": f"subcategory must be one of {sorted(valid_subs)}."}), 400

    # Resolve the utility ChargeCategory (preferred). utility_item name is derived from it.
    utype = None
    if category_id:
        utype = ChargeCategory.query.filter_by(
            id=category_id, landlord_id=landlord_id, kind="utility"
        ).first()
        if not utype:
            return jsonify({"error": "category_id not found for this landlord."}), 400
        utility_item = utype.name

    if not all([property_id, unit_id, utility_item, reading_month]):
        return jsonify({"error": "property_id, unit_id, utility (type), and reading_month are required."}), 400

    # #8 — readings are OPTIONAL. A metered utility supplies current/previous readings;
    # a flat (non-metered) utility supplies a straight `amount` and no readings.
    # A DEPOSIT subcategory is money held — never metered — so it always takes a flat
    # amount, regardless of whether the category itself is metered.
    is_metered = bool(utype and utype.is_metered) and subcategory != SubCategory.deposit.value
    has_reading = current_reading not in (None, "")
    has_amount  = amount not in (None, "")

    if subcategory == SubCategory.deposit.value and has_reading:
        return jsonify({"error": "A deposit is not metered — record it as a flat amount, not a meter reading."}), 400
    if not has_reading and not has_amount:
        return jsonify({"error": "Provide either a current_reading (metered) or an amount (flat charge)."}), 400

    if has_reading and previous_reading is not None:
        if Decimal(str(current_reading)) < Decimal(str(previous_reading)):
            return jsonify({"error": "current_reading must be >= previous_reading."}), 400

    # Uniqueness check — now scoped per subcategory so a unit can carry e.g. both a
    # Water current and a Water deposit in the same month.
    existing = UtilityReading.query.filter_by(
        unit_id=unit_id, utility_item=utility_item,
        subcategory=subcategory, reading_month=reading_month,
    ).first()
    if existing:
        label = utype.subcategory_display().get(subcategory, utility_item) if utype else utility_item
        return jsonify({"error": f"A {label} reading already exists for this unit in {reading_month}."}), 400

    consumption = None
    if has_reading and previous_reading is not None:
        consumption = Decimal(str(current_reading)) - Decimal(str(previous_reading))

    reading = UtilityReading(
        landlord_id      = landlord_id,
        property_id      = property_id,
        unit_id          = unit_id,
        utility_item     = utility_item,
        category_id      = utype.id if utype else None,
        subcategory      = subcategory,
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
      { property_id, utility_item?, category_id?, reading_month,
        readings: [{ unit_id, current_reading?, previous_reading?, amount? }] }
    category_id (preferred) resolves the landlord's utility ChargeCategory — its
    name becomes utility_item and each reading is tagged with it, so the invoice
    line generated later inherits the right category for allocation priority.
    Metered categories take current/previous readings; non-metered ones take a
    flat `amount` per row instead. Validates each reading but does NOT generate
    invoices yet — call /bulk-upload/generate-invoices after review.
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
    category_id   = data.get("category_id")
    reading_month = data.get("reading_month")
    readings_data = data.get("readings", [])

    utype = None
    if category_id:
        utype = ChargeCategory.query.filter_by(
            id=category_id, landlord_id=landlord_id, kind="utility"
        ).first()
        if not utype:
            return jsonify({"error": "category_id not found for this landlord."}), 400
        utility_item = utype.name

    if not all([property_id, utility_item, reading_month]):
        return jsonify({"error": "property_id, utility (category_id or utility_item), and reading_month are required."}), 400
    if not readings_data:
        return jsonify({"error": "readings list is required."}), 400

    created  = []
    errors   = []

    for r_data in readings_data:
        unit_id          = r_data.get("unit_id")
        current_reading  = r_data.get("current_reading")
        previous_reading = r_data.get("previous_reading")
        amount           = r_data.get("amount")

        has_reading = current_reading not in (None, "")
        has_amount  = amount not in (None, "")
        if not unit_id or (not has_reading and not has_amount):
            errors.append({"unit_id": unit_id, "error": "unit_id and either a current_reading or an amount are required."})
            continue

        if has_reading and previous_reading is not None:
            if Decimal(str(current_reading)) < Decimal(str(previous_reading)):
                errors.append({"unit_id": unit_id, "error": "current_reading < previous_reading."})
                continue

        # Skip duplicates silently
        if UtilityReading.query.filter_by(
            unit_id=unit_id, utility_item=utility_item, reading_month=reading_month
        ).first():
            errors.append({"unit_id": unit_id, "error": "Duplicate reading for this month."})
            continue

        consumption = None
        if has_reading and previous_reading is not None:
            consumption = Decimal(str(current_reading)) - Decimal(str(previous_reading))

        reading = UtilityReading(
            landlord_id      = landlord_id,
            property_id      = property_id,
            unit_id          = unit_id,
            utility_item     = utility_item,
            category_id      = utype.id if utype else None,
            previous_reading = previous_reading if has_reading else None,
            current_reading  = current_reading if has_reading else None,
            amount           = Decimal(str(amount)) if has_amount else None,
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
      { property_id, category_id? | utility_item?, reading_month,
        reading_ids?: [int]  (default: all unlinked readings for this batch) }
    category_id (preferred) resolves the landlord's utility ChargeCategory to its
    name for scoping the readings query.
    ---
    tags: [Utilities]
    security:
      - Bearer: []
    responses:
      202: {description: Invoice generation task queued.}
    """
    landlord_id   = get_current_landlord_id()
    data          = request.get_json(silent=True) or {}

    utility_item = data.get("utility_item")
    category_id  = data.get("category_id")
    if category_id:
        utype = ChargeCategory.query.filter_by(
            id=category_id, landlord_id=landlord_id, kind="utility"
        ).first()
        if not utype:
            return jsonify({"error": "category_id not found for this landlord."}), 400
        utility_item = utype.name

    from tasks.invoice_tasks import generate_utility_invoices_task
    task = generate_utility_invoices_task.delay(
        landlord_id,
        data.get("property_id"),
        utility_item,
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
    Body: { mode: "current" | "new" | "queue", amount? }
      - "current": append to the tenant's open/partial invoice for the reading month
                   (creates one if none exists yet).
      - "new":     always raise a fresh invoice for just this reading.
      - "queue":   hold it for the unit's NEXT invoice. This is the one that fits
                   how meters are actually read: on the 28th there is no invoice
                   to attach to, and raising a one-line utility bill sends the
                   tenant a second, unexpected invoice. Queued charges are folded
                   into the next monthly run automatically.
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
        item_lower = (reading.utility_item or "").lower()
        if reading.category and reading.category.default_rate is not None:
            rate = reading.category.default_rate
        elif item_lower == "water":
            rate = reading.property.water_rate if reading.property else None
        elif item_lower == "electricity":
            rate = reading.property.electricity_rate if reading.property else None
        if rate is None:
            return jsonify({"error": f"No rate configured for {reading.utility_item}; pass an explicit amount."}), 400
        amount = Decimal(str(reading.consumption or 0)) * Decimal(str(rate))

    if amount <= 0:
        return jsonify({"error": "Computed amount is zero — set a consumption/rate or pass an amount."}), 400

    description = f"{reading.reading_month} — {reading.previous_reading or 0} to {reading.current_reading}"

    # Queued: nothing is billed today. The next invoice this unit gets — the
    # monthly run, or a manual invoice that opts in — picks it up.
    if mode == "queue":
        from services import invoice_queue_service as queue

        cat = reading.category
        sub = reading.subcategory or "current"
        label = (cat.subcategory_display().get(sub, cat.name) if cat
                 else (reading.utility_item or "Utility").capitalize())
        charge = queue.queue_charge(
            landlord_id, reading.unit,
            item=label,
            amount=amount,
            category_id=reading.category_id,
            subcategory=sub,
            description=f"{reading.reading_month} — "
                        f"{reading.previous_reading or 0} to {reading.current_reading}",
            utility_reading_id=reading.id,
            actor_user_id=int(get_jwt_identity()),
        )
        db.session.commit()
        return jsonify({
            "message": "Held for this unit's next invoice.",
            "queued_charge": charge.to_dict() if charge else None,
        }), 201

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

    # A utility reading bills the category's subcategory the reading was recorded
    # against (current / balance / deposit).
    cat_id = reading.category_id
    sub = reading.subcategory or "current"
    if reading.category:
        utility_name = reading.category.subcategory_display().get(sub, reading.category.name)
    else:
        utility_name = reading.utility_item.capitalize()
    if target is not None:
        db.session.add(InvoiceLineItem(
            invoice_id=target.id, item=utility_name, description=description,
            quantity=Decimal("1"), unit_price=amount, amount=amount, utility_reading_id=reading.id,
            category_id=cat_id, subcategory=sub,
        ))
        target.total_amount = (target.total_amount or Decimal("0")) + amount
        target.balance      = target.total_amount - (target.amount_paid or Decimal("0"))
        tenant.balance      = (tenant.balance or Decimal("0")) - amount
        # Append the utility's name to the invoice's title if it isn't already there —
        # "Rent" becomes "Rent, Electricity" (comma-joined, matching the invoice-form format).
        existing_names = [p.strip() for p in (target.title or "").split(",") if p.strip()]
        if utility_name not in existing_names:
            existing_names.append(utility_name)
            target.title = ", ".join(existing_names)
        invoice = target
    else:
        # New invoice (also the fallback when no open invoice exists for the month).
        issue_dt = _date.today()
        try:
            year, month = (int(x) for x in reading.reading_month.split("-")[:2])
            issue_dt = _date(year, month, 1)
        except (ValueError, AttributeError):
            pass
        invoice = _create_invoice(
            landlord_id, tenant, reading.unit, reading.property, "utility", issue_dt, None,
            [{
                "item": utility_name, "description": description,
                "quantity": 1, "unit_price": amount, "utility_reading_id": reading.id,
                "category_id": cat_id, "subcategory": sub,
            }],
            title=utility_name,
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