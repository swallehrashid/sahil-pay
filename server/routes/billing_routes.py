"""
routes/billing_routes.py — Platform Billing & Subscription
Blueprint: billing_bp  |  Prefix: /api/billing

Covers §4.21 + MPESA_INTEGRATION_SPEC.md (verified-only payments, D3):
  GET /                    — current plan summary (incl. paybill account refs)
  POST /pay-subscription     — LEGACY self-reported; records a PENDING,
                                UNVERIFIED transaction only. Does not activate
                                anything — an admin must verify it.
  POST /pay-subscription/stk — verified subscription payment via Daraja STK
                                Push (or simulation) to the platform paybill.
  POST /buy-sms              — LEGACY self-reported; same demotion as above.
  POST /buy-sms/stk          — verified SMS credit purchase via Daraja STK.
  GET /transactions/<id>/status — poll a pending transaction while waiting
                                for the Daraja callback.
  GET /transactions        — billing transaction history
  POST /tax-invoice        — generate platform-fee tax invoice PDF

Billing cycle discounts (applied server-side):
  monthly  → 0%   (full price)
  3-month  → 10%  discount
  annual   → 15%  discount

SMS pricing: reseller rate from services/sms_billing.py.  Minimum purchase
is 100 credits.

Both STK endpoints create a PENDING BillingTransaction and either finalise it
instantly (MPESA_SIMULATION_MODE=true, the default until go-live) or send a
real STK push and wait for POST /api/webhooks/daraja/billing-callback.  Only
a verified transaction activates anything or accrues affiliate commission
(AFFILIATE_PROGRAM_SPEC.md §3).
"""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Landlord, BillingTransaction, SubscriptionPlan,
    BillingTransactionType, BillingTransactionStatus,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service import record_audit
from services import billing_service, daraja_service
from services.daraja_service import DarajaError, normalize_msisdn

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")

# NOTE: the 3-tier discount structure (monthly/quarterly/annual) is keyed by
# SubscriptionPlan, not BillingCycle — BillingCycle only has monthly/yearly
# (it's a different axis: how often the landlord is actually invoiced, not
# which commitment tier's discount applies). The variable name "billing_cycle"
# below is kept as the original route used it, but it's really selecting a
# SubscriptionPlan value. The actual discount/tenor table now lives in
# services/billing_service.py so the legacy and verified-STK paths (and
# affiliate_service's commission math) all read the exact same numbers.
_CYCLE_DISCOUNTS = billing_service._CYCLE_DISCOUNTS
_CYCLE_MONTHS    = billing_service._CYCLE_MONTHS
_SMS_MIN_PURCHASE = 100
# Any amount from one shilling: installments are the point. A floor stops a
# stray zero, a ceiling stops a typo becoming a KES 10m prompt on someone's phone.
_MIN_PAYMENT = Decimal("1")
_MAX_PAYMENT = Decimal("1000000")


def _sub_account_ref(landlord_id: int) -> str:
    return f"SUB-{landlord_id}"


def _sms_account_ref(landlord_id: int) -> str:
    return f"SMS-{landlord_id}"


def _sms_unit_price(landlord: Landlord) -> Decimal:
    """
    KES this landlord pays for one SMS credit.

    Delegates to services/sms_billing.effective_price_per_sms — the SAME
    function the send path and the margin report use — so the price quoted on
    the buy screen, the price actually charged, and the price in the books can
    never disagree.

    This used to read the global rate directly and so ignored
    landlords.sms_price_override entirely: a landlord you had agreed 1.20 with
    was still charged 1.00 at the till, and the reports showed revenue that
    never arrived.
    """
    from services.sms_billing import effective_price_per_sms

    return effective_price_per_sms(landlord.landlord_settings, landlord=landlord)


