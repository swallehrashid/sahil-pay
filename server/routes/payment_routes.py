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

from flask import Blueprint, request, jsonify, abort, Response, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Payment, PaymentAllocation, Invoice, Tenant, Landlord,
    BankStatementUpload, BankStatementTransaction,
    PaymentStatus, PaymentSource, InvoiceStatus,
    BankStatementStatus,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.audit_service   import record_audit
from services.pdf_service     import generate_receipt_pdf
from services.email_service   import send_receipt_email
from services.sms_service     import send_sms
from services.notification_service import notify
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
@scope_to_accessible_properties
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

    if g.accessible_property_ids is not None:
        query = query.filter(Payment.property_id.in_(g.accessible_property_ids))

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
    # #5 — the landlord chooses how the payment is spread over the tenant's invoices:
    #   'auto'   → follow Settings → Payments auto-allocation priority
    #   'manual' → apply the explicit {invoice_id, amount_allocated} rows they passed
    allocation_mode = data.get("allocation_mode") or ("manual" if allocations else "auto")

    if not tenant_id or amount <= 0:
        return jsonify({"error": "tenant_id and a positive amount are required."}), 400

    tenant = Tenant.query.filter_by(
        id=tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not tenant:
        return jsonify({"error": "Tenant not found."}), 404

    # Validate allocation total (manual only; auto never exceeds the amount by design)
    alloc_total = sum(Decimal(str(a.get("amount_allocated", 0))) for a in allocations)
    if allocation_mode == "manual" and alloc_total > amount:
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

    # #5/#7 — the allocation service is the single writer of PaymentAllocation rows and
    # invoice amount_paid/balance/status (fully-cleared invoices auto-flip to 'paid').
    from services.allocation_service import auto_allocate, apply_allocations
    landlord = db.session.get(Landlord, landlord_id)
    if allocation_mode == "auto" and payment.status == PaymentStatus.confirmed.value:
        allocations = auto_allocate(tenant, amount, landlord, ref_date=payment.payment_date or date.today())
    # A pending payment is not allocated until it's confirmed; only confirmed payments
    # touch the ledger.
    if payment.status == PaymentStatus.confirmed.value:
        apply_allocations(payment, tenant, allocations, landlord_id)

    # Ledger convention (matches landlord_dashboard_routes/report_routes/export_service):
    # negative balance = arrears (owed), positive = advance (credit). The FULL payment
    # reduces what's owed regardless of how it's allocated across invoices — allocation
    # only determines which invoices show as paid; the tenant's running balance is
    # simply lifetime charges minus lifetime payments. A pending (unconfirmed) payment
    # does NOT touch the ledger until it's confirmed.
    if payment.status == PaymentStatus.confirmed.value:
        tenant.balance = (tenant.balance or Decimal("0")) + amount

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

    # Fire the landlord's "payment" alert (respects Settings → Alerts: enabled +
    # channel) and run the payment-acknowledgment automation (Settings →
    # Automation). Both no-op if the landlord has them off.
    if payment.status == PaymentStatus.confirmed.value:
        from services.alert_service import dispatch_alert
        from services.automation_service import on_payment_recorded

        landlord = db.session.get(Landlord, landlord_id)
        tenant_name = f"{tenant.first_name} {tenant.last_name}"
        dispatch_alert(
            landlord_id,
            "payment",
            title="Payment received",
            body=f"{tenant_name} paid KES {amount} ({payment.payment_ref}).",
            link="/landlord/payments",
            entity_type="payment",
            entity_id=payment.id,
        )
        on_payment_recorded(landlord, payment, tenant)
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
# GET /api/payments/<id>/allocation-preview  — proposed auto-allocation
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/allocation-preview", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def allocation_preview(payment_id):
    """
    Show how this payment WOULD be auto-allocated across the tenant's
    outstanding invoices (in the landlord's configured priority order), so the
    landlord can accept it or switch to manual before confirming. Read-only.
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Outstanding invoices + proposed auto-allocation.}
    """
    from services.allocation_service import (
        auto_allocate, outstanding_invoices, categorize_invoice,
        CATEGORY_LABELS, get_allocation_priority,
    )
    landlord_id = get_current_landlord_id()
    pay = _get_or_404(landlord_id, payment_id)
    tenant = pay.tenant
    landlord = db.session.get(Landlord, landlord_id)
    ref_date = pay.payment_date or date.today()

    proposed = auto_allocate(tenant, pay.amount, landlord, ref_date=ref_date)
    proposed_by_inv = {a["invoice_id"]: float(a["amount_allocated"]) for a in proposed}

    invoices = []
    for inv in sorted(outstanding_invoices(tenant), key=lambda i: (i.issue_date or ref_date, i.id)):
        bal = float((inv.total_amount or 0) - (inv.amount_paid or 0))
        cat = categorize_invoice(inv, ref_date)
        invoices.append({
            "id":             inv.id,
            "invoice_number": inv.invoice_number,
            "title":          inv.title or inv.invoice_type,
            "invoice_type":   inv.invoice_type,
            "category":       cat,
            "category_label": CATEGORY_LABELS.get(cat, cat),
            "issue_date":     str(inv.issue_date),
            "balance":        bal,
            "proposed_amount": proposed_by_inv.get(inv.id, 0.0),
        })

    total_allocated = round(sum(proposed_by_inv.values()), 2)
    return jsonify({
        "payment_id":      pay.id,
        "amount":          float(pay.amount),
        "priority_order":  get_allocation_priority(landlord),
        "outstanding":     invoices,
        "proposed_total":  total_allocated,
        "advance_credit":  round(max(0.0, float(pay.amount) - total_allocated), 2),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/payments/<id>/confirm  — landlord/team confirms a submitted payment
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/confirm", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def confirm_payment(payment_id):
    """
    Confirm a pending (tenant-submitted) payment. Applies it to the tenant's
    invoices — either `manual` (explicit allocations) or `auto` (the landlord's
    priority order) — moves the tenant's balance, marks the payment confirmed,
    and notifies the tenant. Only now does the payment reflect on the tenant's
    ledger and become a downloadable receipt.

    Body: { mode: 'auto'|'manual', allocations?: [{invoice_id, amount_allocated}] }
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Payment confirmed.}
      400: {description: Already confirmed or invalid allocation.}
    """
    from services.allocation_service import auto_allocate, apply_allocations

    landlord_id = get_current_landlord_id()
    pay = _get_or_404(landlord_id, payment_id)
    if pay.status == PaymentStatus.confirmed.value:
        return jsonify({"error": "This payment is already confirmed."}), 400

    tenant = pay.tenant
    if not tenant:
        return jsonify({"error": "Payment has no tenant to allocate to."}), 400

    landlord = db.session.get(Landlord, landlord_id)
    data     = request.get_json(silent=True) or {}
    mode     = (data.get("mode") or "auto").lower()
    before   = pay.to_dict()

    if mode == "manual":
        allocations = data.get("allocations", [])
        alloc_total = sum(Decimal(str(a.get("amount_allocated", 0))) for a in allocations)
        if alloc_total > pay.amount:
            return jsonify({"error": "Allocation total exceeds the payment amount."}), 400
    else:
        allocations = auto_allocate(tenant, pay.amount, landlord, ref_date=pay.payment_date or date.today())

    apply_allocations(pay, tenant, allocations, landlord_id)

    # Ledger convention: the FULL payment reduces what's owed; any unallocated
    # remainder is advance credit (matches create_payment / the landlord side).
    tenant.balance = (tenant.balance or Decimal("0")) + pay.amount
    pay.status = PaymentStatus.confirmed.value
    db.session.commit()

    tenant_name = f"{tenant.first_name} {tenant.last_name}".strip()
    if tenant.user_id:
        notify(
            recipient_user_id=tenant.user_id,
            category="payment_received",
            title="Payment confirmed",
            body=f"Your payment of KES {pay.amount:,.2f} ({pay.payment_ref}) has been confirmed. Your receipt is now available.",
            landlord_id=landlord_id,
            link="/portal/pay",
            entity_type="payment",
            entity_id=pay.id,
        )

    # Landlord-side alert + acknowledgment automation (both no-op if disabled).
    from services.alert_service import dispatch_alert
    from services.automation_service import on_payment_recorded
    dispatch_alert(
        landlord_id, "payment",
        title="Payment confirmed",
        body=f"{tenant_name} — KES {pay.amount:,.2f} ({pay.payment_ref}).",
        link="/landlord/payments", entity_type="payment", entity_id=pay.id,
    )
    on_payment_recorded(landlord, pay, tenant)

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="confirm_payment",
        entity_type="payment",
        entity_id=pay.id,
        description=f"Payment {pay.payment_ref} of KES {pay.amount} confirmed ({mode} allocation) for {tenant_name}.",
        before_data=before,
        after_data=pay.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Payment confirmed.", "payment": pay.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/payments/<id>/decline  — reject a submitted payment
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:payment_id>/decline", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def decline_payment(payment_id):
    """
    Decline a pending (tenant-submitted) payment — e.g. proof doesn't check
    out. No ledger effect; the tenant is notified with the optional reason.
    Body: { reason?: str }
    ---
    tags: [Payments]
    security:
      - Bearer: []
    responses:
      200: {description: Payment declined.}
      400: {description: Only pending payments can be declined.}
    """
    landlord_id = get_current_landlord_id()
    pay = _get_or_404(landlord_id, payment_id)
    if pay.status == PaymentStatus.confirmed.value:
        return jsonify({"error": "A confirmed payment cannot be declined; delete it instead."}), 400

    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    before = pay.to_dict()

    pay.status = PaymentStatus.declined.value
    if reason:
        pay.notes = f"{pay.notes or ''}\nDeclined: {reason}".strip()
    db.session.commit()

    tenant = pay.tenant
    if tenant and tenant.user_id:
        body = f"Your payment of KES {pay.amount:,.2f} ({pay.payment_ref}) could not be confirmed."
        if reason:
            body += f" Reason: {reason}"
        notify(
            recipient_user_id=tenant.user_id,
            category="payment_received",
            title="Payment not confirmed",
            body=body,
            landlord_id=landlord_id,
            link="/portal/pay",
            entity_type="payment",
            entity_id=pay.id,
        )

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="decline_payment",
        entity_type="payment",
        entity_id=pay.id,
        description=f"Payment {pay.payment_ref} declined." + (f" Reason: {reason}" if reason else ""),
        before_data=before,
        after_data=pay.to_dict(),
    )
    db.session.commit()
    return jsonify({"message": "Payment declined.", "payment": pay.to_dict()}), 200


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
    """
    Send the payment receipt to the tenant on one or more channels.
    Body: { channels: ["email","sms","in_app"] }  (defaults to ["email"]).
    WhatsApp is accepted but not yet deliverable (no integration) — it's reported
    back as skipped so the caller knows. Each channel is best-effort and skipped
    (not failed) when the tenant lacks the needed contact detail.
    """
    landlord_id = get_current_landlord_id()
    pay         = _get_or_404(landlord_id, payment_id)
    tenant      = pay.tenant
    if not tenant:
        return jsonify({"error": "This payment is not linked to a tenant."}), 400

    data     = request.get_json(silent=True) or {}
    channels = data.get("channels") or ["email"]
    summary  = (
        f"Receipt {pay.payment_ref}: payment of KES {pay.amount} received "
        f"on {pay.payment_date}. Thank you."
    )

    sent, skipped = [], []
    for ch in channels:
        if ch == "email":
            if tenant.email:
                pdf_bytes = generate_receipt_pdf(pay)
                send_receipt_email.delay(tenant.email, tenant.first_name, pdf_bytes, pay.payment_ref)
                sent.append("email")
            else:
                skipped.append("email (no email on file)")
        elif ch == "sms":
            if tenant.phone:
                send_sms(tenant.phone, summary)
                sent.append("sms")
            else:
                skipped.append("sms (no phone on file)")
        elif ch == "in_app":
            if tenant.user_id:
                notify(
                    recipient_user_id=tenant.user_id,
                    category="payment_receipt",
                    title="Payment received",
                    body=summary,
                    landlord_id=landlord_id,
                    link="/portal/statement",
                    entity_type="payment",
                    entity_id=pay.id,
                )
                sent.append("in_app")
            else:
                skipped.append("in_app (tenant has no app account yet)")
        elif ch == "whatsapp":
            skipped.append("whatsapp (not yet integrated)")
        else:
            skipped.append(f"{ch} (unknown channel)")

    db.session.commit()   # persist any in-app notification rows

    if not sent:
        return jsonify({"error": "Receipt could not be sent. " + "; ".join(skipped)}), 400
    msg = "Receipt sent via " + ", ".join(sent)
    if skipped:
        msg += " — skipped: " + ", ".join(skipped)
    return jsonify({"message": msg, "sent": sent, "skipped": skipped}), 200


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

    # Reverse invoice allocations SAFELY: roll back each previously-allocated invoice's
    # amount_paid / balance / status before discarding the allocation rows — otherwise the
    # old tenant's invoices stay marked (partly) paid by a payment that no longer applies.
    for alloc in list(pay.payment_allocations):
        inv = alloc.invoice
        if inv:
            inv.amount_paid = max(Decimal("0"), (inv.amount_paid or Decimal("0")) - alloc.amount_allocated)
            inv.balance     = inv.total_amount - inv.amount_paid
            if inv.amount_paid <= 0:
                inv.status = InvoiceStatus.open.value
            elif inv.balance > 0:
                inv.status = InvoiceStatus.partial.value
            else:
                inv.status = InvoiceStatus.paid.value
        db.session.delete(alloc)
    db.session.flush()

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

    if created:
        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="import_bank_statement_payments",
            entity_type="payment",
            entity_id=upload.id,
            description=f"{len(created)} payment(s) imported from bank statement upload #{upload.id}.",
            after_data={"payment_ids": [p.id for p in created]},
        )
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