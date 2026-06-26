"""
routes/mpesa_routes.py — Landlord-Initiated M-Pesa Actions
Blueprint: mpesa_bp  |  Prefix: /api/mpesa

This file covers LANDLORD-INITIATED M-Pesa actions, NOT provider callbacks.
Callbacks (C2B confirmation, STK push result) live in webhook_routes.py.

Two payment flows supported:
  1. Daraja STK Push — landlord triggers a payment prompt on the tenant's phone.
     Flow: POST /stk-push → Daraja API → STK callback (webhook_routes.py)
           → MpesaTransaction updated → Payment created on success.

  2. C2B Paybill / Till — tenant pays to the landlord's shortcode directly.
     Flow: Tenant pays → C2B webhook (webhook_routes.py) fires
           → MpesaTransaction created (status=unmatched)
           → Landlord uses POST /status-check to find the transaction
           → Manually or auto-matched to a tenant/payment.

  3. Co-Pilot SMS Ingest — landlord's phone agent forwarding M-Pesa
     confirmation SMS text to the platform.
     Flow: Co-Pilot mobile app → POST /copilot/ingest
           → Platform parses SMS → Creates MpesaTransaction → Matches.

Environment variables required:
  DARAJA_CONSUMER_KEY, DARAJA_CONSUMER_SECRET,
  DARAJA_SHORTCODE, DARAJA_PASSKEY,
  DARAJA_BASE_URL (https://api.safaricom.co.ke OR sandbox)
"""

import os
import re
import base64
import hashlib
from datetime import datetime
from decimal import Decimal

import requests as ext_requests
from flask import Blueprint, request, jsonify, abort, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    MpesaTransaction, Payment, Tenant, Landlord,
    MpesaTransactionStatus, PaymentStatus, PaymentSource,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit

mpesa_bp = Blueprint("mpesa", __name__, url_prefix="/api/mpesa")


# ===========================================================================
# Daraja helpers
# ===========================================================================

def _daraja_access_token() -> str:
    """Obtain a Daraja OAuth token. Token is short-lived — fetch fresh each time."""
    consumer_key    = os.getenv("DARAJA_CONSUMER_KEY", "")
    consumer_secret = os.getenv("DARAJA_CONSUMER_SECRET", "")
    base_url        = os.getenv("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")

    credentials = base64.b64encode(
        f"{consumer_key}:{consumer_secret}".encode()
    ).decode()

    resp = ext_requests.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _daraja_stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _payment_ref_number(landlord_id: int) -> str:
    count = Payment.query.filter_by(landlord_id=landlord_id).count()
    return f"PAY-{landlord_id}-{count + 1:06d}"


# ===========================================================================
# Co-Pilot SMS Parser
# ===========================================================================

# Example Safaricom M-Pesa confirmation SMS:
# "RXXXXXXXXX Confirmed. Ksh1,500.00 received from JOHN DOE 254712345678 on 1/6/25 at 10:34 AM"
_MPESA_SMS_PATTERN = re.compile(
    r"(?P<ref>[A-Z0-9]{10})\s+Confirmed\.\s+"
    r"Ksh(?P<amount>[\d,]+\.?\d*)\s+received from\s+"
    r"(?P<sender_name>.+?)\s+(?P<phone>2547\d{8})",
    re.IGNORECASE,
)