# ---------------------------------------------------------------------------
# GET /api/billing/
# ---------------------------------------------------------------------------
@billing_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def get_billing_summary():
    """
    Return the landlord's current billing plan details:
      - plan name, unit count, cost, billing cycle, discount
      - amount_due, next_billing_date, subscription status
      - sms_balance
      - platform paybill number + this landlord's account reference strings
        for subscription and SMS direct-paybill payments
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Billing summary.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    # Auto-categorise into the right package by unit count and refresh the
    # derived figures (cost, next billing date, amount due) before returning.
    from services.billing_service import recompute_subscription

    subscription = recompute_subscription(landlord)
    billing_service.roll_forward(landlord)
    db.session.commit()
    package = landlord.package

    sms_price = float(_sms_unit_price(landlord))
    settings  = landlord.landlord_settings
    uses_own  = bool(settings and settings.sms_connected and settings.sms_sender_id)

    return jsonify({
        "subscription":  subscription.to_dict() if subscription else None,
        "package":       package.to_dict()      if package      else None,
        "sms_balance":   landlord.sms_balance,
        "sms_unit_price": sms_price,
        "sms_min_purchase": _SMS_MIN_PURCHASE,
        "sms_uses_own_sender": uses_own,
        "is_on_trial":   landlord.is_on_trial,
        "trial_ends_at": str(landlord.trial_ends_at) if landlord.trial_ends_at else None,
        "access":        billing_service.access_state(landlord),
        "pay_options":   billing_service.pay_amount_options(subscription) if subscription else [],
        "min_payment":   float(_MIN_PAYMENT),
        # The pay screen shows a "simulate the M-Pesa confirmation" control only
        # while simulation is on. It is never shown, and the endpoint refuses,
        # in production.
        "simulation_mode": bool(current_app.config.get("MPESA_SIMULATION_MODE", True)),
        "paybill": {
            "shortcode":              current_app.config.get("PLATFORM_DARAJA_SHORTCODE"),
            "subscription_account_ref": _sub_account_ref(landlord_id),
            "sms_account_ref":          _sms_account_ref(landlord_id),
        },
    }), 200


@billing_bp.route("/access", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def get_access():
    """Is the portal open? Lightweight — polled by the app shell."""
    landlord = db.session.get(Landlord, get_current_landlord_id())
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404
    if billing_service.roll_forward(landlord):
        db.session.commit()
    return jsonify(billing_service.access_state(landlord)), 200


# ---------------------------------------------------------------------------
# POST /api/billing/pay-subscription  (LEGACY — self-reported, unverified)
# ---------------------------------------------------------------------------
@billing_bp.route("/pay-subscription", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def pay_subscription():
    """
    LEGACY self-reported subscription payment — the Daraja-outage escape
    hatch. Body:
      { billing_cycle: 'monthly'|'quarterly'|'annual',
        payment_reference: str,
        package_id?: int   -- to switch package }

    Unlike before, this NO LONGER activates the subscription immediately —
    a landlord can no longer type any string into payment_reference and get
    service (MPESA_INTEGRATION_SPEC.md D3). It creates a PENDING, UNVERIFIED
    BillingTransaction with the intended activation stashed in context_json.
    An admin must verify it (POST /api/admin/billing-transactions/<id>/verify)
    before the subscription changes at all. Prefer POST /pay-subscription/stk
    for real landlord usage.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      202: {description: Payment recorded, pending admin verification.}
      400: {description: Invalid cycle or missing payment reference.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    billing_cycle     = data.get("billing_cycle", SubscriptionPlan.monthly.value)
    payment_reference = (data.get("payment_reference") or "").strip()
    new_package_id    = data.get("package_id")

    if not payment_reference:
        return jsonify({"error": "payment_reference is required."}), 400

    subscription = landlord.subscription
    if not subscription:
        return jsonify({"error": "No subscription found for this account."}), 400

    try:
        amount_due, months, discount = billing_service.preview_subscription_cost(
            subscription, billing_cycle, new_package_id
        )
    except ValueError as e:
        status_code = 404 if "Package" in str(e) else 400
        return jsonify({"error": str(e)}), status_code

    # Verified-only (D3): the activation intent is stashed but NOT applied.
    # Only an admin verify (or a matching Daraja callback) applies it.
    ctx = billing_service.build_subscription_context(
        billing_cycle, months, discount, new_package_id, applied=False
    )

    txn = BillingTransaction(
        landlord_id       = landlord_id,
        type              = BillingTransactionType.subscription.value,
        amount            = amount_due,
        payment_reference = payment_reference,
        status            = BillingTransactionStatus.pending.value,
        context_json      = ctx,
    )
    db.session.add(txn)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="pay_subscription_self_reported",
        entity_type="billing",
        entity_id=txn.id,
        description=(
            f"Self-reported subscription payment of KES {amount_due} recorded "
            f"({billing_cycle}, {discount}% discount) — pending admin verification."
        ),
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":      "Payment recorded. It will activate once verified by an admin.",
        "transaction":  txn.to_dict(),
        "subscription": subscription.to_dict(),
    }), 202


