"""
routes/tenant_routes.py — Landlord-Side Tenant Management
Blueprint: tenant_bp  |  Prefix: /api/tenants

This is the landlord's view of tenants — NOT the tenant's own portal
(that lives in tenant_portal_routes.py).

Covers all 11 per-tenant row actions from §4.5:
  edit, view transactions, send balance reminder, add invoice, add payment,
  send custom message, send statement, download statement, download CSV,
  shift tenant, delete tenant.

Deletes are soft (is_deleted=True). Deleted tenants are never hard-removed —
they appear in the /deleted view and deleted-tenants report.
"""

import csv
import io
from datetime import datetime, date

from flask import Blueprint, request, jsonify, abort, Response, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Tenant, Unit, Property, TenantUnitHistory, TenantDocument,
    Invoice, Payment, CommunicationLog,
    CommunicationStatus, MessageChannel, RecipientType,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service   import record_audit
from services.pdf_service     import generate_tenant_statement_pdf
from services.sms_service     import send_sms
from services.email_service   import send_statement_email
from services.storage_service import upload_to_s3

tenant_bp = Blueprint("tenants", __name__, url_prefix="/api/tenants")


# ---------------------------------------------------------------------------
# GET /api/tenants/
# ---------------------------------------------------------------------------
@tenant_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
@scope_to_accessible_properties
def list_tenants():
    """
    List active (non-deleted) tenants for the current landlord.
    Returns summary: total_tenants, total_arrears, leases_expiring_soon.

    Filters: ?property_id=, ?unit_id=, ?search= (name/phone), ?page=, ?per_page=
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated tenant list + summary.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)
    prop_id     = request.args.get("property_id", type=int)
    unit_id     = request.args.get("unit_id",     type=int)
    search      = request.args.get("search", "").strip()

    query = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    all_tenants_query = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False)

    # Property-scoped team members only see tenants in units under their
    # assigned properties. Tenant has no property_id directly, so scope via
    # a subquery on Unit rather than joining (avoids clashing with the
    # ?property_id= join below).
    if g.accessible_property_ids is not None:
        accessible_unit_ids = db.session.query(Unit.id).filter(
            Unit.property_id.in_(g.accessible_property_ids)
        )
        query = query.filter(Tenant.unit_id.in_(accessible_unit_ids))
        all_tenants_query = all_tenants_query.filter(Tenant.unit_id.in_(accessible_unit_ids))

    if prop_id:
        query = query.join(Unit).filter(Unit.property_id == prop_id)
    if unit_id:
        query = query.filter(Tenant.unit_id == unit_id)
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Tenant.first_name.ilike(like),
                Tenant.last_name.ilike(like),
                Tenant.phone.ilike(like),
            )
        )

    all_tenants     = all_tenants_query.all()
    total_arrears   = sum(abs(float(t.balance)) for t in all_tenants if t.balance < 0)

    # Leases expiring within 30 days
    in_30           = date.today()
    from datetime import timedelta
    near_expiry_date = date.today() + timedelta(days=30)
    leases_expiring = sum(
        1 for t in all_tenants
        if t.lease_expiry_date and in_30 <= t.lease_expiry_date <= near_expiry_date
    )

    paginated = query.order_by(Tenant.last_name, Tenant.first_name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for t in paginated.items:
        d = t.to_dict()
        unit = t.unit
        d["unit_name"]     = unit.name       if unit else None
        d["property_name"] = unit.property.name if (unit and unit.property) else None
        d["property_id"]   = unit.property_id   if unit else None
        items.append(d)

    return jsonify({
        "summary": {
            "total_tenants":     len(all_tenants),
            "total_arrears":     round(total_arrears, 2),
            "leases_expiring":   leases_expiring,
        },
        "tenants":      items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/
# ---------------------------------------------------------------------------
@tenant_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def create_tenant():
    """
    Add a new tenant.  Required: unit_id, first_name, last_name, phone.
    Optional: all other fields per §4.5 form spec.
    Sets unit.is_occupied = True on creation.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      201: {description: Tenant created.}
      400: {description: Validation error or unit already occupied.}
      404: {description: Unit not found.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    unit_id    = data.get("unit_id")
    first_name = (data.get("first_name") or "").strip()
    last_name  = (data.get("last_name")  or "").strip()
    phone      = (data.get("phone")      or "").strip()

    if not all([unit_id, first_name, last_name, phone]):
        return jsonify({"error": "unit_id, first_name, last_name, and phone are required."}), 400

    unit = Unit.query.join(Property).filter(
        Unit.id == unit_id,
        Property.landlord_id == landlord_id,
        Unit.is_deleted.is_(False),
    ).first()
    if not unit:
        return jsonify({"error": "Unit not found."}), 404
    if unit.is_occupied:
        return jsonify({"error": "This unit is already occupied."}), 400

    # Build tenant
    tenant = Tenant(
        landlord_id          = landlord_id,
        unit_id              = unit_id,
        first_name           = first_name,
        last_name            = last_name,
        phone                = phone,
        secondary_phone      = data.get("secondary_phone"),
        email                = (data.get("email") or "").lower() or None,
        national_id          = data.get("national_id"),
        kra_pin              = data.get("kra_pin"),
        account_number       = data.get("account_number"),
        deposit_amount       = data.get("deposit_amount"),
        deposit_paid         = data.get("deposit_paid"),
        deposit_returned     = data.get("deposit_returned"),
        rent_payment_penalty = data.get("rent_payment_penalty"),
        bank_payer_name      = data.get("bank_payer_name"),
        balance              = 0,
        lease_start_date     = _parse_date(data.get("lease_start_date")),
        lease_expiry_date    = _parse_date(data.get("lease_expiry_date")),
        move_in_date         = _parse_date(data.get("move_in_date")),
        move_out_date        = _parse_date(data.get("move_out_date")),
        notes                = data.get("notes"),
    )
    db.session.add(tenant)
    db.session.flush()

    # Mark unit occupied + record unit history
    unit.is_occupied = True
    history = TenantUnitHistory(
        tenant_id   = tenant.id,
        unit_id     = unit_id,
        moved_in_at = tenant.move_in_date or date.today(),
    )
    db.session.add(history)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_tenant",
        entity_type="tenant",
        entity_id=tenant.id,
        description=f"Tenant '{first_name} {last_name}' added to unit '{unit.name}'.",
        after_data=tenant.to_dict(),
    )
    db.session.commit()

    return jsonify(tenant.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/tenants/deleted
# ---------------------------------------------------------------------------
@tenant_bp.route("/deleted", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def list_deleted_tenants():
    """
    View soft-deleted tenants. Bypasses the default soft-delete filter.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Deleted tenant list.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    paginated = (
        Tenant.query
        .filter_by(landlord_id=landlord_id, is_deleted=True)
        .order_by(Tenant.deleted_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return jsonify({
        "tenants":      [t.to_dict() for t in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/tenants/<id>
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
@scope_to_accessible_properties
def get_tenant(tenant_id):
    """Return full detail for one tenant including unit/property info."""
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    d           = tenant.to_dict()
    unit        = tenant.unit
    d["unit_name"]     = unit.name       if unit else None
    d["property_name"] = unit.property.name if (unit and unit.property) else None
    d["property_id"]   = unit.property_id   if unit else None
    d["documents"]     = [doc.to_dict() for doc in tenant.documents]
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/tenants/<id>
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def update_tenant(tenant_id):
    """Partial update of a tenant's editable fields."""
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    data        = request.get_json(silent=True) or {}
    before      = tenant.to_dict()

    editable = [
        "first_name", "last_name", "phone", "secondary_phone", "email",
        "national_id", "kra_pin", "account_number", "deposit_amount",
        "deposit_paid", "deposit_returned", "rent_payment_penalty",
        "bank_payer_name", "notes",
    ]
    for field in editable:
        if field in data:
            setattr(tenant, field, data[field])

    for date_field in ["lease_start_date", "lease_expiry_date", "move_in_date", "move_out_date"]:
        if date_field in data:
            setattr(tenant, date_field, _parse_date(data[date_field]))

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_tenant",
        entity_type="tenant",
        entity_id=tenant.id,
        description=f"Tenant '{tenant.first_name} {tenant.last_name}' updated.",
        before_data=before,
        after_data=tenant.to_dict(),
    )
    db.session.commit()
    return jsonify(tenant.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/tenants/<id>  (soft delete)
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def delete_tenant(tenant_id):
    """
    Soft-delete a tenant. The tenant's unit is freed (is_occupied = False).
    TenantUnitHistory moved_out_at is set to today.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant soft-deleted.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    before      = tenant.to_dict()

    tenant.is_deleted  = True
    tenant.deleted_at  = datetime.utcnow()
    tenant.move_out_date = date.today()

    # Free the unit
    unit = tenant.unit
    if unit:
        unit.is_occupied = False

    # Close unit history entry
    history = (
        TenantUnitHistory.query
        .filter_by(tenant_id=tenant.id, unit_id=tenant.unit_id)
        .filter(TenantUnitHistory.moved_out_at.is_(None))
        .first()
    )
    if history:
        history.moved_out_at = date.today()

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_tenant",
        entity_type="tenant",
        entity_id=tenant.id,
        description=f"Tenant '{tenant.first_name} {tenant.last_name}' soft-deleted.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": "Tenant deleted successfully."}), 200


# ---------------------------------------------------------------------------
# GET /api/tenants/<id>/transactions
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/transactions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def get_transactions(tenant_id):
    """
    Full transaction ledger for one tenant:
    invoices (ordered by issue_date) + payments (ordered by payment_date).
    Running balance is computed in Python and included.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Chronological ledger entries with running balance.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)

    entries = []
    for inv in tenant.invoices:
        if not inv.is_deleted:
            entries.append({
                "type":        "invoice",
                "date":        str(inv.issue_date),
                "item":        inv.invoice_type,
                "description": inv.title,
                "amount_due":  float(inv.total_amount),
                "amount_paid": float(inv.amount_paid),
                "status":      inv.status,
                "ref":         inv.invoice_number,
            })
    for pay in tenant.payments:
        if not pay.is_deleted:
            entries.append({
                "type":        "payment",
                "date":        str(pay.payment_date),
                "item":        pay.source,
                "description": pay.notes,
                "amount":      float(pay.amount),
                "status":      pay.status,
                "ref":         pay.payment_ref,
            })

    entries.sort(key=lambda x: x["date"])

    # Compute running balance
    running = 0.0
    for e in entries:
        if e["type"] == "invoice":
            running += e["amount_due"]
        else:
            running -= e["amount"]
        e["running_balance"] = round(running, 2)

    return jsonify({
        "tenant_id":      tenant.id,
        "current_balance": float(tenant.balance),
        "transactions":   entries,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/<id>/shift
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/shift", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def shift_tenant(tenant_id):
    """
    Move a tenant to a different unit.
    Body: { new_unit_id, move_date (optional, defaults to today) }
    Closes the current TenantUnitHistory entry and opens a new one.
    Frees the old unit and marks the new unit occupied.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant shifted to new unit.}
      400: {description: New unit is occupied or same as current.}
      404: {description: New unit not found.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    data        = request.get_json(silent=True) or {}

    new_unit_id = data.get("new_unit_id")
    move_date   = _parse_date(data.get("move_date")) or date.today()

    if not new_unit_id:
        return jsonify({"error": "new_unit_id is required."}), 400
    if new_unit_id == tenant.unit_id:
        return jsonify({"error": "New unit is the same as the current unit."}), 400

    new_unit = Unit.query.join(Property).filter(
        Unit.id == new_unit_id,
        Property.landlord_id == landlord_id,
        Unit.is_deleted.is_(False),
    ).first()
    if not new_unit:
        return jsonify({"error": "New unit not found."}), 404
    if new_unit.is_occupied:
        return jsonify({"error": "New unit is already occupied."}), 400

    old_unit = tenant.unit

    # Close current history
    current_history = (
        TenantUnitHistory.query
        .filter_by(tenant_id=tenant.id, unit_id=tenant.unit_id)
        .filter(TenantUnitHistory.moved_out_at.is_(None))
        .first()
    )
    if current_history:
        current_history.moved_out_at = move_date

    # Open new history
    db.session.add(TenantUnitHistory(
        tenant_id   = tenant.id,
        unit_id     = new_unit_id,
        moved_in_at = move_date,
    ))

    # Flip occupancy
    if old_unit:
        old_unit.is_occupied = False
    new_unit.is_occupied   = True
    tenant.unit_id         = new_unit_id
    tenant.move_in_date    = move_date

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="shift_tenant",
        entity_type="tenant",
        entity_id=tenant.id,
        description=(
            f"Tenant '{tenant.first_name} {tenant.last_name}' shifted "
            f"from unit '{old_unit.name if old_unit else '?'}' "
            f"to '{new_unit.name}' on {move_date}."
        ),
    )
    db.session.commit()

    return jsonify({"message": "Tenant shifted successfully.", "tenant": tenant.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/<id>/reminder
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/reminder", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def send_reminder(tenant_id):
    """
    Send a balance reminder to a single tenant via SMS/WhatsApp/email.
    Body: { channel: 'sms'|'whatsapp'|'email', message?: str }
    Decrements SMS balance if channel is 'sms'.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Reminder sent.}
    """
    from services.communication_service import dispatch_message
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    data        = request.get_json(silent=True) or {}

    channel = data.get("channel", MessageChannel.sms.value)
    message = data.get("message") or (
        f"Dear {tenant.first_name}, your outstanding balance is "
        f"KES {abs(float(tenant.balance)):,.2f}. "
        f"Please make your payment to avoid penalties."
    )

    dispatch_message(
        landlord_id=landlord_id,
        tenant=tenant,
        channel=channel,
        content=message,
    )

    return jsonify({"message": f"Reminder sent to {tenant.first_name} via {channel}."}), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/bulk-reminder
# ---------------------------------------------------------------------------
@tenant_bp.route("/bulk-reminder", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def bulk_reminder():
    """
    Send balance reminders to a list of tenant IDs.
    Body: { tenant_ids: [int], channel: str, message?: str }
    Queued via Celery to avoid request timeout on large batches.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Bulk reminder task queued.}
    """
    from tasks.communication_tasks import send_bulk_reminders
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}
    tenant_ids  = data.get("tenant_ids", [])
    channel     = data.get("channel", MessageChannel.sms.value)
    message     = data.get("message")

    if not tenant_ids:
        return jsonify({"error": "tenant_ids list is required."}), 400

    send_bulk_reminders.delay(landlord_id, tenant_ids, channel, message)

    return jsonify({"message": f"Bulk reminder queued for {len(tenant_ids)} tenant(s)."}), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/<id>/statement/send
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/statement/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def send_statement(tenant_id):
    """
    Generate and email the tenant statement PDF to the tenant.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: Statement emailed.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)

    pdf_bytes = generate_tenant_statement_pdf(tenant)
    send_statement_email.delay(tenant.email, tenant.first_name, pdf_bytes)

    return jsonify({"message": f"Statement sent to {tenant.email or tenant.phone}."}), 200


