"""
routes/payment_routes.py — Payment Management
Blueprint: payment_bp  |  Prefix: /api/payments

Status vocabulary (exactly as spec): confirmed / pending / declined
Sources: mpesa / co_pilot / bank_statement / manual

Financial rules:
  - Allocation sum ≤ payment amount (enforced via PaymentAllocation table)
  - Unallocated remainder updates tenant.balance as a credit (advance)
  - Every payment write goes through strict server-side validation
"""

from datetime import datetime, date
from decimal import Decimal

from flask import Blueprint, request, jsonify, abort, Response
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Payment, PaymentAllocation, Invoice, Tenant, Landlord,
    BankStatementUpload, BankStatementTransaction,
    PaymentStatus, PaymentSource, InvoiceStatus,
    BankStatementStatus,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service   import record_audit
from services.pdf_service     import generate_receipt_pdf
from services.email_service   import send_receipt_email
from services.storage_service import upload_to_s3
from tasks.payment_tasks      import parse_bank_statement_task

payment_bp = Blueprint("payments", __name__, url_prefix="/api/payments")


def _ref_number(landlord_id: int) -> str:
    count = Payment.query.filter_by(landlord_id=landlord_id).count()
    return f"PAY-{landlord_id}-{count + 1:06d}"


# ---------------------------------------------------------------------------
# GET /api/payments/
# ---------------------------------------------------------------------------
@payment_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def list_payments():
    """
    List payments with total summary and filters.
    Filters: ?start_date=, ?end_date=, ?min_amount=, ?max_amount=,
             ?status=, ?source=, ?property_id=, ?unit_id=, ?tenant_id=,
             ?page=, ?per_page=
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated payment list + total summary.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = Payment.query.filter_by(landlord_id=landlord_id, is_deleted=False)

    # Filters
    if v := request.args.get("start_date"):
        query = query.filter(Payment.payment_date >= v)
    if v := request.args.get("end_date"):
        query = query.filter(Payment.payment_date <= v)
    if v := request.args.get("min_amount", type=float):
        query = query.filter(Payment.amount >= v)
    if v := request.args.get("max_amount", type=float):
        query = query.filter(Payment.amount <= v)
    if v := request.args.get("status"):
        query = query.filter(Payment.status == v)
    if v := request.args.get("source"):
        query = query.filter(Payment.source == v)
    if v := request.args.get("property_id", type=int):
        query = query.filter(Payment.property_id == v)
    if v := request.args.get("unit_id", type=int):
        query = query.filter(Payment.unit_id == v)
    if v := request.args.get("tenant_id", type=int):
        query = query.filter(Payment.tenant_id == v)

    total_amount = db.session.query(
        db.func.coalesce(db.func.sum(Payment.amount), 0)
    ).filter(
        Payment.landlord_id == landlord_id,
        Payment.is_deleted.is_(False),
        Payment.status == PaymentStatus.confirmed.value,
    ).scalar()

    paginated = query.order_by(Payment.payment_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for p in paginated.items:
        d = p.to_dict()
        t = p.tenant
        d["tenant_name"]   = f"{t.first_name} {t.last_name}" if t else None
        d["unit_name"]     = p.unit.name     if p.unit     else None
        d["property_name"] = p.property.name if p.property else None
        items.append(d)

    return jsonify({
        "summary":      {"total_confirmed": round(float(total_amount), 2)},
        "payments":     items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/payments/
# ---------------------------------------------------------------------------
@payment_bp.route("/", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def create_payment():
    """
    Record a manual payment and optionally allocate it to invoices.
    Body:
      { tenant_id, amount, payment_date, payment_method?, notes?,
        source: 'manual'|'mpesa'|'co_pilot'|'bank_statement',
        mpesa_reference?, till_number?,
        allocations: [{ invoice_id, amount_allocated }] }

    Allocation rules:
      - sum(allocations) <= amount
      - Remainder credited to tenant.balance (advance)
      - Each allocated invoice status is recalculated after allocation
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      201: {description: Payment recorded.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    tenant_id      = data.get("tenant_id")
    amount         = Decimal(str(data.get("amount", 0)))
    payment_date   = data.get("payment_date", str(date.today()))
    source         = data.get("source", PaymentSource.manual.value)
    allocations    = data.get("allocations", [])

    if not tenant_id or amount <= 0:
        return jsonify({"error": "tenant_id and a positive amount are required."}), 400

    tenant = Tenant.query.filter_by(
        id=tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not tenant:
        return jsonify({"error": "Tenant not found."}), 404

    # Validate allocation total
    alloc_total = sum(Decimal(str(a.get("amount_allocated", 0))) for a in allocations)
    if alloc_total > amount:
        return jsonify({"error": "Allocation total exceeds payment amount."}), 400

    payment = Payment(
        payment_ref    = _ref_number(landlord_id),
        landlord_id    = landlord_id,
        tenant_id      = tenant_id,
        unit_id        = tenant.unit_id,
        property_id    = tenant.unit.property_id if tenant.unit else None,
        amount         = amount,
        payment_date   = payment_date,
        status         = data.get("status", PaymentStatus.confirmed.value),
        source         = source,
        payment_method = data.get("payment_method"),
        mpesa_reference = data.get("mpesa_reference"),
        till_number    = data.get("till_number"),
        notes          = data.get("notes"),
    )
    db.session.add(payment)
    db.session.flush()

    # Apply allocations
    for alloc in allocations:
        inv_id  = alloc.get("invoice_id")
        alloc_amt = Decimal(str(alloc.get("amount_allocated", 0)))
        if not inv_id or alloc_amt <= 0:
            continue
        inv = Invoice.query.filter_by(id=inv_id, landlord_id=landlord_id, is_deleted=False).first()
        if not inv:
            continue

        db.session.add(PaymentAllocation(
            payment_id       = payment.id,
            invoice_id       = inv.id,
            amount_allocated = alloc_amt,
        ))

        # Update invoice amounts paid + status
        inv.amount_paid = (inv.amount_paid or Decimal("0")) + alloc_amt
        inv.balance     = inv.total_amount - inv.amount_paid
        if inv.balance <= 0:
            inv.status = InvoiceStatus.paid.value
        elif inv.amount_paid > 0:
            inv.status = InvoiceStatus.partial.value

    # Credit unallocated amount to tenant balance (advance)
    unallocated = amount - alloc_total
    tenant.balance = (tenant.balance or Decimal("0")) + unallocated - (amount - alloc_total)
    # Recalculate: tenant balance is advance credit (positive) or arrears (negative)
    # Simple model: balance decreases by amount, then increases by unallocated credit
    tenant.balance = (tenant.balance or Decimal("0")) + unallocated

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_payment",
        entity_type="payment",
        entity_id=payment.id,
        description=f"Payment {payment.payment_ref} of KES {amount} recorded for tenant {tenant_id}.",
        after_data=payment.to_dict(),
    )
    db.session.commit()

    return jsonify(payment.to_dict()), 201


# ---------------------------------------------------------------------------
# GET /api/payments/<id>
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def get_payment(payment_id):
    """Return full payment detail including allocations."""
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)
    d           = pay.to_dict()
    d["allocations"] = [a.to_dict() for a in pay.payment_allocations]
    t = pay.tenant
    d["tenant_name"]   = f"{t.first_name} {t.last_name}" if t else None
    d["unit_name"]     = pay.unit.name     if pay.unit     else None
    d["property_name"] = pay.property.name if pay.property else None
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/payments/<id>
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def update_payment(payment_id):
    """Update a payment's status, notes, or reference fields."""
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)
    data        = request.get_json(silent=True) or {}
    before      = pay.to_dict()

    for field in ["status", "notes", "mpesa_reference", "till_number", "payment_method", "payment_date"]:
        if field in data:
            setattr(pay, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_payment",
        entity_type="payment",
        entity_id=pay.id,
        description=f"Payment {pay.payment_ref} updated.",
        before_data=before,
        after_data=pay.to_dict(),
    )
    db.session.commit()
    return jsonify(pay.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/payments/<id>  (soft delete)
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def delete_payment(payment_id):
    """Soft-delete a payment. Reverses invoice allocations and tenant balance."""
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)
    before      = pay.to_dict()

    # Reverse invoice allocations
    for alloc in pay.payment_allocations:
        inv = alloc.invoice
        if inv and not inv.is_deleted:
            inv.amount_paid = max(Decimal("0"), (inv.amount_paid or Decimal("0")) - alloc.amount_allocated)
            inv.balance     = inv.total_amount - inv.amount_paid
            if inv.amount_paid <= 0:
                inv.status = InvoiceStatus.open.value
            else:
                inv.status = InvoiceStatus.partial.value

    # Reverse tenant balance credit
    if pay.tenant:
        pay.tenant.balance = (pay.tenant.balance or Decimal("0")) - pay.amount

    pay.is_deleted = True
    pay.deleted_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_payment",
        entity_type="payment",
        entity_id=pay.id,
        description=f"Payment {pay.payment_ref} soft-deleted. Allocations reversed.",
        before_data=before,
    )
    db.session.commit()
    return jsonify({"message": f"Payment {pay.payment_ref} deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/payments/<id>/receipt/send
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/receipt/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def send_receipt(payment_id):
    """Email the payment receipt to the tenant."""
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)

    if not pay.tenant or not pay.tenant.email:
        return jsonify({"error": "Tenant has no email address on file."}), 400

    pdf_bytes = generate_receipt_pdf(pay)
    send_receipt_email.delay(pay.tenant.email, pay.tenant.first_name, pdf_bytes, pay.payment_ref)

    return jsonify({"message": "Receipt emailed to tenant."}), 200


# ---------------------------------------------------------------------------
# GET /api/payments/<id>/receipt/download
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/receipt/download", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def download_receipt(payment_id):
    """Stream the payment receipt PDF."""
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)
    pdf_bytes   = generate_receipt_pdf(pay)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=receipt_{pay.payment_ref}.pdf"},
    ), 200