def _parse_mpesa_sms(sms_text: str) -> dict | None:
    """
    Parse a raw M-Pesa C2B confirmation SMS.
    Returns dict with keys: ref, amount, sender_name, phone — or None if no match.
    """
    match = _MPESA_SMS_PATTERN.search(sms_text)
    if not match:
        return None
    return {
        "ref":         match.group("ref"),
        "amount":      Decimal(match.group("amount").replace(",", "")),
        "sender_name": match.group("sender_name").strip(),
        "phone":       match.group("phone"),
    }


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
    Trigger a Daraja STK Push — sends a payment prompt to the tenant's phone.

    Body:
      { tenant_id: int,
        amount: number,
        invoice_id?: int,    -- optional: pre-fills account reference
        description?: str }

    Flow:
      1. Validate tenant, fetch phone number (must be 254XXXXXXXXX format).
      2. Get Daraja access token.
      3. POST to /mpesa/stkpush/v1/processrequest.
      4. Create MpesaTransaction (status=pending, description=CheckoutRequestID).
      5. Return immediately — Daraja will call POST /api/webhooks/mpesa/stk-callback
         when the tenant completes or cancels.

    The webhook_routes.py callback handler is responsible for creating the
    confirmed Payment row and updating the MpesaTransaction status.
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      200: {description: STK Push initiated. Awaiting callback.}
      400: {description: Validation error or Daraja rejection.}
      404: {description: Tenant not found.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    tenant_id   = data.get("tenant_id")
    amount      = data.get("amount")
    invoice_id  = data.get("invoice_id")
    description = data.get("description", "Rent Payment")

    if not tenant_id or not amount:
        return jsonify({"error": "tenant_id and amount are required."}), 400

    tenant = Tenant.query.filter_by(
        id=tenant_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if not tenant:
        return jsonify({"error": "Tenant not found."}), 404

    # Normalise phone: must be 2547XXXXXXXX
    phone = (tenant.phone or "").replace("+", "").replace(" ", "")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "254" + phone[1:]
    if not re.match(r"^2547\d{8}$|^2541\d{8}$", phone):
        return jsonify({"error": f"Tenant phone '{phone}' is not a valid Safaricom number."}), 400

    # Daraja configuration
    shortcode  = os.getenv("DARAJA_SHORTCODE", "")
    passkey    = os.getenv("DARAJA_PASSKEY", "")
    base_url   = os.getenv("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")
    callback   = os.getenv("DARAJA_STK_CALLBACK_URL", "")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    password  = _daraja_stk_password(shortcode, passkey, timestamp)

    # Account reference: invoice number if provided, else tenant last name
    account_ref = f"INV-{invoice_id}" if invoice_id else (tenant.last_name or "RENT")

    try:
        token = _daraja_access_token()
    except Exception as e:
        current_app.logger.error(f"Daraja token error: {e}")
        return jsonify({"error": "Could not obtain M-Pesa API token. Check credentials."}), 502

    stk_payload = {
        "BusinessShortCode": shortcode,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            int(float(amount)),    # Daraja requires integer
        "PartyA":            phone,
        "PartyB":            shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback,
        "AccountReference":  account_ref[:12],
        "TransactionDesc":   description[:13],
    }

    try:
        resp = ext_requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            json=stk_payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        resp_data = resp.json()
    except Exception as e:
        current_app.logger.error(f"STK Push API error: {e}")
        return jsonify({"error": "STK Push request failed. Try again."}), 502

    # Daraja success: ResponseCode == "0"
    if resp_data.get("ResponseCode") != "0":
        return jsonify({
            "error":       resp_data.get("ResponseDescription", "STK Push rejected."),
            "daraja_code": resp_data.get("ResponseCode"),
        }), 400

    checkout_request_id = resp_data.get("CheckoutRequestID", "")

    # Create pending MpesaTransaction
    mpesa_txn = MpesaTransaction(
        landlord_id      = landlord_id,
        reference_number = checkout_request_id,
        shortcode        = shortcode,
        status           = MpesaTransactionStatus.pending.value,
        amount           = Decimal(str(amount)),
        tenant_id        = tenant.id,
        description      = f"STK Push | {description}",
    )
    db.session.add(mpesa_txn)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="stk_push_initiated",
        entity_type="payment",
        entity_id=mpesa_txn.id,
        description=(
            f"STK Push of KES {amount} sent to {phone} "
            f"(CheckoutRequestID: {checkout_request_id})."
        ),
    )
    db.session.commit()

    return jsonify({
        "message":              "STK Push sent. Awaiting tenant confirmation.",
        "checkout_request_id":  checkout_request_id,
        "mpesa_transaction_id": mpesa_txn.id,
        "merchant_request_id":  resp_data.get("MerchantRequestID"),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/mpesa/copilot/ingest
# ---------------------------------------------------------------------------
@mpesa_bp.route("/copilot/ingest", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def copilot_ingest():
    """
    Co-Pilot app forwards a raw M-Pesa confirmation SMS text.
    The platform parses it, creates or updates a MpesaTransaction,
    and attempts to auto-match it to a Tenant.

    Matching rules (in order):
      1. Phone number → Tenant.phone (exact match after normalisation)
      2. If no match: status=unmatched; landlord resolves manually.

    If a match is found and auto-confirm is enabled, a Payment row is created.

    Body:
      { sms_text: str,
        agent_code: str,    -- identifies which landlord account
        shortcode?: str,
        till_number?: str,
        auto_confirm?: bool  -- default False; if True creates Payment automatically }
    ---
    tags: [M-Pesa]
    security:
      - Bearer: []
    responses:
      201: {description: M-Pesa transaction ingested.}
      400: {description: SMS parse failure or validation error.}
    """
    landlord_id  = get_current_landlord_id()
    data         = request.get_json(silent=True) or {}
    sms_text     = (data.get("sms_text") or "").strip()
    auto_confirm = bool(data.get("auto_confirm", False))

    if not sms_text:
        return jsonify({"error": "sms_text is required."}), 400

    # Parse SMS
    parsed = _parse_mpesa_sms(sms_text)
    if not parsed:
        return jsonify({
            "error": "Could not parse M-Pesa SMS. Ensure it is a valid Safaricom confirmation message.",
            "sms_text": sms_text,
        }), 400

    ref    = parsed["ref"]
    amount = parsed["amount"]
    phone  = parsed["phone"]

    # Check for duplicate reference
    existing = MpesaTransaction.query.filter_by(
        landlord_id=landlord_id, reference_number=ref
    ).first()
    if existing:
        return jsonify({
            "message":     "Transaction already recorded.",
            "transaction": existing.to_dict(),
        }), 200

    # Attempt tenant match by phone
    norm_phone = phone if phone.startswith("254") else "254" + phone[1:]
    tenant     = Tenant.query.filter_by(
        landlord_id=landlord_id, is_deleted=False
    ).filter(
        db.or_(Tenant.phone == phone, Tenant.phone == norm_phone)
    ).first()

    status = (
        MpesaTransactionStatus.recorded.value if tenant
        else MpesaTransactionStatus.unmatched.value
    )

    mpesa_txn = MpesaTransaction(
        landlord_id      = landlord_id,
        reference_number = ref,
        shortcode        = data.get("shortcode"),
        till_number      = data.get("till_number"),
        status           = status,
        amount           = amount,
        tenant_id        = tenant.id if tenant else None,
        description      = f"Co-Pilot | {parsed['sender_name']} | {sms_text[:120]}",
    )
    db.session.add(mpesa_txn)
    db.session.flush()

    payment = None
    if tenant and auto_confirm:
        # Auto-create a confirmed payment
        payment = Payment(
            payment_ref     = _payment_ref_number(landlord_id),
            landlord_id     = landlord_id,
            tenant_id       = tenant.id,
            unit_id         = tenant.unit_id,
            property_id     = (tenant.unit.property_id if tenant.unit else None),
            amount          = amount,
            payment_date    = datetime.utcnow().date(),
            status          = PaymentStatus.confirmed.value,
            source          = PaymentSource.co_pilot.value,
            mpesa_reference = ref,
            notes           = f"Auto-confirmed via Co-Pilot. SMS ref: {ref}",
        )
        db.session.add(payment)
        db.session.flush()

        mpesa_txn.payment_id = payment.id
        mpesa_txn.status     = MpesaTransactionStatus.recorded.value

        # Update tenant balance
        tenant.balance = (tenant.balance or Decimal("0")) + amount

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="copilot_ingest",
        entity_type="payment",
        entity_id=mpesa_txn.id,
        description=(
            f"Co-Pilot SMS ingested: {ref}, KES {amount}. "
            f"Tenant match: {'yes' if tenant else 'no'}. "
            f"Auto-confirmed: {auto_confirm}."
        ),
    )
    db.session.commit()

    return jsonify({
        "message":       "SMS ingested successfully.",
        "transaction":   mpesa_txn.to_dict(),
        "tenant_matched": tenant is not None,
        "payment":       payment.to_dict() if payment else None,
        "status":        status,
    }), 201


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

    payment = Payment(
        payment_ref     = _payment_ref_number(landlord_id),
        landlord_id     = landlord_id,
        tenant_id       = tenant.id,
        unit_id         = tenant.unit_id,
        property_id     = (tenant.unit.property_id if tenant.unit else None),
        amount          = mpesa_txn.amount or Decimal("0"),
        payment_date    = datetime.utcnow().date(),
        status          = PaymentStatus.confirmed.value,
        source          = PaymentSource.mpesa.value,
        mpesa_reference = mpesa_txn.reference_number,
        notes           = f"Manually matched from M-Pesa transaction #{mpesa_txn.id}",
    )
    db.session.add(payment)
    db.session.flush()

    mpesa_txn.tenant_id  = tenant.id
    mpesa_txn.payment_id = payment.id
    mpesa_txn.status     = MpesaTransactionStatus.recorded.value

    tenant.balance = (tenant.balance or Decimal("0")) + (mpesa_txn.amount or Decimal("0"))

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