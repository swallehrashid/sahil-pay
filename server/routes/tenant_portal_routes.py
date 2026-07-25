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

    from services.balance_breakdown import build_breakdown

    open_invoices = [
        inv for inv in tenant.invoices
        if not inv.is_deleted
        and inv.status in (InvoiceStatus.open.value, InvoiceStatus.partial.value)
    ]

    # Itemised, line-level breakdown — the single source of truth for "where the
    # balance came from" (shared with reminder communications). This replaces the
    # old 3-bucket rent/utility/other split, which silently dropped whole invoice
    # types (e.g. a water DEPOSIT) that fell outside its hard-coded type sets.
    breakdown = build_breakdown(tenant)

    # Legacy summary buckets kept for any older client, now derived from the same
    # itemised source so they always reconcile with `breakdown`.
    rent_due    = sum(it["amount"] for it in breakdown["items"]
                      if "rent" in it["label"].lower() and not it["is_deposit"])
    utility_due = sum(it["amount"] for it in breakdown["items"]
                      if any(u in it["label"].lower()
                             for u in ("water", "electricity", "garbage", "security"))
                      and not it["is_deposit"])
    deposit_due = breakdown["deposits_due"]
    other_due   = round(breakdown["total_due"] - rent_due - utility_due - deposit_due, 2)

    # Deposit HELD = refundable deposit money the tenant has actually PAID
    # (confirmed) — the money the landlord is currently holding, NOT what was
    # merely invoiced/owed. Sums BOTH the onboarding deposit captured on the
    # tenant record and any PAID deposit-subcategory invoice line items; an
    # unpaid deposit line contributes nothing.
    from models import SubCategory, InvoiceStatus as _IS
    deposits_held = float(tenant.deposit_paid or 0)
    for inv in tenant.invoices:
        if inv.is_deleted or inv.status == _IS.void.value:
            continue
        for li in inv.line_items:
            if li.subcategory == SubCategory.deposit.value:
                deposits_held += float(li.amount_paid or 0)
    deposits_held = round(deposits_held - float(tenant.deposit_returned or 0), 2)

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
        if not pay.is_deleted and pay.status == PaymentStatus.confirmed.value
        and pay.payment_date and pay.payment_date >= month_start
    )
    previous_balance = float(tenant.balance) + month_invoices_total - month_payments_total

    return jsonify({
        "tenant_id":       tenant.id,
        "tenant_name":     f"{tenant.first_name} {tenant.last_name}",
        "current_balance": float(tenant.balance),
        "previous_balance": round(previous_balance, 2),
        "total_due":       round(breakdown["total_due"], 2),
        "rent_due":        round(rent_due, 2),
        "utility_due":     round(utility_due, 2),
        "deposit_due":     round(deposit_due, 2),
        "other_due":       round(other_due, 2),
        # Full itemised breakdown — the tenant sees exactly what makes up the total.
        "breakdown_items": breakdown["items"],
        "arrears_due":     round(breakdown["arrears_due"], 2),
        "deposits_due":    round(breakdown["deposits_due"], 2),
        "deposits_held":   deposits_held,   # confirmed/paid deposit money held
        "unit_name":       unit.name     if unit     else None,
        "property_name":   property.name if property else None,
        "lease_expiry":    str(tenant.lease_expiry_date) if tenant.lease_expiry_date else None,
        "open_invoices": [
            {
                "id":             inv["id"],
                "invoice_number": inv["invoice_number"],
                "title":          inv["title"],
                "type":           inv["type"],
                "issue_date":     inv["issue_date"],
                "due_date":       inv["due_date"],
                "balance":        inv["balance"],
                "is_overdue":     inv["is_overdue"],
                "status":         "partial" if any(l["amount"] < inv["balance"] for l in inv["lines"]) else "open",
                "lines":          inv["lines"],
            }
            for inv in breakdown["invoices"]
        ],
    }), 200