# ---------------------------------------------------------------------------
# POST /api/payments/<id>/reassign
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/reassign", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def reassign_payment(payment_id):
    """
    Re-assign a payment to a different tenant ('change tenant' action).
    Clears existing allocations and re-credits to the new tenant.
    Body: { new_tenant_id }
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Payment reassigned.}
      404: {description: Payment or tenant not found.}
    """
    landlord_id    = get_current_landlord_id()
    pay            = _get_or_404(landlord_id, payment_id)
    data           = request.get_json(silent=True) or {}
    new_tenant_id  = data.get("new_tenant_id")
    before         = pay.to_dict()

    if not new_tenant_id:
        return jsonify({"error": "new_tenant_id is required."}), 400

    new_tenant = Tenant.query.filter_by(
        id=new_tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not new_tenant:
        return jsonify({"error": "New tenant not found."}), 404

    # Reverse old tenant balance
    if pay.tenant:
        pay.tenant.balance = (pay.tenant.balance or Decimal("0")) - pay.amount
    # Reverse invoice allocations
    PaymentAllocation.query.filter_by(payment_id=pay.id).delete()

    pay.tenant_id  = new_tenant_id
    pay.unit_id    = new_tenant.unit_id
    pay.property_id = new_tenant.unit.property_id if new_tenant.unit else None
    new_tenant.balance = (new_tenant.balance or Decimal("0")) + pay.amount

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="reassign_payment",
        entity_type="payment",
        entity_id=pay.id,
        description=f"Payment {pay.payment_ref} reassigned to tenant {new_tenant_id}.",
        before_data=before,
        after_data=pay.to_dict(),
    )
    db.session.commit()
    return jsonify(pay.to_dict()), 200


