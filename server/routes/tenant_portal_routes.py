"""
routes/tenant_portal_routes.py — Tenant Self-Service Portal
Blueprint: tenant_portal_bp  |  Prefix: /api/portal

OTP-authenticated.  The tenant JWT issued by otp_routes.py carries:
  { role: "tenant", tenant_id: int, landlord_id: int }

All endpoints here ONLY expose data belonging to the authenticated tenant.
Profile edits write directly to the shared `tenants` row — the landlord
sees the changes immediately in their portal.

Maintenance requests created here become visible in maintenance_routes.py
(landlord side) with the same tenant_id for tracking.
"""

from datetime import datetime, date
from decimal import Decimal

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    Tenant, Invoice, Payment, PaymentAllocation, PaymentSource,
    PaymentStatus, InvoiceStatus, MaintenanceRequest,
    MaintenanceStatus, MaintenanceCategory,
)
from services.pdf_service  import generate_tenant_statement_pdf, generate_receipt_pdf
from services.email_service import send_receipt_email

tenant_portal_bp = Blueprint("tenant_portal", __name__, url_prefix="/api/portal")


def _get_portal_tenant() -> tuple[Tenant | None, int | None]:
    """
    Extract tenant_id from JWT claims and load the Tenant row.
    Returns (tenant, landlord_id) or (None, None) on failure.
    """
    claims     = get_jwt()
    tenant_id  = claims.get("tenant_id")
    landlord_id = claims.get("landlord_id")
    if not tenant_id:
        return None, None
    tenant = Tenant.query.filter_by(id=tenant_id, is_deleted=False).first()
    return tenant, landlord_id


def _require_tenant():
    """
    Convenience wrapper: returns (tenant, landlord_id) or aborts 403.
    """
    from flask import abort
    tenant, landlord_id = _get_portal_tenant()
    if not tenant:
        abort(403, description="Tenant session not found. Please log in again.")
    return tenant, landlord_id


def _payment_ref(landlord_id: int) -> str:
    count = Payment.query.filter_by(landlord_id=landlord_id).count()
    return f"PAY-{landlord_id}-{count + 1:06d}"


# ---------------------------------------------------------------------------
# GET /api/portal/dashboard
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def portal_dashboard():
    """
    Return the tenant's balance breakdown for the dashboard.
    Shows:
      - rent_due        : sum of open/partial rent invoices
      - utilities_due   : sum of open/partial utility invoices
      - previous_balance: carried-over balance from last month
      - current_balance : tenant.balance (overall ledger position)
      - open_invoices   : list of unpaid invoices for quick-pay
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Balance breakdown.}
    """
    tenant, landlord_id = _require_tenant()

    open_invoices = [
        inv for inv in tenant.invoices
        if not inv.is_deleted
        and inv.status in (InvoiceStatus.open.value, InvoiceStatus.partial.value)
    ]

    rent_types    = {"rent"}
    utility_types = {"water", "electricity", "garbage", "security", "utility"}

    rent_due     = sum(float(inv.balance) for inv in open_invoices
                       if (inv.invoice_type or "").lower() in rent_types)
    utility_due  = sum(float(inv.balance) for inv in open_invoices
                       if (inv.invoice_type or "").lower() in utility_types)

    # All other open amounts (custom, penalty, recurring)
    other_due = sum(float(inv.balance) for inv in open_invoices
                    if (inv.invoice_type or "").lower() not in rent_types | utility_types)

    unit     = tenant.unit
    property = unit.property if unit else None

    # previous_balance: the balance as it stood at the start of this calendar
    # month — reconstructed by reversing this month's invoice/payment activity
    # out of the current running balance (same ledger convention: invoices
    # subtract, payments add — see payment_routes.py's create_payment).
    month_start = date.today().replace(day=1)
    month_invoices_total = sum(
        float(inv.total_amount) for inv in tenant.invoices
        if not inv.is_deleted and inv.issue_date and inv.issue_date >= month_start
    )
    month_payments_total = sum(
        float(pay.amount) for pay in tenant.payments
        if not pay.is_deleted and pay.payment_date and pay.payment_date >= month_start
    )
    previous_balance = float(tenant.balance) + month_invoices_total - month_payments_total

    return jsonify({
        "tenant_id":       tenant.id,
        "tenant_name":     f"{tenant.first_name} {tenant.last_name}",
        "current_balance": float(tenant.balance),
        "previous_balance": round(previous_balance, 2),
        "rent_due":        round(rent_due, 2),
        "utility_due":     round(utility_due, 2),
        "other_due":       round(other_due, 2),
        "unit_name":       unit.name     if unit     else None,
        "property_name":   property.name if property else None,
        "lease_expiry":    str(tenant.lease_expiry_date) if tenant.lease_expiry_date else None,
        "open_invoices": [
            {
                "id":           inv.id,
                "invoice_number": inv.invoice_number,
                "type":         inv.invoice_type,
                "due_date":     str(inv.due_date) if inv.due_date else None,
                "balance":      float(inv.balance),
                "status":       inv.status,
            }
            for inv in sorted(open_invoices, key=lambda x: x.issue_date)
        ],
    }), 200