# ---------------------------------------------------------------------------
# STK payments — any amount, confirmed ONLY by Safaricom
# ---------------------------------------------------------------------------

def _money_or_400(raw):
    try:
        value = Decimal(str(raw)).quantize(Decimal("1"))
    except Exception:
        return None
    if value < _MIN_PAYMENT or value > _MAX_PAYMENT:
        return None
    return value


def _send_stk(landlord, txn, *, phone, account_ref, description, audit_action):
    """
    Push the prompt and leave the transaction PENDING.

    Nothing here — in simulation or live — marks a payment paid. A payment is
    confirmed only when Safaricom says the money landed: the STK callback (then
    cross-checked with an STK status query), a C2B paybill confirmation, the
    reconciliation sweep, or an admin who has checked the paybill statement.

    Simulation used to "verify" instantly, so the app showed money as received
    that never existed. Simulation now stops at pending like the real thing,
    and the confirmation is played through the SAME callback handler.
    """
    simulation_mode = current_app.config.get("MPESA_SIMULATION_MODE", True)
    if simulation_mode:
        txn.payment_reference = f"ws_CO_SIM{txn.id:010d}"
        db.session.commit()
        record_audit(
            actor_user_id=int(get_jwt_identity()), landlord_id=landlord.id,
            action=f"{audit_action}_simulated", entity_type="billing", entity_id=txn.id,
            description=f"[SIMULATION] STK prompt for KES {txn.amount} to {phone} — pending confirmation.",
        )
        db.session.commit()
        return jsonify({
            "message": "Payment prompt sent (simulation). Waiting for M-Pesa to confirm.",
            "simulated": True,
            "checkout_request_id": txn.payment_reference,
            "transaction": txn.to_dict(),
        }), 200

    try:
        resp_data = daraja_service.stk_push(
            phone=phone, amount=txn.amount, account_ref=account_ref,
            description=description,
            callback_url=current_app.config.get("PLATFORM_DARAJA_STK_CALLBACK_URL", ""),
        )
    except DarajaError as e:
        current_app.logger.error(f"Platform STK Push API error: {e}")
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({"error": "M-Pesa could not send the prompt right now. Try again, "
                                 "or pay through the Paybill details below."}), 502

    if resp_data.get("ResponseCode") != "0":
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({
            "error":       resp_data.get("ResponseDescription", "STK Push rejected."),
            "daraja_code": resp_data.get("ResponseCode"),
        }), 400

    txn.payment_reference = resp_data.get("CheckoutRequestID", "")
    db.session.commit()
    record_audit(
        actor_user_id=int(get_jwt_identity()), landlord_id=landlord.id,
        action=f"{audit_action}_initiated", entity_type="billing", entity_id=txn.id,
        description=f"Platform STK Push of KES {txn.amount} sent to {phone} "
                    f"(CheckoutRequestID: {txn.payment_reference}).",
    )
    db.session.commit()
    return jsonify({
        "message":             "Check your phone and enter your M-Pesa PIN.",
        "simulated":           False,
        "checkout_request_id": txn.payment_reference,
        "transaction":         txn.to_dict(),
    }), 200