# ---------------------------------------------------------------------------
# POST /api/portal/pay
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/payment-details", methods=["GET"])
@jwt_required()
def payment_details():
    """
    Everything the tenant needs to make a payment: the landlord's pay
    directives (paybill/till, account number, expected name, instructions),
    the tenant's outstanding invoices, and their current balance. Read-only.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Payment directives + outstanding charges.}
    """
    from models import Landlord
    tenant, landlord_id = _require_tenant()
    landlord = db.session.get(Landlord, landlord_id)
    unit     = tenant.unit
    property = unit.property if unit else None

    account_number = (
        tenant.account_number
        or (property.mpesa_details if property else None)
        or (landlord.default_account_number if landlord else None)
    )

    outstanding = []
    total_due = Decimal("0")
    for inv in tenant.invoices:
        if inv.is_deleted:
            continue
        bal = (inv.total_amount or Decimal("0")) - (inv.amount_paid or Decimal("0"))
        if bal <= 0:
            continue
        total_due += bal
        outstanding.append({
            "id":            inv.id,
            "invoice_number": inv.invoice_number,
            "invoice_type":  inv.invoice_type,
            "title":         inv.title or inv.invoice_type,
            "issue_date":    str(inv.issue_date),
            "due_date":      str(inv.due_date) if inv.due_date else None,
            "total_amount":  float(inv.total_amount or 0),
            "amount_paid":   float(inv.amount_paid or 0),
            "balance":       float(bal),
        })
    outstanding.sort(key=lambda x: x["issue_date"])

    return jsonify({
        "mpesa_type":           landlord.mpesa_type if landlord else None,
        "mpesa_number":         landlord.mpesa_number if landlord else None,
        "account_number":       account_number,
        "expected_name":        landlord.company_name if landlord else None,
        "payment_instructions": landlord.payment_instructions if landlord else None,
        "currency":             landlord.currency if landlord else "KES",
        "tenant_account":       tenant.account_number,
        "outstanding_invoices": outstanding,
        "total_due":            float(total_due),
        "current_balance":      float(tenant.balance or 0),
    }), 200


@tenant_portal_bp.route("/payments", methods=["GET"])
@jwt_required()
def list_portal_payments():
    """
    Tenant's payment history, split into confirmed (with downloadable receipt),
    pending (submitted, awaiting the landlord's confirmation), and declined.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Payments grouped by status.}
    """
    tenant, _ = _require_tenant()

    def _row(p):
        return {
            "id":              p.id,
            "payment_ref":     p.payment_ref,
            "amount":          float(p.amount or 0),
            "payment_date":    str(p.payment_date) if p.payment_date else None,
            "status":          p.status,
            "payment_method":  p.payment_method,
            "mpesa_reference": p.mpesa_reference,
            "proof_url":       p.proof_url,
            "submitted_at":    p.created_at.isoformat() if p.created_at else None,
        }

    pays = [p for p in tenant.payments if not p.is_deleted]
    return jsonify({
        "confirmed": [_row(p) for p in pays if p.status == PaymentStatus.confirmed.value],
        "pending":   [_row(p) for p in pays if p.status == PaymentStatus.pending.value],
        "declined":  [_row(p) for p in pays if p.status == PaymentStatus.declined.value],
    }), 200