# ---------------------------------------------------------------------------
# POST /api/portal/pay
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/pay", methods=["POST"])
@jwt_required()
def portal_pay():
    """
    Tenant makes a payment in-portal.
    Body:
      { amount: number,
        payment_method: str,         -- e.g. 'mpesa', 'card'
        mpesa_reference?: str,
        allocations?: [{ invoice_id, amount_allocated }]
      }

    Allocation rules (same as payment_routes.py):
      - sum(allocations) <= amount
      - Remainder credited to tenant.balance (advance)
      - Each allocated invoice status is recalculated

    On success, a receipt PDF is auto-emailed if the tenant has an email.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      201: {description: Payment recorded. Receipt emailed if email on file.}
      400: {description: Validation error.}
    """
    tenant, landlord_id = _require_tenant()
    data                = request.get_json(silent=True) or {}

    amount         = Decimal(str(data.get("amount", 0)))
    payment_method = data.get("payment_method", "mpesa")
    mpesa_ref      = data.get("mpesa_reference")
    allocations    = data.get("allocations", [])

    if amount <= 0:
        return jsonify({"error": "A positive payment amount is required."}), 400

    # Validate allocation total
    alloc_total = sum(Decimal(str(a.get("amount_allocated", 0))) for a in allocations)
    if alloc_total > amount:
        return jsonify({"error": "Allocation total exceeds payment amount."}), 400

    unit     = tenant.unit
    property = unit.property if unit else None

    payment = Payment(
        payment_ref     = _payment_ref(landlord_id),
        landlord_id     = landlord_id,
        tenant_id       = tenant.id,
        unit_id         = tenant.unit_id,
        property_id     = property.id if property else None,
        amount          = amount,
        payment_date    = date.today(),
        status          = PaymentStatus.confirmed.value,
        source          = PaymentSource.mpesa.value
                          if payment_method == "mpesa" else PaymentSource.manual.value,
        payment_method  = payment_method,
        mpesa_reference = mpesa_ref,
        notes           = "Tenant self-service portal payment",
    )
    db.session.add(payment)
    db.session.flush()

    # Apply allocations
    for alloc in allocations:
        inv_id    = alloc.get("invoice_id")
        alloc_amt = Decimal(str(alloc.get("amount_allocated", 0)))
        if not inv_id or alloc_amt <= 0:
            continue
        inv = Invoice.query.filter_by(
            id=inv_id, tenant_id=tenant.id, is_deleted=False
        ).first()
        if not inv:
            continue
        db.session.add(PaymentAllocation(
            payment_id=payment.id, invoice_id=inv.id, amount_allocated=alloc_amt
        ))
        inv.amount_paid = (inv.amount_paid or Decimal("0")) + alloc_amt
        inv.balance     = inv.total_amount - inv.amount_paid
        inv.status      = (
            InvoiceStatus.paid.value    if inv.balance <= 0
            else InvoiceStatus.partial.value if inv.amount_paid > 0
            else InvoiceStatus.open.value
        )

    # Ledger convention (matches landlord_dashboard_routes/report_routes/export_service):
    # negative balance = arrears (owed), positive = advance (credit). The FULL payment
    # reduces what's owed regardless of allocation split — see payment_routes.py's
    # create_payment for the identical landlord-side logic.
    tenant.balance = (tenant.balance or Decimal("0")) + amount

    from models import Landlord
    from services.notification_service import notify
    landlord_row = db.session.get(Landlord, landlord_id)
    if landlord_row and landlord_row.user_id:
        notify(
            recipient_user_id=landlord_row.user_id,
            category="payment_received",
            template_key="payment_received",
            template_kwargs={
                "amount": f"{amount:,.2f}",
                "tenant_name": f"{tenant.first_name} {tenant.last_name}",
                "unit_name": unit.name if unit else "—",
            },
            landlord_id=landlord_id,
            link="/landlord/payments",
            entity_type="payment",
            entity_id=payment.id,
        )

    db.session.commit()

    from services.audit_service import record_audit
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_payment",
        entity_type="payment",
        entity_id=payment.id,
        description=f"Payment {payment.payment_ref} of KES {amount} recorded via tenant portal by {tenant.first_name} {tenant.last_name}.",
        after_data=payment.to_dict(),
    )
    db.session.commit()

    # Auto-email receipt if tenant has an email address
    if tenant.email:
        try:
            pdf_bytes = generate_receipt_pdf(payment)
            send_receipt_email.delay(
                tenant.email, tenant.first_name, pdf_bytes, payment.payment_ref
            )
        except Exception:
            pass  # Non-blocking — payment is recorded regardless

    return jsonify({
        "message":   "Payment recorded successfully.",
        "payment":   payment.to_dict(),
        "new_balance": float(tenant.balance),
    }), 201