@billing_bp.route("/pay/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def pay_stk():
    """
    Pay what YOU choose. Body:
      { purpose: "subscription" | "sms", amount: int, phone,
        cycle?: monthly|quarterly|annual   (subscription: pay ahead for a period) }

    Subscription: any amount goes against the running balance — installments
    welcome; the account opens when the balance reaches zero.
    SMS: the amount buys floor(amount / price) credits (at least the minimum).
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Prompt sent; transaction pending until M-Pesa confirms.}
      400: {description: Invalid amount / phone.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}
    purpose     = data.get("purpose", "subscription")
    phone       = normalize_msisdn(data.get("phone") or landlord.mpesa_number)
    amount      = _money_or_400(data.get("amount"))

    if not phone:
        return jsonify({"error": "Enter the Safaricom number that will pay (07… or 01…)."}), 400
    if amount is None:
        return jsonify({"error": f"Enter an amount between KES {_MIN_PAYMENT} and KES {_MAX_PAYMENT:,}."}), 400

    if purpose == "sms":
        unit_price = _sms_unit_price(landlord)
        sms_count = int(amount / unit_price) if unit_price > 0 else 0
        if sms_count < _SMS_MIN_PURCHASE:
            return jsonify({"error": f"The minimum SMS purchase is {_SMS_MIN_PURCHASE} messages "
                                     f"(KES {(unit_price * _SMS_MIN_PURCHASE).quantize(Decimal('1'))})."}), 400
        txn = BillingTransaction(
            landlord_id=landlord_id, type=BillingTransactionType.sms_purchase.value, amount=amount,
            sms_count=sms_count, status=BillingTransactionStatus.pending.value,
            context_json={"sms_count": sms_count, "unit_price": str(unit_price), "applied": False,
                          "payer_phone": phone,
                          "shortcode": current_app.config.get("PLATFORM_DARAJA_SHORTCODE")},
        )
        db.session.add(txn)
        db.session.flush()
        return _send_stk(landlord, txn, phone=phone, account_ref=_sms_account_ref(landlord_id),
                         description="SMS Credits", audit_action="buy_sms_stk")

    if landlord.subscription is None:
        return jsonify({"error": "No subscription found for this account."}), 400
    cycle = data.get("cycle") or None
    if cycle and cycle not in billing_service.valid_cycles():
        return jsonify({"error": "Unknown billing cycle."}), 400
    txn = BillingTransaction(
        landlord_id=landlord_id, type=BillingTransactionType.subscription.value, amount=amount,
        status=BillingTransactionStatus.pending.value,
        context_json=billing_service.build_balance_context(amount, cycle=cycle, payer_phone=phone),
    )
    db.session.add(txn)
    db.session.flush()
    return _send_stk(landlord, txn, phone=phone, account_ref=_sub_account_ref(landlord_id),
                     description="Subscription", audit_action="pay_subscription_stk")


@billing_bp.route("/pay-subscription/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def pay_subscription_stk():
    """
    Pay a whole billing cycle (older app builds). Body: { billing_cycle, phone }.
    Same pipeline as POST /pay/stk with the cycle's full price as the amount.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Prompt sent; pending until M-Pesa confirms.}
    """
    landlord = db.session.get(Landlord, get_current_landlord_id())
    data = request.get_json(silent=True) or {}
    cycle = data.get("billing_cycle", SubscriptionPlan.monthly.value)
    if landlord.subscription is None:
        return jsonify({"error": "No subscription found for this account."}), 400
    try:
        amount_due, _, _ = billing_service.preview_subscription_cost(landlord.subscription, cycle,
                                                                     data.get("package_id"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "Package" in str(e) else 400
    phone = normalize_msisdn(data.get("phone") or landlord.mpesa_number)
    if not phone:
        return jsonify({"error": "A valid Safaricom phone number is required."}), 400
    txn = BillingTransaction(
        landlord_id=landlord.id, type=BillingTransactionType.subscription.value,
        amount=amount_due.quantize(Decimal("1")), status=BillingTransactionStatus.pending.value,
        context_json=billing_service.build_balance_context(amount_due, cycle=cycle, payer_phone=phone),
    )
    db.session.add(txn)
    db.session.flush()
    return _send_stk(landlord, txn, phone=phone, account_ref=_sub_account_ref(landlord.id),
                     description="Subscription", audit_action="pay_subscription_stk")


@billing_bp.route("/transactions/<int:txn_id>/simulate-confirmation", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def simulate_confirmation(txn_id):
    """
    SIMULATION ONLY: play Safaricom's STK callback for a pending transaction
    through the real webhook handler. Body: { result: "success" | "cancelled" }.
    Refused outright unless MPESA_SIMULATION_MODE is on and this is not production.
    ---
    tags: [Billing]
    responses:
      200: {description: Callback delivered.}
      404: {description: Not available.}
    """
    if not current_app.config.get("MPESA_SIMULATION_MODE", True) or \
            (current_app.config.get("APP_ENV") or "").lower() == "production" and \
            not current_app.config.get("ALLOW_SIMULATED_CONFIRMATION"):
        return jsonify({"error": "Not available."}), 404
    landlord_id = get_current_landlord_id()
    txn = BillingTransaction.query.filter_by(id=txn_id, landlord_id=landlord_id).first()
    if not txn or not (txn.payment_reference or "").startswith("ws_CO_SIM"):
        return jsonify({"error": "Not available."}), 404
    success = (request.get_json(silent=True) or {}).get("result", "success") == "success"
    payload = {"Body": {"stkCallback": {
        "MerchantRequestID": f"SIM-{txn.id}", "CheckoutRequestID": txn.payment_reference,
        "ResultCode": 0 if success else 1032,
        "ResultDesc": "The service request is processed successfully." if success else "Request cancelled by user",
        **({"CallbackMetadata": {"Item": [
            {"Name": "Amount", "Value": float(txn.amount)},
            {"Name": "MpesaReceiptNumber", "Value": f"SIM{txn.id:07d}"},
            {"Name": "PhoneNumber", "Value": (txn.context_json or {}).get("payer_phone")},
        ]}} if success else {}),
    }}}
    with current_app.test_request_context("/api/webhooks/daraja/billing-callback", method="POST", json=payload):
        from routes.webhook_routes import _billing_callback
        _billing_callback()
    db.session.refresh(txn)
    return jsonify({"transaction": txn.to_dict()}), 200


@billing_bp.route("/confirm-payment", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def confirm_paybill_payment():
    """
    "I paid through the Paybill" — look the M-Pesa code up. Body:
      { mpesa_code, purpose?: subscription|sms }

    Confirms ONLY a payment Safaricom has already reported to us (a C2B
    confirmation on the platform paybill). A code we have never seen is not
    trusted: it is filed as PENDING for an admin to check against the paybill
    statement, and the account does not change until they do.
    ---
    tags: [Billing]
    responses:
      200: {description: Found and applied (or already applied).}
      202: {description: Not seen yet — pending admin review.}
    """
    from models import PlatformC2BPayment
    from routes.webhook_routes import _apply_c2b_to_landlord

    landlord_id = get_current_landlord_id()
    landlord = db.session.get(Landlord, landlord_id)
    data = request.get_json(silent=True) or {}
    code = "".join(ch for ch in str(data.get("mpesa_code") or "").upper() if ch.isalnum())
    purpose = "sms_purchase" if data.get("purpose") == "sms" else "subscription"
    if not (8 <= len(code) <= 12):
        return jsonify({"error": "Enter the M-Pesa confirmation code from your SMS, e.g. SJK4XXXXXX."}), 400

    c2b = PlatformC2BPayment.query.filter_by(trans_id=code).first()
    if c2b is not None:
        if c2b.status == "matched":
            if c2b.landlord_id == landlord_id:
                txn = db.session.get(BillingTransaction, c2b.billing_transaction_id) if c2b.billing_transaction_id else None
                return jsonify({"message": "This payment is already confirmed on your account.",
                                "transaction": txn.to_dict() if txn else None}), 200
            return jsonify({"error": "This M-Pesa code has already been applied to another account. "
                                     "Contact Sahil Pay support if this is wrong."}), 409
        # Unmatched (wrong or missing account number). Auto-apply only when the
        # reference plainly points at THIS account; otherwise an admin decides,
        # so nobody can claim a stranger's payment by knowing its code.
        ref_digits = "".join(ch for ch in (c2b.bill_ref or "") if ch.isdigit())
        if ref_digits == str(landlord_id):
            txn = _apply_c2b_to_landlord(c2b, landlord, purpose)
            db.session.commit()
            if txn is not None:
                return jsonify({"message": "Payment found and confirmed.", "transaction": txn.to_dict()}), 200

    existing = BillingTransaction.query.filter_by(landlord_id=landlord_id, payment_reference=code).first()
    if existing is not None:
        return jsonify({"message": "We already have this code — it is waiting for review.",
                        "transaction": existing.to_dict()}), 202

    txn = BillingTransaction(
        landlord_id=landlord_id, type=purpose, amount=Decimal(str(c2b.amount)) if c2b else Decimal("0"),
        payment_reference=code, status=BillingTransactionStatus.pending.value,
        context_json={"mode": "claim", "applied": False, "claimed_code": code,
                      "seen_by_mpesa": c2b is not None},
    )
    db.session.add(txn)
    db.session.flush()
    record_audit(actor_user_id=int(get_jwt_identity()), landlord_id=landlord_id,
                 action="claim_paybill_payment", entity_type="billing", entity_id=txn.id,
                 description=f"Landlord reported paybill payment {code}; pending review.")
    from routes.webhook_routes import _notify_all_admins
    _notify_all_admins(category="platform_payment_claim", title="Paybill payment to check",
                       body=f"{landlord.company_name} says they paid with M-Pesa code {code}. "
                            "It has not been confirmed by M-Pesa yet — check the paybill statement.",
                       entity_type="billing", entity_id=txn.id)
    db.session.commit()
    return jsonify({
        "message": "We haven't received this payment from M-Pesa yet. It's saved as pending — "
                   "it will confirm automatically when M-Pesa reports it, or after our team checks it.",
        "transaction": txn.to_dict(),
    }), 202


@billing_bp.route("/transactions/<int:txn_id>/receipt", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def download_billing_receipt(txn_id):
    """
    The Sahil Pay receipt PDF, streamed. Only for a CONFIRMED payment.

    The old flow generated the PDF, stored it, and handed the browser a
    "/uploads/..." path — which the app then requested under /api, got a 404,
    and silently did nothing. The receipt is now rendered and streamed from
    this one authenticated endpoint.
    ---
    tags: [Billing]
    responses:
      200: {description: PDF.}
      409: {description: Payment not confirmed yet.}
    """
    from flask import Response
    from services.pdf_service import generate_tax_invoice_pdf

    landlord_id = get_current_landlord_id()
    txn = BillingTransaction.query.filter_by(id=txn_id, landlord_id=landlord_id).first()
    if not txn:
        return jsonify({"error": "Transaction not found."}), 404
    if not txn.is_verified or txn.status != BillingTransactionStatus.paid.value:
        return jsonify({"error": "A receipt is available once M-Pesa confirms the payment."}), 409
    landlord = db.session.get(Landlord, landlord_id)
    pdf = generate_tax_invoice_pdf(txn, landlord)
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="sahilpay-receipt-SP-RCPT-{txn.id:06d}.pdf"',
        "Cache-Control": "private, no-store",
    })


# ---------------------------------------------------------------------------
# GET /api/billing/transactions/<id>/status
# ---------------------------------------------------------------------------
@billing_bp.route("/transactions/<int:txn_id>/status", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def transaction_status(txn_id):
    """
    Poll a pending transaction's verification status — used by the client
    while waiting for the Daraja callback to land (E18 in
    AFFILIATE_PROGRAM_SPEC.md §10: STK push times out / user cancels).
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Transaction status.}
      404: {description: Transaction not found.}
    """
    landlord_id = get_current_landlord_id()
    txn = BillingTransaction.query.filter_by(id=txn_id, landlord_id=landlord_id).first()
    if not txn:
        return jsonify({"error": "Transaction not found."}), 404
    return jsonify({"transaction": txn.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/billing/buy-sms  (LEGACY — self-reported, unverified)
# ---------------------------------------------------------------------------
@billing_bp.route("/buy-sms", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def buy_sms():
    """
    LEGACY self-reported SMS credit purchase — the Daraja-outage escape
    hatch. Body: { sms_count: int (min 100), payment_reference: str }

    No longer credits sms_balance immediately (MPESA_INTEGRATION_SPEC.md D3)
    — creates a PENDING, UNVERIFIED BillingTransaction. An admin must verify
    it (POST /api/admin/billing-transactions/<id>/verify) before credits are
    added. Prefer POST /buy-sms/stk for real landlord usage.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      202: {description: Purchase recorded, pending admin verification.}
      400: {description: Below minimum or missing reference.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    sms_count         = int(data.get("sms_count", 0))
    payment_reference = (data.get("payment_reference") or "").strip()

    if sms_count < _SMS_MIN_PURCHASE:
        return jsonify({"error": f"Minimum SMS purchase is {_SMS_MIN_PURCHASE} credits."}), 400
    if not payment_reference:
        return jsonify({"error": "payment_reference is required."}), 400

    unit_price = _sms_unit_price(landlord)
    amount     = (unit_price * sms_count).quantize(Decimal("0.01"))

    txn = BillingTransaction(
        landlord_id       = landlord_id,
        type              = BillingTransactionType.sms_purchase.value,
        amount            = amount,
        sms_count         = sms_count,
        payment_reference = payment_reference,
        status            = BillingTransactionStatus.pending.value,
        context_json      = {"sms_count": sms_count, "unit_price": str(unit_price), "applied": False},
    )
    db.session.add(txn)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="buy_sms_self_reported",
        entity_type="billing",
        entity_id=txn.id,
        description=f"Self-reported purchase of {sms_count} SMS credits for KES {amount} — pending admin verification.",
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":     f"Purchase of {sms_count} SMS credits recorded. Credits apply once verified by an admin.",
        "transaction": txn.to_dict(),
        "sms_balance": landlord.sms_balance,
    }), 202