@tenant_portal_bp.route("/payments/submit", methods=["POST"])
@jwt_required()
def submit_payment():
    """
    Tenant SUBMITS a payment for the landlord to confirm — they cannot record a
    confirmed payment themselves. Creates a `pending` Payment with the tenant's
    proof-of-payment attachment; the ledger is NOT touched until a landlord (or
    permitted team member) confirms it. The landlord and every team member with
    the `payments` permission are notified.

    Accepts multipart/form-data (proof file) or JSON.
    Fields: amount (required), mpesa_reference?, payment_method?, note?, proof (file).
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      201: {description: Payment submitted for confirmation.}
      400: {description: Validation error.}
    """
    from models import Landlord, TeamMember, TeamMemberPermission
    from services.notification_service import notify

    tenant, landlord_id = _require_tenant()

    if request.is_json:
        data      = request.get_json(silent=True) or {}
        proof_url = data.get("proof_url")
    else:
        data  = request.form.to_dict()
        proof = request.files.get("proof")
        if proof:
            from services.storage_service import upload_to_s3
            proof_url = upload_to_s3(proof, folder=f"payment-proofs/{landlord_id}")
        else:
            proof_url = None

    amount         = Decimal(str(data.get("amount", 0)))
    payment_method = data.get("payment_method", "mpesa")
    mpesa_ref      = data.get("mpesa_reference")
    note           = (data.get("note") or "").strip()

    if amount <= 0:
        return jsonify({"error": "A positive payment amount is required."}), 400

    unit     = tenant.unit
    property = unit.property if unit else None
    tenant_name = f"{tenant.first_name} {tenant.last_name}".strip()

    notes = "Submitted via tenant portal — awaiting confirmation."
    if note:
        notes += f" Tenant note: {note}"

    payment = Payment(
        payment_ref     = _payment_ref(landlord_id),
        landlord_id     = landlord_id,
        tenant_id       = tenant.id,
        unit_id         = tenant.unit_id,
        property_id     = property.id if property else None,
        amount          = amount,
        payment_date    = date.today(),
        status          = PaymentStatus.pending.value,
        source          = PaymentSource.mpesa.value
                          if payment_method == "mpesa" else PaymentSource.manual.value,
        payment_method  = payment_method,
        mpesa_reference = mpesa_ref,
        proof_url       = proof_url,
        notes           = notes,
    )
    db.session.add(payment)
    db.session.flush()

    # Notify the landlord + every active team member with the payments permission.
    title   = f"Payment awaiting confirmation — {tenant_name}"
    body    = f"{tenant_name} submitted KES {amount:,.2f} for confirmation."
    recipients: list[int] = []
    landlord_row = db.session.get(Landlord, landlord_id)
    if landlord_row and landlord_row.user_id:
        recipients.append(landlord_row.user_id)
    team_rows = (
        db.session.query(TeamMember)
        .join(TeamMemberPermission, TeamMemberPermission.team_member_id == TeamMember.id)
        .filter(
            TeamMember.landlord_id == landlord_id,
            TeamMember.is_active.is_(True),
            TeamMemberPermission.module == "payments",
            db.or_(TeamMemberPermission.can_view.is_(True), TeamMemberPermission.can_edit.is_(True)),
        )
        .all()
    )
    recipients.extend(tm.user_id for tm in team_rows if tm.user_id)
    for uid in set(recipients):
        notify(
            recipient_user_id=uid,
            category="payment_received",
            title=title,
            body=body,
            landlord_id=landlord_id,
            link=f"/landlord/payments?status=pending&highlight={payment.id}",
            entity_type="payment",
            entity_id=payment.id,
        )

    db.session.commit()

    from services.audit_service import record_audit
    record_audit(
        # #18 — the tenant JWT identity is str(tenant.user_id or tenant.id); for
        # OTP-only tenants with no linked User it falls back to tenant.id, which the
        # audit resolver would misread as a User id and log the wrong person. Pass
        # the acting tenant's real identity explicitly so the log is always correct.
        actor_user_id=tenant.user_id,
        actor_full_name=tenant_name,
        actor_username=tenant.email or tenant.phone,
        landlord_id=landlord_id,
        action="submit_payment",
        entity_type="payment",
        entity_id=payment.id,
        description=f"Payment {payment.payment_ref} of KES {amount} submitted for confirmation via tenant portal by {tenant_name}.",
        after_data=payment.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message": "Payment submitted. Your landlord will confirm it shortly.",
        "payment": payment.to_dict(),
    }), 201


