"""
routes/mpesa_routes.py — Landlord-Initiated M-Pesa Actions
Blueprint: mpesa_bp  |  Prefix: /api/mpesa

This file covers LANDLORD-INITIATED M-Pesa actions, NOT provider callbacks.
Callbacks (C2B confirmation, STK push result) live in webhook_routes.py.

Two payment flows supported:
  1. Daraja STK Push — landlord triggers a payment prompt on the tenant's phone.
     GATED OFF (MPESA_INTEGRATION_SPEC.md D1): no per-landlord Daraja
     credentials exist yet, so this would otherwise route tenant rent into
     Sahil's OWN platform paybill — commingling platform revenue with
     landlords' rent. POST /stk-push returns 409 until a per-landlord
     credentials phase exists.

  2. C2B Paybill / Till — tenant pays to the landlord's shortcode directly.
     Flow: Tenant pays → C2B webhook (webhook_routes.py) fires
           → MpesaTransaction created (status=unmatched)
           → Landlord uses POST /status-check to find the transaction
           → Manually or auto-matched to a tenant/payment.
     This flow is UNCHANGED and still fully supported — it never touches the
     platform paybill, only whatever paybill/till the landlord already owns.

Co-Pilot SMS ingestion lives in routes/copilot_routes.py (POST
/api/copilot/ingest) — it's device-token authenticated, not landlord-JWT, so
it can't live here. See COPILOT_PLATFORM_SPEC.md.
"""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    MpesaTransaction, Payment, Tenant, Landlord,
    MpesaTransactionStatus, PaymentStatus, PaymentSource,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit

mpesa_bp = Blueprint("mpesa", __name__, url_prefix="/api/mpesa")


def _payment_ref_number(landlord_id: int) -> str:
    count = Payment.query.filter_by(landlord_id=landlord_id).count()
    return f"PAY-{landlord_id}-{count + 1:06d}"


# ===========================================================================
# Routes
# ===========================================================================