# ---------------------------------------------------------------------------
# POST /api/billing/buy-sms/stk  (older app builds)
# ---------------------------------------------------------------------------
@billing_bp.route("/buy-sms/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def buy_sms_stk():
    """
    Buy a number of SMS credits. Body: { sms_count (min 100), phone }.
    Same pending-until-confirmed pipeline as POST /pay/stk.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Prompt sent; pending until M-Pesa confirms.}
      400: {description: Below minimum or invalid phone.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}
    sms_count = int(data.get("sms_count", 0) or 0)
    phone     = normalize_msisdn(data.get("phone") or landlord.mpesa_number)
    if sms_count < _SMS_MIN_PURCHASE:
        return jsonify({"error": f"Minimum SMS purchase is {_SMS_MIN_PURCHASE} credits."}), 400
    if not phone:
        return jsonify({"error": "A valid Safaricom phone number is required."}), 400
    unit_price = _sms_unit_price(landlord)
    amount = (unit_price * sms_count).quantize(Decimal("1"), rounding="ROUND_CEILING")
    txn = BillingTransaction(
        landlord_id=landlord_id, type=BillingTransactionType.sms_purchase.value, amount=amount,
        sms_count=sms_count, status=BillingTransactionStatus.pending.value,
        context_json={"sms_count": sms_count, "unit_price": str(unit_price), "applied": False,
                      "payer_phone": phone, "shortcode": current_app.config.get("PLATFORM_DARAJA_SHORTCODE")},
    )
    db.session.add(txn)
    db.session.flush()
    return _send_stk(landlord, txn, phone=phone, account_ref=_sms_account_ref(landlord_id),
                     description="SMS Credits", audit_action="buy_sms_stk")


# ---------------------------------------------------------------------------
# GET /api/billing/transactions
# ---------------------------------------------------------------------------
@billing_bp.route("/transactions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def list_transactions():
    """
    Return all billing transactions (subscription payments + SMS purchases).
    Filters: ?type=, ?page=, ?per_page=
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated billing transactions.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = BillingTransaction.query.filter_by(landlord_id=landlord_id)
    if v := request.args.get("type"):
        query = query.filter(BillingTransaction.type == v)

    paginated = query.order_by(BillingTransaction.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "transactions": [t.to_dict() for t in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/billing/tax-invoice
# ---------------------------------------------------------------------------
@billing_bp.route("/tax-invoice", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def generate_tax_invoice():
    """
    Generate a platform-fee tax invoice (PDF) for a specific BillingTransaction.
    Body: { transaction_id: int }

    The PDF is generated via WeasyPrint, uploaded to S3, and the URL is stored
    on the BillingTransaction.tax_invoice_url field.  Returns the download URL.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Tax invoice URL.}
      404: {description: Transaction not found.}
    """
    landlord_id    = get_current_landlord_id()
    data           = request.get_json(silent=True) or {}
    transaction_id = data.get("transaction_id")

    if not transaction_id:
        return jsonify({"error": "transaction_id is required."}), 400

    txn = BillingTransaction.query.filter_by(
        id=transaction_id, landlord_id=landlord_id
    ).first()
    if not txn:
        return jsonify({"error": "Billing transaction not found."}), 404
    if not txn.is_verified:
        return jsonify({"error": "A receipt is available once M-Pesa confirms the payment."}), 409

    from services.pdf_service    import generate_tax_invoice_pdf
    from services.storage_service import upload_to_s3
    import io

    landlord  = db.session.get(Landlord, landlord_id)
    pdf_bytes = generate_tax_invoice_pdf(txn, landlord)

    file_url  = upload_to_s3(
        io.BytesIO(pdf_bytes),
        folder=f"tax-invoices/{landlord_id}",
        filename=f"tax_invoice_{txn.id}.pdf",
        content_type="application/pdf",
    )

    txn.tax_invoice_url = file_url
    db.session.commit()

    return jsonify({
        "message":         "Tax invoice generated.",
        "download_path":   f"/billing/transactions/{txn.id}/receipt",
        "tax_invoice_url": file_url,
        "transaction":     txn.to_dict(),
    }), 200