# ---------------------------------------------------------------------------
# GET /api/portal/payments/<id>/receipt
# ---------------------------------------------------------------------------
@tenant_portal_bp.route("/payments/<int:payment_id>/receipt", methods=["GET"])
@jwt_required()
def download_receipt(payment_id):
    """
    Receipt for a CONFIRMED payment. Mirrors the landlord's report flow:
      ?format=json  -> structured receipt data to view on screen first
      ?format=pdf   -> the branded PDF download (also emailed to the tenant)
    A pending/declined payment has no receipt (403). Own payments only.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Receipt (JSON view or PDF stream).}
      403: {description: Payment not yet confirmed.}
      404: {description: Payment not found.}
    """
    from services.receipt_service import build_receipt, render_receipt_pdf

    tenant, _ = _require_tenant()
    fmt = (request.args.get("format") or "pdf").lower()

    payment = Payment.query.filter_by(
        id=payment_id, tenant_id=tenant.id, is_deleted=False
    ).first()
    if not payment:
        return jsonify({"error": "Payment not found."}), 404
    if payment.status != PaymentStatus.confirmed.value:
        return jsonify({"error": "A receipt is only available once the payment is confirmed."}), 403

    if fmt == "json":
        return jsonify(build_receipt(payment)), 200

    pdf_bytes = render_receipt_pdf(payment)

    # Auto-email a copy on download.
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
            "id":          f"inv-{inv.id}",
            "_sort":       (d, inv.created_at.isoformat() if inv.created_at else "", inv.id),
            "date":        d,
            "type":        "invoice",
            "description": inv.title or inv.invoice_type,
            "invoice_no":  inv.invoice_number,
            "amount_due":  float(inv.total_amount),
            "amount_paid": float(inv.amount_paid),
            "status":      inv.status,
        })

    for pay in tenant.payments:
        # Only landlord-confirmed payments belong on the ledger; pending
        # submissions await confirmation and must not move the balance.
        if pay.is_deleted or pay.status != PaymentStatus.confirmed.value:
            continue
        d = str(pay.payment_date)
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        # Surface the payment "proof" the tenant can verify against their own
        # records: the M-Pesa transaction code / till, else the internal ref.
        proof_ref = pay.mpesa_reference or pay.till_number or pay.payment_ref
        method_label = pay.payment_method or (pay.source.value if hasattr(pay.source, "value") else pay.source)
        entries.append({
            "id":              f"pay-{pay.id}",
            "_sort":           (d, pay.created_at.isoformat() if pay.created_at else "", pay.id),
            "date":            d,
            "type":            "payment",
            "description":     f"Payment — {method_label}",
            "payment_ref":     pay.payment_ref,
            "mpesa_reference": pay.mpesa_reference,
            "till_number":     pay.till_number,
            "proof_ref":       proof_ref,
            "amount":          float(pay.amount),
            "status":          pay.status,
        })

    # #13 — strict chronological order: same-day events keep the order they were
    # recorded (by created_at, then id), not batched by type.
    entries.sort(key=lambda x: x["_sort"])

    # Running balance in the #10 convention: owed positive, advance/credit negative.
    running = 0.0
    for e in entries:
        if e["type"] == "invoice":
            running += e["amount_due"]
        else:
            running -= e["amount"]
        e["running_balance"] = round(running, 2)
        e.pop("_sort", None)

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
        actor_user_id=tenant.user_id,
        actor_full_name=f"{tenant.first_name} {tenant.last_name}".strip(),
        actor_username=tenant.email or tenant.phone,
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
        actor_user_id=tenant.user_id,
        actor_full_name=f"{tenant.first_name} {tenant.last_name}".strip(),
        actor_username=tenant.email or tenant.phone,
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


# ---------------------------------------------------------------------------
# Tenant ↔ Landlord message thread
# ---------------------------------------------------------------------------
# Categories a tenant may tag a message with, so the landlord/team can triage
# "what they want" at a glance.
PORTAL_MESSAGE_CATEGORIES = {"rent", "repairs", "complaint", "documents", "general"}