# ---------------------------------------------------------------------------
# GET /api/tenants/<id>/statement/download
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/statement/download", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def download_statement(tenant_id):
    """
    Stream a PDF statement for the tenant directly to the browser.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: PDF stream.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)
    pdf_bytes   = generate_tenant_statement_pdf(tenant)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=statement_{tenant.last_name}_{tenant.id}.pdf"
            )
        },
    ), 200


# ---------------------------------------------------------------------------
# GET /api/tenants/<id>/export.csv
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/export.csv", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def export_tenant_csv(tenant_id):
    """
    Download a CSV of a single tenant's transaction history.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: CSV file.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Item", "Amount Due", "Amount Paid", "Status", "Reference"])

    for inv in sorted(tenant.invoices, key=lambda x: x.issue_date):
        if not inv.is_deleted:
            writer.writerow([
                str(inv.issue_date), "Invoice", inv.invoice_type,
                float(inv.total_amount), float(inv.amount_paid),
                inv.status, inv.invoice_number,
            ])
    for pay in sorted(tenant.payments, key=lambda x: x.payment_date):
        if not pay.is_deleted:
            writer.writerow([
                str(pay.payment_date), "Payment", pay.source,
                "", float(pay.amount), pay.status, pay.payment_ref,
            ])

    csv_data = output.getvalue()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=tenant_{tenant.last_name}_{tenant.id}.csv"
            )
        },
    ), 200


