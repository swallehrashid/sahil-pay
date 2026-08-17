"""
routes/maintenance_routes.py — Maintenance Requests
Blueprint: maintenance_bp  |  Prefix: /api/maintenance

Status vocabulary (exactly as spec): open / in_progress / closed
Categories: electrical / plumbing / roofing / pest_control / roof_repair /
            locksmith / pool / garage / heating_cooling / handiwork /
            tiles / washroom / painting / security / other

Maintenance requests can be raised by landlord/team OR by tenants
(tenant portal posts here via the shared model).
The "create expense" shortcut pre-fills the expense form with the
request's property, unit, and a maintenance category.
"""

from flask import Blueprint, request, jsonify, abort, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    MaintenanceRequest, MaintenanceComment, Expense, MaintenanceStatus,
    ExpenseStatus, ExpenseCategory,
)
from decorators import (
    accessible_property_ids,
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service   import record_audit
from services.storage_service import upload_to_s3

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")


# ---------------------------------------------------------------------------
# GET /api/maintenance/
# ---------------------------------------------------------------------------
@maintenance_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "view")
@scope_to_accessible_properties
def list_requests():
    """
    List maintenance requests with summary counts.
    Filters: ?property_id=, ?unit_id=, ?status=, ?category=, ?page=, ?per_page=
    ---
    tags: [Maintenance]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated maintenance requests + summary.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = MaintenanceRequest.query.filter_by(landlord_id=landlord_id)
    open_query     = MaintenanceRequest.query.filter_by(landlord_id=landlord_id, status=MaintenanceStatus.open.value)
    progress_query = MaintenanceRequest.query.filter_by(landlord_id=landlord_id, status=MaintenanceStatus.in_progress.value)

    if g.accessible_property_ids is not None:
        query = query.filter(MaintenanceRequest.property_id.in_(g.accessible_property_ids))
        open_query = open_query.filter(MaintenanceRequest.property_id.in_(g.accessible_property_ids))
        progress_query = progress_query.filter(MaintenanceRequest.property_id.in_(g.accessible_property_ids))

    if v := request.args.get("property_id", type=int):
        query = query.filter(MaintenanceRequest.property_id == v)
    if v := request.args.get("unit_id", type=int):
        query = query.filter(MaintenanceRequest.unit_id == v)
    if v := request.args.get("status"):
        query = query.filter(MaintenanceRequest.status == v)
    if v := request.args.get("category"):
        query = query.filter(MaintenanceRequest.category == v)

    open_count     = open_query.count()
    progress_count = progress_query.count()

    paginated = query.order_by(MaintenanceRequest.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for req in paginated.items:
        d = req.to_dict()
        d["property_name"] = req.property.name if req.property else None
        d["unit_name"]     = req.unit.name     if req.unit     else None
        t = req.tenant
        d["tenant_name"]   = f"{t.first_name} {t.last_name}" if t else None
        items.append(d)

    return jsonify({
        "summary": {
            "open":        open_count,
            "in_progress": progress_count,
        },
        "requests":     items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/maintenance/
# ---------------------------------------------------------------------------
@maintenance_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "edit")
def create_request():
    """
    Create a maintenance request.
    Accepts multipart/form-data (for image upload) or JSON.
    Required: property_id, unit_id, summary.
    Optional: tenant_id, category, status, description, image file.
    ---
    tags: [Maintenance]
    security:
      - Bearer: []
    responses:
      201: {description: Request created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()

    if request.is_json:
        data      = request.get_json(silent=True) or {}
        image_url = None
    else:
        data      = request.form.to_dict()
        image     = request.files.get("image")
        image_url = upload_to_s3(image, folder=f"maintenance/{landlord_id}", profile="image") if image else None

    property_id = data.get("property_id")
    unit_id     = data.get("unit_id")
    summary     = (data.get("summary") or "").strip()

    if not all([property_id, unit_id, summary]):
        return jsonify({"error": "property_id, unit_id, and summary are required."}), 400

    req = MaintenanceRequest(
        landlord_id = landlord_id,
        property_id = int(property_id),
        unit_id     = int(unit_id),
        tenant_id   = int(data["tenant_id"]) if data.get("tenant_id") else None,
        summary     = summary,
        description = data.get("description"),
        category    = data.get("category"),
        status      = data.get("status", MaintenanceStatus.open.value),
        image_url   = image_url or data.get("image_url"),
    )
    db.session.add(req)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_maintenance_request",
        entity_type="maintenance",
        entity_id=req.id,
        description=f"Maintenance request created: '{summary}'.",
        after_data=req.to_dict(),
    )
    db.session.commit()
    return jsonify(req.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/maintenance/<id>
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:request_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "view")
def get_request(request_id):
    landlord_id = get_current_landlord_id()
    req         = _get_or_404(landlord_id, request_id)
    d           = req.to_dict()
    d["property_name"] = req.property.name if req.property else None
    d["unit_name"]     = req.unit.name     if req.unit     else None
    d["linked_expense"] = req.expense.to_dict() if req.expense else None
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/maintenance/<id>
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:request_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "edit")
def update_request(request_id):
    """Update a maintenance request (status, category, description, etc.)."""
    landlord_id = get_current_landlord_id()
    req         = _get_or_404(landlord_id, request_id)
    data        = request.get_json(silent=True) or {}
    before      = req.to_dict()

    for field in ["status", "category", "summary", "description", "image_url"]:
        if field in data:
            setattr(req, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_maintenance_request",
        entity_type="maintenance",
        entity_id=req.id,
        description=f"Maintenance request #{req.id} updated (status: {req.status}).",
        before_data=before,
        after_data=req.to_dict(),
    )
    db.session.commit()
    return jsonify(req.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/maintenance/<id>
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:request_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "edit")
def delete_request(request_id):
    """Hard-delete a maintenance request (no financial data — no soft-delete needed)."""
    landlord_id = get_current_landlord_id()
    req         = _get_or_404(landlord_id, request_id)

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_maintenance_request",
        entity_type="maintenance",
        entity_id=request_id,
        description=f"Maintenance request '{req.summary}' deleted.",
        before_data=req.to_dict(),
    )
    db.session.commit()

    db.session.delete(req)
    db.session.commit()
    return jsonify({"message": "Maintenance request deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/maintenance/<id>/create-expense
# ---------------------------------------------------------------------------
@maintenance_bp.route("/<int:request_id>/create-expense", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "edit")
def create_expense_from_request(request_id):
    """
    Create a linked Expense record pre-filled from this maintenance request.
    Body may override: amount, payment_method, notes, status.
    The expense is linked to the maintenance request via expense.maintenance_request_id.
    ---
    tags: [Maintenance]
    security:
      - Bearer: []
    responses:
      201: {description: Expense created and linked to maintenance request.}
      400: {description: Amount is required.}
    """
    from datetime import date
    landlord_id = get_current_landlord_id()
    req         = _get_or_404(landlord_id, request_id)
    data        = request.get_json(silent=True) or {}

    amount = data.get("amount")
    if not amount:
        return jsonify({"error": "amount is required to create an expense."}), 400

    expense = Expense(
        landlord_id            = landlord_id,
        property_id            = req.property_id,
        unit_id                = req.unit_id,
        category               = ExpenseCategory.maintenance.value,
        amount                 = amount,
        payment_method         = data.get("payment_method"),
        expense_date           = data.get("expense_date", str(date.today())),
        status                 = data.get("status", ExpenseStatus.pending.value),
        notes                  = data.get("notes") or req.description,
        maintenance_request_id = req.id,
    )
    db.session.add(expense)
    db.session.flush()

    # Link back (post_update handles circular FK)
    req.expense_id = expense.id
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_expense",
        entity_type="expense",
        entity_id=expense.id,
        description=f"Expense created from maintenance request #{req.id}.",
        after_data=expense.to_dict(),
    )
    db.session.commit()
    return jsonify(expense.to_dict()), 201


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, request_id: int) -> MaintenanceRequest:
    query = MaintenanceRequest.query.filter_by(id=request_id, landlord_id=landlord_id)
    # Property scope: a team member restricted to specific properties must not
    # be able to open an object from another property by guessing its id — under
    # a property manager that is one owner reading a rival owner's records. This
    # resolves the caller's scope on demand, so it holds even on routes that
    # never applied @scope_to_accessible_properties.
    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(MaintenanceRequest.property_id.in_(allowed))
    r = query.first()
    if not r:
        abort(404, description="Maintenance request not found.")
    return r

