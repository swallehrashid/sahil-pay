"""
routes/expense_routes.py — Expense Management
Blueprint: expense_bp  |  Prefix: /api/expenses

Status vocabulary (exactly as spec): confirmed / pending
Categories: garbage / maintenance / security / electricity / water /
            cleaning / internet / other

Includes one-off expenses AND recurring expense templates.
Recurring templates are instantiated on the 1st of each month by Celery Beat.
"""

from datetime import datetime, date

from flask import Blueprint, request, jsonify, abort, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Expense, RecurringExpense, ExpenseStatus
from decorators import (
    accessible_property_ids,
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service   import record_audit
from services.storage_service import upload_to_s3

expense_bp = Blueprint("expenses", __name__, url_prefix="/api/expenses")


# ---------------------------------------------------------------------------
# GET /api/expenses/
# ---------------------------------------------------------------------------
@expense_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "view")
@scope_to_accessible_properties
def list_expenses():
    """
    List expenses with total summary and filters.
    Filters: ?property_id=, ?unit_id=, ?start_date=, ?end_date=,
             ?min_amount=, ?max_amount=, ?status=, ?category=,
             ?page=, ?per_page=
    ---
    tags: [Expenses]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated expense list + total summary.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = Expense.query.filter_by(landlord_id=landlord_id, is_deleted=False)

    if g.accessible_property_ids is not None:
        query = query.filter(Expense.property_id.in_(g.accessible_property_ids))

    if v := request.args.get("property_id", type=int):
        query = query.filter(Expense.property_id == v)
    if v := request.args.get("unit_id", type=int):
        query = query.filter(Expense.unit_id == v)
    if v := request.args.get("start_date"):
        query = query.filter(Expense.expense_date >= v)
    if v := request.args.get("end_date"):
        query = query.filter(Expense.expense_date <= v)
    if v := request.args.get("min_amount", type=float):
        query = query.filter(Expense.amount >= v)
    if v := request.args.get("max_amount", type=float):
        query = query.filter(Expense.amount <= v)
    if v := request.args.get("status"):
        query = query.filter(Expense.status == v)
    if v := request.args.get("category"):
        query = query.filter(Expense.category == v)

    total = db.session.query(
        db.func.coalesce(db.func.sum(Expense.amount), 0)
    ).filter_by(landlord_id=landlord_id, is_deleted=False).scalar()

    paginated = query.order_by(Expense.expense_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for e in paginated.items:
        d = e.to_dict()
        d["property_name"] = e.property.name if e.property else None
        d["unit_name"]     = e.unit.name     if e.unit     else None
        items.append(d)

    return jsonify({
        "summary":      {"total_expenses": round(float(total), 2)},
        "expenses":     items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/expenses/
# ---------------------------------------------------------------------------
@expense_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def create_expense():
    """
    Record a one-off expense.
    Accepts multipart/form-data or JSON.
    Body: { property_id, amount, expense_date, category, status?,
            unit_id?, payment_method?, notes? }
    Optional file upload (receipt image).
    ---
    tags: [Expenses]
    security:
      - Bearer: []
    responses:
      201: {description: Expense created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()

    # Support both JSON and multipart
    if request.is_json:
        data = request.get_json(silent=True) or {}
        file_url = None
    else:
        data     = request.form.to_dict()
        file     = request.files.get("file")
        file_url = upload_to_s3(file, folder=f"expenses/{landlord_id}", profile="document") if file else None

    property_id  = data.get("property_id")
    amount       = data.get("amount")
    expense_date = data.get("expense_date")
    category     = data.get("category")

    if not all([property_id, amount, expense_date]):
        return jsonify({"error": "property_id, amount, and expense_date are required."}), 400

    expense = Expense(
        landlord_id    = landlord_id,
        property_id    = int(property_id),
        unit_id        = int(data["unit_id"]) if data.get("unit_id") else None,
        category       = category,
        amount         = amount,
        payment_method = data.get("payment_method"),
        expense_date   = expense_date,
        status         = data.get("status", ExpenseStatus.pending.value),
        notes          = data.get("notes"),
        file_url       = file_url or data.get("file_url"),
    )
    db.session.add(expense)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_expense",
        entity_type="expense",
        entity_id=expense.id,
        description=f"Expense of KES {amount} ({category}) recorded.",
        after_data=expense.to_dict(),
    )
    db.session.commit()
    return jsonify(expense.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/expenses/<id>
# ---------------------------------------------------------------------------
@expense_bp.route("/<int:expense_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "view")
def get_expense(expense_id):
    landlord_id = get_current_landlord_id()
    expense     = _get_or_404(landlord_id, expense_id)
    d           = expense.to_dict()
    d["property_name"] = expense.property.name if expense.property else None
    d["unit_name"]     = expense.unit.name     if expense.unit     else None
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/expenses/<id>
# ---------------------------------------------------------------------------
@expense_bp.route("/<int:expense_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def update_expense(expense_id):
    landlord_id = get_current_landlord_id()
    expense     = _get_or_404(landlord_id, expense_id)
    data        = request.get_json(silent=True) or {}
    before      = expense.to_dict()

    for field in ["category", "amount", "payment_method", "expense_date",
                  "status", "notes", "property_id", "unit_id"]:
        if field in data:
            setattr(expense, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_expense",
        entity_type="expense",
        entity_id=expense.id,
        description="Expense updated.",
        before_data=before,
        after_data=expense.to_dict(),
    )
    db.session.commit()
    return jsonify(expense.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/expenses/<id>  (soft delete)
# ---------------------------------------------------------------------------
@expense_bp.route("/<int:expense_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def delete_expense(expense_id):
    landlord_id = get_current_landlord_id()
    expense     = _get_or_404(landlord_id, expense_id)
    before      = expense.to_dict()

    expense.is_deleted = True
    expense.deleted_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_expense",
        entity_type="expense",
        entity_id=expense.id,
        description="Expense soft-deleted.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": "Expense deleted."}), 200


# ===========================================================================
# Recurring Expense Templates
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/expenses/recurring
# ---------------------------------------------------------------------------
@expense_bp.route("/recurring", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "view")
def list_recurring_expenses():
    """
    List all active recurring expense templates.
    ---
    tags: [Expenses]
    security:
      - Bearer: []
    responses:
      200: {description: Recurring expense templates.}
    """
    landlord_id = get_current_landlord_id()
    templates   = RecurringExpense.query.filter_by(
        landlord_id=landlord_id, is_active=True
    ).all()
    return jsonify({
        "recurring_expenses": [t.to_dict() for t in templates],
        "total": len(templates),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/expenses/recurring
# ---------------------------------------------------------------------------
@expense_bp.route("/recurring", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def create_recurring_expense():
    """
    Create a recurring expense template.
    Celery Beat will instantiate this into an Expense row on the 1st of each month.
    Body: { property_id?, unit_id?, category, amount, payment_method?,
            notes?, day_of_month? (default 1) }
    At least one of property_id / unit_id must be provided.
    ---
    tags: [Expenses]
    security:
      - Bearer: []
    responses:
      201: {description: Recurring template created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    property_id = data.get("property_id")
    unit_id     = data.get("unit_id")
    amount      = data.get("amount")

    if not (property_id or unit_id):
        return jsonify({"error": "At least one of property_id or unit_id is required."}), 400
    if not amount:
        return jsonify({"error": "amount is required."}), 400

    template = RecurringExpense(
        landlord_id    = landlord_id,
        property_id    = property_id,
        unit_id        = unit_id,
        category       = data.get("category"),
        amount         = amount,
        payment_method = data.get("payment_method"),
        notes          = data.get("notes"),
        day_of_month   = data.get("day_of_month", 1),
        is_active      = True,
    )
    db.session.add(template)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_recurring_expense",
        entity_type="recurring_expense",
        entity_id=template.id,
        description=f"Recurring expense template created (KES {amount}/month).",
        after_data=template.to_dict(),
    )
    db.session.commit()
    return jsonify(template.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/expenses/recurring/<id>
# ---------------------------------------------------------------------------
@expense_bp.route("/recurring/<int:template_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def update_recurring_expense(template_id):
    landlord_id = get_current_landlord_id()
    template    = RecurringExpense.query.filter_by(
        id=template_id, landlord_id=landlord_id
    ).first()
    if not template:
        abort(404, description="Recurring expense template not found.")

    data   = request.get_json(silent=True) or {}
    before = template.to_dict()

    for field in ["category", "amount", "payment_method", "notes",
                  "day_of_month", "property_id", "unit_id"]:
        if field in data:
            setattr(template, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_recurring_expense",
        entity_type="recurring_expense",
        entity_id=template.id,
        description="Recurring expense template updated.",
        before_data=before,
        after_data=template.to_dict(),
    )
    db.session.commit()
    return jsonify(template.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/expenses/recurring/<id>  (deactivate)
# ---------------------------------------------------------------------------
@expense_bp.route("/recurring/<int:template_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("expenses", "edit")
def deactivate_recurring_expense(template_id):
    """Deactivate (not hard-delete) a recurring expense template."""
    landlord_id = get_current_landlord_id()
    template    = RecurringExpense.query.filter_by(
        id=template_id, landlord_id=landlord_id
    ).first()
    if not template:
        abort(404, description="Recurring expense template not found.")

    template.is_active = False
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="deactivate_recurring_expense",
        entity_type="recurring_expense",
        entity_id=template.id,
        description="Recurring expense template deactivated.",
    )
    db.session.commit()
    return jsonify({"message": "Recurring expense deactivated."}), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, expense_id: int) -> Expense:
    query = Expense.query.filter_by(id=expense_id, landlord_id=landlord_id, is_deleted=False)
    # Property scope: a team member restricted to specific properties must not
    # be able to open an object from another property by guessing its id — under
    # a property manager that is one owner reading a rival owner's records. This
    # resolves the caller's scope on demand, so it holds even on routes that
    # never applied @scope_to_accessible_properties.
    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(Expense.property_id.in_(allowed))
    e = query.first()
    if not e:
        abort(404, description="Expense not found or access denied.")
    return e