@tenant_portal_bp.route("/messages", methods=["GET"])
@jwt_required()
def list_messages():
    """
    Return the authenticated tenant's full conversation thread with their
    landlord (both directions), oldest-first. Opening the thread marks every
    landlord/team message as read.
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      200: {description: Conversation thread.}
    """
    from models import TenantMessage
    tenant, landlord_id = _require_tenant()

    msgs = (
        TenantMessage.query
        .filter_by(landlord_id=landlord_id, tenant_id=tenant.id)
        .order_by(TenantMessage.created_at.asc())
        .all()
    )

    # Mark inbound (landlord/team) messages as read now that the tenant sees them.
    unread = [m for m in msgs if m.sender_role != "tenant" and not m.is_read]
    if unread:
        for m in unread:
            m.is_read = True
            m.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({
        "messages":   [m.to_dict() for m in msgs],
        "total":      len(msgs),
        "categories": sorted(PORTAL_MESSAGE_CATEGORIES),
    }), 200


@tenant_portal_bp.route("/messages", methods=["POST"])
@jwt_required()
def send_message():
    """
    Tenant sends a message to their landlord/team. Fans out an in-app
    notification to the landlord and every team member holding the
    `messages` permission, so they're alerted the same way maintenance
    requests already alert them.

    Body: { body (required), category? }
    ---
    tags: [Tenant Portal]
    security:
      - Bearer: []
    responses:
      201: {description: Message sent.}
      400: {description: Validation error.}
    """
    from models import (
        TenantMessage, Landlord, TeamMember, TeamMemberPermission,
    )
    from services.notification_service import notify

    tenant, landlord_id = _require_tenant()
    data     = request.get_json(silent=True) or {}
    body     = (data.get("body") or "").strip()
    category = (data.get("category") or "general").strip().lower()

    if not body:
        return jsonify({"error": "Message body is required."}), 400
    if category not in PORTAL_MESSAGE_CATEGORIES:
        category = "general"

    tenant_name = f"{tenant.first_name} {tenant.last_name}".strip()
    msg = TenantMessage(
        landlord_id    = landlord_id,
        tenant_id      = tenant.id,
        sender_role    = "tenant",
        sender_user_id = tenant.user_id,
        sender_name    = tenant_name,
        category       = category,
        body           = body,
        is_read        = False,
    )
    db.session.add(msg)
    db.session.flush()

    title   = f"New message from {tenant_name}"
    preview = body if len(body) <= 120 else body[:117] + "…"

    # Notify the landlord.
    landlord_row = db.session.get(Landlord, landlord_id)
    if landlord_row and landlord_row.user_id:
        notify(
            recipient_user_id=landlord_row.user_id,
            category="tenant_message",
            title=title,
            body=preview,
            landlord_id=landlord_id,
            link=f"/landlord/messages?tenant={tenant.id}",
            entity_type="tenant_message",
            entity_id=msg.id,
        )

    # Notify every active team member who can see the `messages` module.
    team_rows = (
        db.session.query(TeamMember)
        .join(TeamMemberPermission, TeamMemberPermission.team_member_id == TeamMember.id)
        .filter(
            TeamMember.landlord_id == landlord_id,
            TeamMember.is_active.is_(True),
            TeamMemberPermission.module == "messages",
            db.or_(
                TeamMemberPermission.can_view.is_(True),
                TeamMemberPermission.can_edit.is_(True),
            ),
        )
        .all()
    )
    for tm in team_rows:
        if tm.user_id:
            notify(
                recipient_user_id=tm.user_id,
                category="tenant_message",
                title=title,
                body=preview,
                landlord_id=landlord_id,
                link=f"/team/messages?tenant={tenant.id}",
                entity_type="tenant_message",
                entity_id=msg.id,
            )

    db.session.commit()

    return jsonify({
        "message": "Message sent.",
        "data":    msg.to_dict(),
    }), 201