# ---------------------------------------------------------------------------
# POST /api/mpesa/status-check
# ---------------------------------------------------------------------------
@mpesa_bp.route("/status-check", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def status_check():
    """
    Look up an M-Pesa transaction by reference number and shortcode/till.
    Used by the landlord to confirm whether a payment has been recorded.

    Body: { reference_number: str, shortcode?: str, till_number?: str }

    Returns the MpesaTransaction if found, including its current status
    and any linked Payment or Tenant.
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      200: {description: Transaction found.}
      404: {description: No matching transaction.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    reference_number = (data.get("reference_number") or "").strip().upper()
    shortcode        = data.get("shortcode")
    till_number      = data.get("till_number")

    if not reference_number:
        return jsonify({"error": "reference_number is required."}), 400

    query = MpesaTransaction.query.filter_by(
        landlord_id=landlord_id, reference_number=reference_number
    )
    if shortcode:
        query = query.filter_by(shortcode=shortcode)
    if till_number:
        query = query.filter_by(till_number=till_number)

    txn = query.first()
    if not txn:
        return jsonify({
            "found":   False,
            "message": "No M-Pesa transaction found with those details.",
        }), 404

    d = txn.to_dict()
    if txn.tenant:
        d["tenant_name"] = f"{txn.tenant.first_name} {txn.tenant.last_name}"
    if txn.payment:
        d["payment"] = txn.payment.to_dict()

    return jsonify({"found": True, "transaction": d}), 200


# ---------------------------------------------------------------------------
# GET /api/mpesa/transactions
# ---------------------------------------------------------------------------
@mpesa_bp.route("/transactions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def list_transactions():
    """
    Return the M-Pesa transaction status table for this landlord.
    Filters: ?status=recorded|unmatched|pending, ?start_date=, ?end_date=,
             ?shortcode=, ?till_number=, ?page=, ?per_page=
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated M-Pesa transaction list.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = MpesaTransaction.query.filter_by(landlord_id=landlord_id)

    if v := request.args.get("status"):
        query = query.filter(MpesaTransaction.status == v)
    if v := request.args.get("shortcode"):
        query = query.filter(MpesaTransaction.shortcode == v)
    if v := request.args.get("till_number"):
        query = query.filter(MpesaTransaction.till_number == v)
    if v := request.args.get("start_date"):
        query = query.filter(MpesaTransaction.created_date >= v)
    if v := request.args.get("end_date"):
        query = query.filter(MpesaTransaction.created_date <= v)

    paginated = query.order_by(MpesaTransaction.created_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for txn in paginated.items:
        d = txn.to_dict()
        d["tenant_name"] = (
            f"{txn.tenant.first_name} {txn.tenant.last_name}" if txn.tenant else None
        )
        d["payment_ref"] = txn.payment.payment_ref if txn.payment else None
        items.append(d)

    return jsonify({
        "transactions": items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/mpesa/stk-push
# ---------------------------------------------------------------------------
@mpesa_bp.route("/stk-push", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def stk_push():
    """
    GATED OFF (MPESA_INTEGRATION_SPEC.md D1) — no per-landlord Daraja
    credentials exist yet. Rent must never flow through the platform's own
    paybill (that would commingle tenant rent with platform revenue and make
    Sahil a payment aggregator holding landlords' money). Until a
    per-landlord-credentials phase is built, direct STK prompts for rent are
    unavailable; landlords collect rent on their own paybill/till via
    Co-Pilot SMS forwarding, tenant self-report, or manual matching (the
    M-Pesa Transaction Status tools below are unaffected).
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      409: {description: Direct M-Pesa prompts are not available yet.}
    """
    return jsonify({
        "error": (
            "Direct M-Pesa prompts are not available yet. Rent payments go to "
            "your own paybill — use Co-Pilot or record the payment manually."
        ),
    }), 409


# ---------------------------------------------------------------------------
# POST /api/mpesa/transactions/<id>/match
# ---------------------------------------------------------------------------
@mpesa_bp.route("/transactions/<int:txn_id>/match", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def match_transaction(txn_id):
    """
    Manually match an unmatched MpesaTransaction to a tenant and create a Payment.
    Body: { tenant_id: int }

    Used by the landlord when auto-matching failed (status=unmatched).
    Creates a confirmed Payment row and updates the MpesaTransaction status to 'recorded'.
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      200: {description: Transaction matched and payment created.}
      400: {description: Already matched.}
      404: {description: Transaction or tenant not found.}
    """
    landlord_id = get_current_landlord_id()
    mpesa_txn   = MpesaTransaction.query.filter_by(
        id=txn_id, landlord_id=landlord_id
    ).first()
    if not mpesa_txn:
        return jsonify({"error": "M-Pesa transaction not found."}), 404
    if mpesa_txn.status == MpesaTransactionStatus.recorded.value:
        return jsonify({"error": "This transaction is already matched to a payment."}), 400

    data      = request.get_json(silent=True) or {}
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        return jsonify({"error": "tenant_id is required."}), 400

    tenant = Tenant.query.filter_by(
        id=tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not tenant:
        return jsonify({"error": "Tenant not found."}), 404

    # If this transaction originated from Co-pilot, tag the payment's source
    # accordingly and respect the landlord's copilot_auto_allocate choice —
    # otherwise (a plain C2B/STK transaction the landlord is resolving
    # themselves) confirm immediately, same as before.
    from models import CopilotMessage, CopilotMatchStatus
    copilot_msg = CopilotMessage.query.filter_by(mpesa_transaction_id=mpesa_txn.id).first()
    landlord    = db.session.get(Landlord, landlord_id)
    ls          = landlord.landlord_settings if landlord else None
    auto_now    = bool(ls and ls.copilot_auto_allocate) if copilot_msg else True

    payment = Payment(
        payment_ref     = _payment_ref_number(landlord_id),
        landlord_id     = landlord_id,
        tenant_id       = tenant.id,
        unit_id         = tenant.unit_id,
        property_id     = (tenant.unit.property_id if tenant.unit else None),
        amount          = mpesa_txn.amount or Decimal("0"),
        payment_date    = datetime.utcnow().date(),
        status          = PaymentStatus.confirmed.value if auto_now else PaymentStatus.pending.value,
        source          = PaymentSource.co_pilot.value if copilot_msg else PaymentSource.mpesa.value,
        mpesa_reference = mpesa_txn.reference_number,
        notes           = f"Manually matched from M-Pesa transaction #{mpesa_txn.id}",
    )
    db.session.add(payment)
    db.session.flush()

    mpesa_txn.tenant_id  = tenant.id
    mpesa_txn.payment_id = payment.id
    mpesa_txn.status     = MpesaTransactionStatus.recorded.value

    # #4.6 — the allocation service is the single writer of allocations/ledgers;
    # a pending payment (copilot review mode) touches no balances until confirmed.
    if payment.status == PaymentStatus.confirmed.value:
        from services.allocation_service import auto_allocate as _auto_allocate, apply_allocations
        alloc_rows = _auto_allocate(tenant, payment.amount, landlord, ref_date=payment.payment_date)
        apply_allocations(payment, tenant, alloc_rows, landlord_id)
    elif copilot_msg and landlord and landlord.user_id:
        from services.notification_service import notify
        notify(
            recipient_user_id=landlord.user_id,
            category="copilot_payment_pending",
            template_key="copilot_payment_pending",
            template_kwargs={
                "amount": f"{payment.amount:,.2f}",
                "sender_name": copilot_msg.parsed_name or copilot_msg.sender_id,
                "tenant_name": f"{tenant.first_name} {tenant.last_name}",
            },
            landlord_id=landlord_id,
            link="/landlord/payments?status=pending",
            entity_type="payment", entity_id=payment.id,
        )

    if copilot_msg:
        copilot_msg.tenant_id    = tenant.id
        copilot_msg.payment_id   = payment.id
        copilot_msg.match_status = CopilotMatchStatus.matched.value

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="match_mpesa_transaction",
        entity_type="payment",
        entity_id=payment.id,
        description=(
            f"M-Pesa transaction {mpesa_txn.reference_number} manually matched "
            f"to tenant {tenant_id}. Payment {payment.payment_ref} created."
        ),
        after_data=payment.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":     "Transaction matched.",
        "transaction": mpesa_txn.to_dict(),
        "payment":     payment.to_dict(),
    }), 200