# ---------------------------------------------------------------------------
# GET /api/portal/payments/<id>/receipt
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/payments/<int:payment_id>/receipt", methods=["GET"])
@jwt_required()
def download_receipt(payment_id):
    """
    Download the PDF receipt for a specific payment.
    Also auto-emails a copy to the tenant if email is on file.
    The tenant can only access their own payment receipts.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: PDF receipt stream.}
      404: {description: Payment not found.}
    """
    tenant, _ = _require_tenant()

    payment = Payment.query.filter_by(
        id=payment_id, tenant_id=tenant.id, is_deleted=False
    ).first()
    if not payment:
        return jsonify({"error": "Payment not found."}), 404

    pdf_bytes = generate_receipt_pdf(payment)

    # Auto-email copy
    if tenant.email:
        try:
            send_receipt_email.delay(
                tenant.email, tenant.first_name, pdf_bytes, payment.payment_ref
            )
        except Exception:
            pass

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=receipt_{payment.payment_ref}.pdf"
        },
    ), 200


# ---------------------------------------------------------------------------
# GET /api/portal/statement
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/statement", methods=["GET"])
@jwt_required()
def portal_statement():
    """
    Return the tenant's full transaction history as JSON.
    Includes all invoices and payments, sorted chronologically,
    with a running balance column.

    ?start_date= and ?end_date= narrow the view (optional).
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Statement entries with running balance.}
    """
    tenant, _ = _require_tenant()
    start_date = request.args.get("start_date")
    end_date   = request.args.get("end_date")

    entries = []

    for inv in tenant.invoices:
        if inv.is_deleted:
            continue
        d = str(inv.issue_date)
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        entries.append({
            "date":        d,
            "type":        "invoice",
            "description": inv.title or inv.invoice_type,
            "invoice_no":  inv.invoice_number,
            "amount_due":  float(inv.total_amount),
            "amount_paid": float(inv.amount_paid),
            "status":      inv.status,
        })

    for pay in tenant.payments:
        if pay.is_deleted:
            continue
        d = str(pay.payment_date)
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        entries.append({
            "id":          pay.id,
            "date":        d,
            "type":        "payment",
            "description": f"Payment via {pay.source}",
            "payment_ref": pay.payment_ref,
            "amount":      float(pay.amount),
            "status":      pay.status,
        })

    entries.sort(key=lambda x: x["date"])

    # Running balance
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
        "start_date":     start_date,
        "end_date":       end_date,
        "entries":        entries,
        "total_entries":  len(entries),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/portal/statement/download
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/statement/download", methods=["GET"])
@jwt_required()
def download_statement():
    """
    Download the tenant's full statement as a PDF.
    ?start_date= and ?end_date= narrow the date range (optional).
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Statement PDF.}
    """
    tenant, _ = _require_tenant()
    pdf_bytes = generate_tenant_statement_pdf(tenant)

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
# GET /api/portal/profile
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    """
    Return the authenticated tenant's profile details.
    The tenant sees the same row the landlord sees (no separate profile table).
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant profile.}
    """
    tenant, _ = _require_tenant()
    d = tenant.to_dict()
    unit     = tenant.unit
    property = unit.property if unit else None
    d["unit_name"]     = unit.name     if unit     else None
    d["property_name"] = property.name if property else None
    return jsonify(d), 200