# ---------------------------------------------------------------------------
# Comments — the running conversation about a job
# ---------------------------------------------------------------------------
# A status says where a job is; it cannot say "plumber booked for Tuesday" or
# "tenant not home, rebooked". Without a place for those they live in WhatsApp
# and are gone the moment the person holding them is on leave.

@maintenance_bp.route("/<int:request_id>/comments", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "view")
def list_comments(request_id):
    """Every note on a request, internal ones included — this is the office view."""
    landlord_id = get_current_landlord_id()
    req = _get_or_404(landlord_id, request_id)
    return jsonify({
        "comments": [c.to_dict() for c in req.comments],
    }), 200


@maintenance_bp.route("/<int:request_id>/comments", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("maintenance", "edit")
def add_comment(request_id):
    """
    Add a note. Body: { body, is_internal? }

    `is_internal` defaults to FALSE — the common case is telling the tenant what
    is happening, and a default of "internal" would quietly hide updates from
    the one person waiting for them. Marking a note internal is the deliberate
    act, not the other way round.
    """
    landlord_id = get_current_landlord_id()
    req = _get_or_404(landlord_id, request_id)

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "A comment cannot be empty."}), 400

    from models import User

    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    name = None
    if user:
        tm = user.team_member_profile
        if tm:
            name = f"{tm.first_name or ''} {tm.last_name or ''}".strip() or tm.username
        else:
            name = getattr(user.landlord_profile, "company_name", None) or user.email

    comment = MaintenanceComment(
        request_id     = req.id,
        author_user_id = user_id,
        author_role    = user.role if user else "team_member",
        author_name    = name,
        body           = body,
        is_internal    = bool(data.get("is_internal", False)),
    )
    db.session.add(comment)
    db.session.flush()

    # Tell the tenant only about notes meant for them.
    if not comment.is_internal and req.tenant and req.tenant.user_id:
        from services.notification_service import notify
        notify(
            recipient_user_id=req.tenant.user_id,
            category="maintenance_update",
            title="Update on your maintenance request",
            body=f"{req.summary}: {body[:120]}",
            landlord_id=landlord_id,
            link="/portal/maintenance",
            entity_type="maintenance",
            entity_id=req.id,
        )

    record_audit(
        actor_user_id=user_id,
        landlord_id=landlord_id,
        action="comment_maintenance_request",
        entity_type="maintenance",
        entity_id=req.id,
        description=(f"Comment added to maintenance request #{req.id}"
                     f"{' (internal)' if comment.is_internal else ''}."),
    )
    db.session.commit()
    return jsonify(comment.to_dict()), 201
