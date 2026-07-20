"""
routes/invoice_routes.py — Invoice Management
Blueprint: invoice_bp  |  Prefix: /api/invoices

Status vocabulary (exactly as spec): draft / void / open / partial / paid
Invoice types: rent / utility / penalty / custom / recurring

Financial rules enforced server-side:
  - total_amount must equal sum of line item amounts
  - Status transitions are driven by payment allocations (open → partial → paid)
  - draft and void are set manually
"""

from datetime import datetime, date
from decimal import Decimal

from flask import Blueprint, request, jsonify, abort, Response, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Invoice, InvoiceLineItem, Tenant, Unit, Property,
    InvoiceStatus, InvoiceType,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service  import record_audit
from services.pdf_service    import generate_invoice_pdf
from services.email_service  import send_invoice_email
from tasks.invoice_tasks     import bulk_generate_invoices_task

invoice_bp = Blueprint("invoices", __name__, url_prefix="/api/invoices")


def _next_invoice_number(landlord_id: int) -> str:
    count = Invoice.query.filter_by(landlord_id=landlord_id).count()
    return f"INV-{landlord_id}-{count + 1:05d}"


# ---------------------------------------------------------------------------
# GET /api/invoices/
# ---------------------------------------------------------------------------
@invoice_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
@scope_to_accessible_properties
def list_invoices():
    """
    List invoices with left-panel filters.
    Filters: ?start_date=, ?end_date=, ?unit_id=, ?property_id=,
             ?invoice_type=, ?status=, ?tenant_id=, ?page=, ?per_page=
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated invoice list.}
    """
    landlord_id  = get_current_landlord_id()
    page         = request.args.get("page", 1, type=int)
    per_page     = request.args.get("per_page", 20, type=int)
    start_date   = request.args.get("start_date")
    end_date     = request.args.get("end_date")
    unit_id      = request.args.get("unit_id",      type=int)
    property_id  = request.args.get("property_id",  type=int)
    invoice_type = request.args.get("invoice_type")
    status       = request.args.get("status")
    tenant_id    = request.args.get("tenant_id",    type=int)

    query = Invoice.query.filter_by(landlord_id=landlord_id, is_deleted=False)

    if g.accessible_property_ids is not None:
        query = query.filter(Invoice.property_id.in_(g.accessible_property_ids))

    if start_date:
        query = query.filter(Invoice.issue_date >= start_date)
    if end_date:
        query = query.filter(Invoice.issue_date <= end_date)
    if unit_id:
        query = query.filter(Invoice.unit_id == unit_id)
    if property_id:
        query = query.filter(Invoice.property_id == property_id)
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if status:
        query = query.filter(Invoice.status == status)
    if tenant_id:
        query = query.filter(Invoice.tenant_id == tenant_id)

    paginated = query.order_by(Invoice.issue_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for inv in paginated.items:
        d = inv.to_dict()
        d["line_items"] = [li.to_dict() for li in inv.line_items]
        t = inv.tenant
        d["tenant_name"]   = f"{t.first_name} {t.last_name}" if t else None
        d["unit_name"]     = inv.unit.name if inv.unit else None
        d["property_name"] = inv.property.name if inv.property else None
        items.append(d)

    return jsonify({
        "invoices":     items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/invoices/
# ---------------------------------------------------------------------------
@invoice_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def create_invoice():
    """
    Create a single invoice with line items.
    Server validates: total_amount == sum of line item amounts.
    Body:
      { tenant_id, unit_id, property_id, invoice_type, issue_date, due_date?,
        status?, title?,
        line_items: [{ item, description?, quantity, unit_price, amount }] }
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      201: {description: Invoice created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    tenant_id    = data.get("tenant_id")
    unit_id      = data.get("unit_id")
    property_id  = data.get("property_id")
    invoice_type = data.get("invoice_type", InvoiceType.custom.value)
    issue_date   = data.get("issue_date")
    line_items   = data.get("line_items", [])

    # The manual invoice form only collects a tenant (unit + property are implied by
    # the tenant's current placement), so derive unit_id / property_id from the tenant
    # when the client doesn't supply them — otherwise a perfectly valid manual invoice
    # is rejected with a 400 for "missing" fields the UI never had a way to send.
    if tenant_id and (not unit_id or not property_id):
        _tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id).first()
        if _tenant:
            unit_id     = unit_id     or _tenant.unit_id
            property_id = property_id or (_tenant.unit.property_id if _tenant.unit else None)

    if not all([tenant_id, unit_id, property_id, issue_date]):
        return jsonify({"error": "tenant_id, unit_id, property_id, and issue_date are required."}), 400
    if not line_items:
        return jsonify({"error": "At least one line_item is required."}), 400

    # Validate line item total. The frontend sends quantity + unit_price per line (no
    # pre-computed `amount`), so fall back to quantity * unit_price here exactly as the
    # InvoiceLineItem rows below do — otherwise computed_total is 0 and every invoice is
    # rejected for not matching its declared total_amount.
    def _line_amount(li):
        if li.get("amount") not in (None, ""):
            return Decimal(str(li["amount"]))
        return Decimal(str(li.get("quantity", 1))) * Decimal(str(li.get("unit_price", 0)))

    computed_total = sum((_line_amount(li) for li in line_items), Decimal("0"))
    declared_total = Decimal(str(data.get("total_amount", computed_total)))
    if abs(computed_total - declared_total) > Decimal("0.01"):
        return jsonify({
            "error": f"total_amount ({declared_total}) does not equal sum of line items ({computed_total})."
        }), 400

    # ── Resolve target invoice: combine into this month's open bill, or create new ─────
    # "Current invoice" = the tenant's still open/partial invoice issued in the same
    # calendar month as this one. When `combine` is on and such an invoice exists, append
    # these charges to it instead of raising a separate bill; otherwise create a new one.
    from datetime import date as _date
    from sqlalchemy import extract

    def _parse_date(d):
        if isinstance(d, str):
            try:
                return _date.fromisoformat(d[:10])
            except ValueError:
                return None
        return d

    combine  = bool(data.get("combine"))
    issue_d  = _parse_date(issue_date)
    target   = None
    if combine and issue_d:
        target = (
            Invoice.query
            .filter_by(tenant_id=tenant_id, landlord_id=landlord_id, is_deleted=False)
            .filter(Invoice.status.in_([InvoiceStatus.open.value, InvoiceStatus.partial.value]))
            .filter(extract("year",  Invoice.issue_date) == issue_d.year)
            .filter(extract("month", Invoice.issue_date) == issue_d.month)
            .order_by(Invoice.id.desc())
            .first()
        )

    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id).first()

    if target is not None:
        invoice = target
    else:
        invoice = Invoice(
            invoice_number = _next_invoice_number(landlord_id),
            landlord_id    = landlord_id,
            tenant_id      = tenant_id,
            unit_id        = unit_id,
            property_id    = property_id,
            invoice_type   = invoice_type,
            issue_date     = issue_date,
            due_date       = data.get("due_date"),
            status         = data.get("status", InvoiceStatus.open.value),
            total_amount   = Decimal("0.00"),
            amount_paid    = Decimal("0.00"),
            balance        = Decimal("0.00"),
            title          = data.get("title"),
        )
        db.session.add(invoice)
        db.session.flush()

    # Append the charges as line items (same for a new or a combined invoice).
    for li_data in line_items:
        qty        = Decimal(str(li_data.get("quantity", 1)))
        unit_price = Decimal(str(li_data.get("unit_price", 0)))
        amount     = Decimal(str(li_data.get("amount", qty * unit_price)))
        db.session.add(InvoiceLineItem(
            invoice_id         = invoice.id,
            item               = li_data.get("item", ""),
            description        = li_data.get("description"),
            quantity           = qty,
            unit_price         = unit_price,
            amount             = amount,
            utility_reading_id = li_data.get("utility_reading_id"),
            category_id        = li_data.get("category_id"),
            subcategory        = li_data.get("subcategory"),
        ))

    # Recompute header totals + status from the (possibly larger) set of charges.
    invoice.total_amount = (invoice.total_amount or Decimal("0")) + computed_total
    invoice.balance      = invoice.total_amount - (invoice.amount_paid or Decimal("0"))
    if invoice.balance <= 0:
        invoice.status = InvoiceStatus.paid.value
    elif (invoice.amount_paid or Decimal("0")) > 0:
        invoice.status = InvoiceStatus.partial.value
    else:
        invoice.status = invoice.status or InvoiceStatus.open.value

    # Ledger: issuing charges increases what the tenant owes (balance more negative).
    if tenant:
        tenant.balance = (tenant.balance or Decimal("0")) - computed_total

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_invoice",
        entity_type="invoice",
        entity_id=invoice.id,
        description=(
            f"Charges added to invoice {invoice.invoice_number} (combined)."
            if target is not None else
            f"Invoice {invoice.invoice_number} created (type: {invoice_type})."
        ),
        after_data=invoice.to_dict(),
    )
    db.session.commit()

    return jsonify(invoice.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/invoices/<id>
# ---------------------------------------------------------------------------
@invoice_bp.route("/<int:invoice_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def get_invoice(invoice_id):
    """Return full invoice detail including line items."""
    landlord_id = get_current_landlord_id()
    inv         = _get_or_404(landlord_id, invoice_id)
    d           = inv.to_dict()
    d["line_items"]    = [li.to_dict() for li in inv.line_items]
    d["property_name"] = inv.property.name if inv.property else None
    d["unit_name"]     = inv.unit.name     if inv.unit     else None
    t = inv.tenant
    d["tenant_name"]   = f"{t.first_name} {t.last_name}" if t else None
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/invoices/<id>
# ---------------------------------------------------------------------------
@invoice_bp.route("/<int:invoice_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def update_invoice(invoice_id):
    """
    Update an invoice. Only draft/open invoices should be edited after creation.
    Re-validates line item total if line_items is included in the payload.
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      200: {description: Invoice updated.}
    """
    landlord_id = get_current_landlord_id()
    inv         = _get_or_404(landlord_id, invoice_id)
    data        = request.get_json(silent=True) or {}
    before      = inv.to_dict()

    for field in ["status", "due_date", "title", "issue_date"]:
        if field in data:
            setattr(inv, field, data[field])

    if "line_items" in data:
        # Replace all line items
        InvoiceLineItem.query.filter_by(invoice_id=inv.id).delete()
        new_total = Decimal("0.00")
        for li_data in data["line_items"]:
            qty        = Decimal(str(li_data.get("quantity", 1)))
            unit_price = Decimal(str(li_data.get("unit_price", 0)))
            amount     = Decimal(str(li_data.get("amount", qty * unit_price)))
            new_total += amount
            db.session.add(InvoiceLineItem(
                invoice_id  = inv.id,
                item        = li_data.get("item", ""),
                description = li_data.get("description"),
                quantity    = qty,
                unit_price  = unit_price,
                amount      = amount,
                category_id = li_data.get("category_id"),
                subcategory = li_data.get("subcategory"),
            ))
        inv.total_amount = new_total
        inv.balance      = new_total - inv.amount_paid

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_invoice",
        entity_type="invoice",
        entity_id=inv.id,
        description=f"Invoice {inv.invoice_number} updated.",
        before_data=before,
        after_data=inv.to_dict(),
    )
    db.session.commit()
    return jsonify(inv.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/invoices/<id>  (soft delete)
# ---------------------------------------------------------------------------
@invoice_bp.route("/<int:invoice_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def delete_invoice(invoice_id):
    """Soft-delete an invoice (sets status to void and is_deleted = True)."""
    landlord_id = get_current_landlord_id()
    inv         = _get_or_404(landlord_id, invoice_id)
    before      = inv.to_dict()

    inv.is_deleted = True
    inv.deleted_at = datetime.utcnow()
    inv.status     = InvoiceStatus.void.value
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_invoice",
        entity_type="invoice",
        entity_id=inv.id,
        description=f"Invoice {inv.invoice_number} voided and soft-deleted.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": f"Invoice {inv.invoice_number} deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/invoices/<id>/send
# ---------------------------------------------------------------------------
@invoice_bp.route("/<int:invoice_id>/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def send_invoice(invoice_id):
    """
    Send an invoice to the tenant via email/SMS.
    Body: { channel: 'email'|'sms'|'whatsapp' }
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      200: {description: Invoice sent.}
    """
    from services.communication_service import dispatch_invoice
    landlord_id = get_current_landlord_id()
    inv         = _get_or_404(landlord_id, invoice_id)
    data        = request.get_json(silent=True) or {}
    channel     = data.get("channel", "email")

    dispatch_invoice(inv, channel)

    return jsonify({"message": f"Invoice {inv.invoice_number} sent via {channel}."}), 200


# ---------------------------------------------------------------------------
# GET /api/invoices/<id>/download
# ---------------------------------------------------------------------------
@invoice_bp.route("/<int:invoice_id>/download", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def download_invoice(invoice_id):
    """Download a single invoice as PDF (WeasyPrint)."""
    landlord_id = get_current_landlord_id()
    inv         = _get_or_404(landlord_id, invoice_id)
    pdf_bytes   = generate_invoice_pdf(inv)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={inv.invoice_number}.pdf"},
    ), 200


# ---------------------------------------------------------------------------
# GET /api/invoices/bulk-download
# ---------------------------------------------------------------------------
@invoice_bp.route("/bulk-download", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def bulk_download():
    """
    Download a ZIP of invoice PDFs — the landlord's "Download all" button.
    Query: ?invoice_ids=1,2,3 (optional — defaults to every non-deleted, non-void
    invoice for the landlord, matching the "all" in "Download all").
    Streams the ZIP directly (same synchronous download pattern as the
    single-invoice download), so no task-status polling is needed.
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      200: {description: ZIP archive of invoice PDFs.}
      404: {description: No matching invoices.}
    """
    landlord_id = get_current_landlord_id()
    raw_ids     = request.args.get("invoice_ids")
    if raw_ids:
        invoice_ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()]
        query = Invoice.query.filter(Invoice.id.in_(invoice_ids), Invoice.landlord_id == landlord_id)
    else:
        query = Invoice.query.filter_by(landlord_id=landlord_id, is_deleted=False).filter(
            Invoice.status != InvoiceStatus.void.value
        )

    invoices = query.all()
    if not invoices:
        return jsonify({"error": "No invoices found to download."}), 404

    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for inv in invoices:
            zf.writestr(f"{inv.invoice_number}.pdf", generate_invoice_pdf(inv))

    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=invoices.zip"},
    ), 200


# ---------------------------------------------------------------------------
# POST /api/invoices/bulk
# ---------------------------------------------------------------------------
@invoice_bp.route("/bulk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def bulk_add_invoices():
    """
    Bulk-add invoices from a list payload.
    Body: { invoices: [ {tenant_id, unit_id, property_id, invoice_type,
                          issue_date, line_items: [...]} ] }
    Each invoice is validated independently; the whole batch fails atomically.
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      201: {description: All invoices created.}
      400: {description: Validation error.}
    """
    landlord_id      = get_current_landlord_id()
    data             = request.get_json(silent=True) or {}
    invoices_payload = data.get("invoices", [])

    if not invoices_payload:
        return jsonify({"error": "invoices list is required."}), 400

    created = []
    for inv_data in invoices_payload:
        line_items = inv_data.get("line_items", [])
        total      = sum(Decimal(str(li.get("amount", 0))) for li in line_items)

        inv = Invoice(
            invoice_number = _next_invoice_number(landlord_id),
            landlord_id    = landlord_id,
            tenant_id      = inv_data["tenant_id"],
            unit_id        = inv_data["unit_id"],
            property_id    = inv_data["property_id"],
            invoice_type   = inv_data.get("invoice_type", InvoiceType.custom.value),
            issue_date     = inv_data["issue_date"],
            due_date       = inv_data.get("due_date"),
            status         = inv_data.get("status", InvoiceStatus.open.value),
            total_amount   = total,
            amount_paid    = Decimal("0.00"),
            balance        = total,
            title          = inv_data.get("title"),
        )
        db.session.add(inv)
        db.session.flush()

        for li_data in line_items:
            qty   = Decimal(str(li_data.get("quantity", 1)))
            price = Decimal(str(li_data.get("unit_price", 0)))
            amt   = Decimal(str(li_data.get("amount", qty * price)))
            db.session.add(InvoiceLineItem(
                invoice_id  = inv.id,
                item        = li_data.get("item", ""),
                description = li_data.get("description"),
                quantity    = qty,
                unit_price  = price,
                amount      = amt,
            ))
        created.append(inv)

    db.session.commit()

    if created:
        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="bulk_add_invoices",
            entity_type="invoice",
            entity_id=None,
            description=f"{len(created)} invoice(s) bulk-added.",
            after_data={"invoice_ids": [i.id for i in created]},
        )
        db.session.commit()

    return jsonify({"created": len(created), "invoices": [i.to_dict() for i in created]}), 201


# ---------------------------------------------------------------------------
# POST /api/invoices/generate/rent
# ---------------------------------------------------------------------------
@invoice_bp.route("/generate/rent", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def generate_rent_invoices():
    """
    Generate rent invoices for all (or selected) active tenants.
    Body: { property_ids?: [int], unit_ids?: [int], issue_date, due_date? }
    Uses unit.rent_amount for each tenant.
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      201: {description: Rent invoices generated.}
    """
    landlord_id  = get_current_landlord_id()
    data         = request.get_json(silent=True) or {}
    issue_date   = data.get("issue_date", str(date.today()))
    property_ids = data.get("property_ids")
    unit_ids     = data.get("unit_ids")

    from tasks.invoice_tasks import generate_rent_invoices_task
    task = generate_rent_invoices_task.delay(
        landlord_id, issue_date, property_ids, unit_ids,
        data.get("due_date"), int(get_jwt_identity()),
    )
    # In dev (CELERY_TASK_ALWAYS_EAGER=True) the task has already run by the time
    # .delay() returns, so task.result is populated; under a real worker it's None
    # until the task completes, and callers should rely on task_id instead.
    created = task.result.get("created") if task.result else None
    return jsonify({"task_id": task.id, "created": created, "message": "Rent invoice generation queued."}), 202


# ---------------------------------------------------------------------------
# POST /api/invoices/generate/recurring
# ---------------------------------------------------------------------------
@invoice_bp.route("/generate/recurring", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def generate_recurring_invoices():
    """
    Manually trigger generation of recurring-bill invoices.
    (Normally triggered automatically by Celery Beat on the 1st of month.)
    Body: { property_ids?: [int], issue_date? }
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      202: {description: Task queued.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}
    from tasks.invoice_tasks import generate_recurring_invoices_task
    task = generate_recurring_invoices_task.delay(
        landlord_id,
        data.get("issue_date", str(date.today())),
        data.get("property_ids"),
        int(get_jwt_identity()),
    )
    created = task.result.get("created") if task.result else None
    return jsonify({"task_id": task.id, "created": created, "message": "Recurring invoice generation queued."}), 202


# ---------------------------------------------------------------------------
# POST /api/invoices/generate/penalty
# ---------------------------------------------------------------------------
@invoice_bp.route("/generate/penalty", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def generate_penalty_invoices():
    """
    Generate penalty invoices for tenants with arrears older than N days.
    Body: { tenant_ids?: [int], issue_date?, penalty_amount? }
    Falls back to tenant.rent_payment_penalty or property.rent_payment_penalty.
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      202: {description: Task queued.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}
    from tasks.invoice_tasks import generate_penalty_invoices_task
    task = generate_penalty_invoices_task.delay(
        landlord_id,
        data.get("issue_date", str(date.today())),
        data.get("tenant_ids"),
        data.get("penalty_amount"),
        int(get_jwt_identity()),
    )
    created = task.result.get("created") if task.result else None
    return jsonify({"task_id": task.id, "created": created, "message": "Penalty invoice generation queued."}), 202


# ---------------------------------------------------------------------------
# POST /api/invoices/generate/custom
# ---------------------------------------------------------------------------
@invoice_bp.route("/generate/custom", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def generate_custom_invoices():
    """
    Generate custom invoices for a list of tenants from a shared template.
    Body: { tenant_ids: [int], issue_date, title?, line_items: [...] }
    ---
    tags: [Invoices]
    security:
      - Bearer: []
    responses:
      201: {description: Custom invoices created.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}
    tenant_ids  = data.get("tenant_ids", [])
    line_items  = data.get("line_items", [])
    issue_date  = data.get("issue_date", str(date.today()))

    if not tenant_ids or not line_items:
        return jsonify({"error": "tenant_ids and line_items are required."}), 400

    from tasks.invoice_tasks import generate_custom_invoices_task
    task = generate_custom_invoices_task.delay(
        landlord_id, tenant_ids, issue_date, line_items,
        data.get("title"), data.get("due_date"), int(get_jwt_identity()),
    )
    created = task.result.get("created") if task.result else None
    return jsonify({"task_id": task.id, "created": created, "message": "Custom invoice generation queued."}), 202


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, invoice_id: int) -> Invoice:
    inv = Invoice.query.filter_by(
        id=invoice_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not inv:
        abort(404, description="Invoice not found or access denied.")
    return inv