# ---------------------------------------------------------------------------
# PUT /api/portal/profile
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    """
    Tenant updates their own profile.
    Allowed fields: first_name, last_name, phone, secondary_phone, email.
    All changes are written to the shared `tenants` row — the landlord
    sees the updates immediately without any sync step.

    Restricted fields (silently ignored): landlord_id, unit_id, balance,
    national_id, kra_pin, deposit amounts, lease dates.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Profile updated.}
    """
    tenant, landlord_id = _require_tenant()
    data   = request.get_json(silent=True) or {}
    before = tenant.to_dict()

    # Strictly allow only safe self-service fields
    for field in ("first_name", "last_name", "phone", "secondary_phone", "email"):
        if field in data:
            val = data[field]
            # Normalise email to lowercase
            if field == "email" and val:
                val = val.strip().lower()
            setattr(tenant, field, val)

    db.session.commit()

    from services.audit_service import record_audit
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="tenant_portal_update_profile",
        entity_type="tenant",
        entity_id=tenant.id,
        description=f"Tenant '{tenant.first_name} {tenant.last_name}' updated their own profile via portal.",
        before_data=before,
        after_data=tenant.to_dict(),
    )
    db.session.commit()

    return jsonify(tenant.to_dict()), 200


# ---------------------------------------------------------------------------
# GET /api/portal/maintenance
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/maintenance", methods=["GET"])
@jwt_required()
def list_maintenance():
    """
    List the authenticated tenant's own maintenance requests.
    ?status= filter: open / in_progress / closed
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant's maintenance requests.}
    """
    tenant, _ = _require_tenant()

    query = MaintenanceRequest.query.filter_by(tenant_id=tenant.id)

    if v := request.args.get("status"):
        query = query.filter(MaintenanceRequest.status == v)

    requests = query.order_by(MaintenanceRequest.created_at.desc()).all()

    return jsonify({
        "requests": [r.to_dict() for r in requests],
        "total":    len(requests),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/portal/maintenance
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/maintenance", methods=["POST"])
@jwt_required()
def create_maintenance():
    """
    Tenant opens a new maintenance request.

    Allowed categories (§6 spec):
      plumbing / electrical / roofing / tiles / washroom /
      painting / security / other

    Body: { category, summary, description? }
    Image uploads: multipart/form-data with optional 'image' file field.

    The request is immediately visible to the landlord in their
    /api/maintenance endpoint under the same property/unit.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      201: {description: Maintenance request created.}
      400: {description: Validation error.}
    """
    tenant, landlord_id = _require_tenant()

    if request.is_json:
        data      = request.get_json(silent=True) or {}
        image_url = None
    else:
        data      = request.form.to_dict()
        image     = request.files.get("image")
        if image:
            from services.storage_service import upload_to_s3
            image_url = upload_to_s3(image, folder=f"maintenance/{landlord_id}")
        else:
            image_url = None

    summary  = (data.get("summary") or "").strip()
    category = data.get("category")

    if not summary:
        return jsonify({"error": "summary is required."}), 400

    # Validate category against the portal-allowed set
    allowed_categories = {
        MaintenanceCategory.plumbing.value,
        MaintenanceCategory.electrical.value,
        MaintenanceCategory.roofing.value,
        MaintenanceCategory.tiles.value,
        MaintenanceCategory.washroom.value,
        MaintenanceCategory.painting.value,
        MaintenanceCategory.security.value,
        MaintenanceCategory.other.value,
    }
    if category and category not in allowed_categories:
        return jsonify({
            "error": f"category must be one of: {sorted(allowed_categories)}."
        }), 400

    # Resolve property from tenant's current unit
    unit      = tenant.unit
    property  = unit.property if unit else None

    if not unit or not property:
        return jsonify({"error": "Your unit or property information is not set up. Contact your landlord."}), 400

    req = MaintenanceRequest(
        landlord_id = landlord_id,
        property_id = property.id,
        unit_id     = unit.id,
        tenant_id   = tenant.id,
        summary     = summary,
        description = data.get("description"),
        category    = category,
        status      = MaintenanceStatus.open.value,
        image_url   = image_url or data.get("image_url"),
    )
    db.session.add(req)
    db.session.flush()

    from models import Landlord
    from services.notification_service import notify
    landlord_row = db.session.get(Landlord, landlord_id)
    if landlord_row and landlord_row.user_id:
        notify(
            recipient_user_id=landlord_row.user_id,
            category="new_maintenance_request",
            template_key="new_maintenance_request",
            template_kwargs={
                "tenant_name": f"{tenant.first_name} {tenant.last_name}",
                "summary": summary,
                "category": category or "other",
            },
            landlord_id=landlord_id,
            link="/landlord/maintenance",
            entity_type="maintenance",
            entity_id=req.id,
        )

    from services.audit_service import record_audit
    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_maintenance_request",
        entity_type="maintenance",
        entity_id=req.id,
        description=f"Maintenance request created via tenant portal by {tenant.first_name} {tenant.last_name}: '{summary}'.",
        after_data=req.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message": "Maintenance request submitted successfully.",
        "request": req.to_dict(),
    }), 201