# ---------------------------------------------------------------------------
# GET /api/payments/report
# ---------------------------------------------------------------------------
@payment_bp.route("/report", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def payments_report():
    """
    Download a payments report as PDF or Excel.
    ?format=pdf|excel, ?start_date=, ?end_date=, ?property_id=
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Report file.}
    """
    from services.export_service import generate_payments_report
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    start_date  = request.args.get("start_date")
    end_date    = request.args.get("end_date")
    property_id = request.args.get("property_id", type=int)

    file_bytes, mime, filename = generate_payments_report(
        landlord_id, fmt, start_date, end_date, property_id
    )
    return Response(
        file_bytes,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    ), 200


# ---------------------------------------------------------------------------
# POST /api/payments/bank-statement/upload
# ---------------------------------------------------------------------------
@payment_bp.route("/bank-statement/upload", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def upload_bank_statement():
    """
    Upload a bank statement file for async parsing.
    Accepts multipart/form-data with a 'file' field (PDF or CSV).
    Queues a Celery task to extract transactions.
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      202: {description: Statement uploaded and parsing queued.}
      400: {description: No file provided.}
    """
    landlord_id = get_current_landlord_id()
    file        = request.files.get("file")
    if not file:
        return jsonify({"error": "A statement file is required."}), 400

    file_url = upload_to_s3(file, folder=f"bank-statements/{landlord_id}")

    upload = BankStatementUpload(
        landlord_id = landlord_id,
        file_url    = file_url,
        status      = BankStatementStatus.uploaded.value,
    )
    db.session.add(upload)
    db.session.commit()

    parse_bank_statement_task.delay(upload.id)

    return jsonify({
        "message":    "Statement uploaded. Parsing in progress.",
        "upload_id":  upload.id,
        "status":     upload.status,
    }), 202


# ---------------------------------------------------------------------------
# GET /api/payments/bank-statement/<id>/transactions
# ---------------------------------------------------------------------------
@payment_bp.route("/bank-statement/<int:upload_id>/transactions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def get_statement_transactions(upload_id):
    """
    Return parsed transactions from an uploaded bank statement for review.
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Parsed transaction list with import status.}
      404: {description: Upload not found.}
    """
    landlord_id = get_current_landlord_id()
    upload      = BankStatementUpload.query.filter_by(
        id=upload_id, landlord_id=landlord_id
    ).first()
    if not upload:
        return jsonify({"error": "Bank statement upload not found."}), 404

    transactions = [t.to_dict() for t in upload.transactions]
    return jsonify({
        "upload":       upload.to_dict(),
        "transactions": transactions,
        "total":        len(transactions),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/payments/bank-statement/<id>/import
# ---------------------------------------------------------------------------
@payment_bp.route("/bank-statement/<int:upload_id>/import", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def import_statement_transactions(upload_id):
    """
    Import selected parsed transactions as confirmed payments.
    Body: { transaction_ids: [int], tenant_mappings?: { txn_id: tenant_id } }
    Each imported transaction creates a Payment row (source=bank_statement).
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      201: {description: Payments created from selected transactions.}
      404: {description: Upload not found.}
    """
    landlord_id      = get_current_landlord_id()
    upload           = BankStatementUpload.query.filter_by(
        id=upload_id, landlord_id=landlord_id
    ).first()
    if not upload:
        return jsonify({"error": "Bank statement upload not found."}), 404

    data             = request.get_json(silent=True) or {}
    transaction_ids  = data.get("transaction_ids", [])
    tenant_mappings  = data.get("tenant_mappings", {})

    if not transaction_ids:
        return jsonify({"error": "transaction_ids list is required."}), 400

    created = []
    for txn_id in transaction_ids:
        txn = BankStatementTransaction.query.filter_by(
            id=int(txn_id), bank_statement_id=upload.id
        ).first()
        if not txn or txn.is_imported:
            continue

        tenant_id = tenant_mappings.get(str(txn_id))

        payment = Payment(
            payment_ref       = _ref_number(landlord_id),
            landlord_id       = landlord_id,
            tenant_id         = int(tenant_id) if tenant_id else None,
            amount            = txn.amount or Decimal("0"),
            payment_date      = txn.txn_date or date.today(),
            status            = PaymentStatus.confirmed.value,
            source            = PaymentSource.bank_statement.value,
            bank_statement_id = upload.id,
            notes             = txn.description,
        )
        db.session.add(payment)
        db.session.flush()

        txn.is_imported       = True
        txn.matched_payment_id = payment.id
        created.append(payment)

    db.session.commit()

    return jsonify({
        "message":  f"{len(created)} payment(s) imported.",
        "payments": [p.to_dict() for p in created],
    }), 201


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_404(landlord_id: int, payment_id: int) -> Payment:
    pay = Payment.query.filter_by(
        id=payment_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not pay:
        abort(404, description="Payment not found or access denied.")
    return pay