# ---------------------------------------------------------------------------
# GET /api/tenants/export.pdf
# ---------------------------------------------------------------------------
@tenant_bp.route("/export.pdf", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def export_all_tenants_pdf():
    """
    Download a PDF of all active tenants in a formatted table.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      200: {description: PDF file.}
    """
    from services.pdf_service import generate_tenants_list_pdf
    landlord_id = get_current_landlord_id()
    tenants     = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False).all()
    pdf_bytes   = generate_tenants_list_pdf(tenants)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": "attachment; filename=all_tenants.pdf"},
    ), 200


# ---------------------------------------------------------------------------
# POST /api/tenants/<id>/documents
# ---------------------------------------------------------------------------
@tenant_bp.route("/<int:tenant_id>/documents", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def upload_document(tenant_id):
    """
    Upload a document to a tenant's folder.
    Expects multipart/form-data with 'file' and optional 'name' fields.
    File is stored in S3 / Cloudinary and a TenantDocument row is created.
    ---
    tags: [Tenants]
    security:
      - Bearer: []
    responses:
      201: {description: Document uploaded.}
      400: {description: No file provided.}
    """
    landlord_id = get_current_landlord_id()
    tenant      = _get_or_404(landlord_id, tenant_id)

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "A file is required."}), 400

    name     = request.form.get("name") or file.filename
    file_url = upload_to_s3(file, folder=f"tenants/{tenant.id}/documents")

    doc = TenantDocument(
        tenant_id = tenant.id,
        name      = name,
        file_url  = file_url,
    )
    db.session.add(doc)
    db.session.commit()

    return jsonify(doc.to_dict()), 201


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, tenant_id: int) -> Tenant:
    t = Tenant.query.filter_by(
        id=tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not t:
        abort(404, description="Tenant not found or access denied.")
    accessible = getattr(g, "accessible_property_ids", None)
    if accessible is not None and (not t.unit or t.unit.property_id not in accessible):
        abort(404, description="Tenant not found or access denied.")
    return t


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None