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


def _sub_account_ref(landlord_id: int) -> str:
    return f"SUB-{landlord_id}"


def _sms_account_ref(landlord_id: int) -> str:
    return f"SMS-{landlord_id}"


def _sms_unit_price(landlord: Landlord) -> Decimal:
    """§9.3 reselling price: the admin-set custom rate for landlords who have
    connected their own SMS sender ID, else the default rate."""
    from services.sms_billing import load_rates
    settings = landlord.landlord_settings
    uses_own = bool(settings and settings.sms_connected and settings.sms_sender_id)
    rates    = load_rates()
    return rates["custom_price"] if uses_own else rates["default_price"]


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
        "sms_uses_own_sender": uses_own,
        "is_on_trial":   landlord.is_on_trial,
        "trial_ends_at": str(landlord.trial_ends_at) if landlord.trial_ends_at else None,
        "paybill": {
            "shortcode":              current_app.config.get("PLATFORM_DARAJA_SHORTCODE"),
            "subscription_account_ref": _sub_account_ref(landlord_id),
            "sms_account_ref":          _sms_account_ref(landlord_id),
        },
    }), 200


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
# POST /api/billing/pay-subscription/stk
# ---------------------------------------------------------------------------
@billing_bp.route("/pay-subscription/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def pay_subscription_stk():
    """
    Verified subscription payment — Daraja STK Push to Sahil's OWN paybill
    (distinct from the landlord's own shortcode used to collect rent).

    Body:
      { billing_cycle: 'monthly'|'quarterly'|'annual',
        phone: str,             -- landlord's phone to receive the STK prompt
        package_id?: int }      -- to switch package

    Unlike POST /pay-subscription, this endpoint does NOT activate the
    subscription immediately. It creates a PENDING, UNVERIFIED
    BillingTransaction and either:
      - simulates an instant successful callback (MPESA_SIMULATION_MODE=true,
        the default until Sahil's paybill credentials are configured), or
      - sends a real STK push and waits for
        POST /api/webhooks/daraja/billing-callback to confirm it.
    Only a verified transaction activates the subscription and is eligible
    for affiliate commission accrual (AFFILIATE_PROGRAM_SPEC.md §3).
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: STK Push sent, awaiting confirmation.}
      201: {description: Simulated payment verified immediately (simulation mode).}
      400: {description: Validation error or Daraja rejection.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    billing_cycle  = data.get("billing_cycle", SubscriptionPlan.monthly.value)
    new_package_id = data.get("package_id")
    phone          = normalize_msisdn(data.get("phone") or landlord.mpesa_number)

    if not phone:
        return jsonify({"error": "A valid Safaricom phone number is required."}), 400

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

    ctx = billing_service.build_subscription_context(
        billing_cycle, months, discount, new_package_id, applied=False
    )
    txn = BillingTransaction(
        landlord_id  = landlord_id,
        type         = BillingTransactionType.subscription.value,
        amount       = amount_due,
        status       = BillingTransactionStatus.pending.value,
        context_json = ctx,
    )
    db.session.add(txn)
    db.session.flush()

    simulation_mode = current_app.config.get("MPESA_SIMULATION_MODE", True)

    if simulation_mode:
        txn.payment_reference = f"SIM{txn.id:08d}"
        db.session.commit()
        billing_service.finalize_subscription_payment(txn)
        db.session.commit()

        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="pay_subscription_stk_simulated",
            entity_type="billing",
            entity_id=txn.id,
            description=(
                f"[SIMULATION] Subscription payment of KES {amount_due} verified "
                f"instantly ({billing_cycle}, {discount}% discount)."
            ),
            after_data=txn.to_dict(),
        )
        db.session.commit()

        return jsonify({
            "message":      "Subscription payment simulated and verified (simulation mode).",
            "simulated":    True,
            "transaction":  txn.to_dict(),
            "subscription": subscription.to_dict(),
        }), 201

    callback_url = current_app.config.get("PLATFORM_DARAJA_STK_CALLBACK_URL", "")

    try:
        resp_data = daraja_service.stk_push(
            phone=phone,
            amount=amount_due,
            account_ref=_sub_account_ref(landlord_id),
            description="Subscription",
            callback_url=callback_url,
        )
    except DarajaError as e:
        current_app.logger.error(f"Platform STK Push API error: {e}")
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({"error": "STK Push request failed. Try again."}), 502

    if resp_data.get("ResponseCode") != "0":
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({
            "error":       resp_data.get("ResponseDescription", "STK Push rejected."),
            "daraja_code": resp_data.get("ResponseCode"),
        }), 400

    checkout_request_id   = resp_data.get("CheckoutRequestID", "")
    txn.payment_reference = checkout_request_id
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="pay_subscription_stk_initiated",
        entity_type="billing",
        entity_id=txn.id,
        description=(
            f"Platform STK Push of KES {amount_due} sent to {phone} "
            f"(CheckoutRequestID: {checkout_request_id})."
        ),
    )
    db.session.commit()

    return jsonify({
        "message":             "STK Push sent. Awaiting confirmation.",
        "checkout_request_id": checkout_request_id,
        "transaction":         txn.to_dict(),
    }), 200


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
# POST /api/billing/buy-sms/stk
# ---------------------------------------------------------------------------
@billing_bp.route("/buy-sms/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "edit")
def buy_sms_stk():
    """
    Verified SMS credit purchase — Daraja STK Push to Sahil's OWN paybill.
    Body: { sms_count: int (min 100), phone: str }

    Mirrors POST /pay-subscription/stk: creates a PENDING, UNVERIFIED
    BillingTransaction and either simulates instant verification
    (MPESA_SIMULATION_MODE=true) or sends a real STK push, finalised by
    POST /api/webhooks/daraja/billing-callback. Only a verified transaction
    credits sms_balance.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      200: {description: STK Push sent, awaiting confirmation.}
      201: {description: Simulated payment verified immediately (simulation mode).}
      400: {description: Below minimum or invalid phone.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    sms_count = int(data.get("sms_count", 0))
    phone     = normalize_msisdn(data.get("phone") or landlord.mpesa_number)

    if sms_count < _SMS_MIN_PURCHASE:
        return jsonify({"error": f"Minimum SMS purchase is {_SMS_MIN_PURCHASE} credits."}), 400
    if not phone:
        return jsonify({"error": "A valid Safaricom phone number is required."}), 400

    unit_price = _sms_unit_price(landlord)
    amount     = (unit_price * sms_count).quantize(Decimal("0.01"))

    txn = BillingTransaction(
        landlord_id  = landlord_id,
        type         = BillingTransactionType.sms_purchase.value,
        amount       = amount,
        sms_count    = sms_count,
        status       = BillingTransactionStatus.pending.value,
        context_json = {"sms_count": sms_count, "unit_price": str(unit_price), "applied": False},
    )
    db.session.add(txn)
    db.session.flush()

    simulation_mode = current_app.config.get("MPESA_SIMULATION_MODE", True)

    if simulation_mode:
        txn.payment_reference = f"SIM{txn.id:08d}"
        db.session.commit()
        billing_service.finalize_sms_purchase(txn)
        db.session.commit()

        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="buy_sms_stk_simulated",
            entity_type="billing",
            entity_id=txn.id,
            description=f"[SIMULATION] {sms_count} SMS credits verified instantly for KES {amount}.",
            after_data=txn.to_dict(),
        )
        db.session.commit()

        return jsonify({
            "message":     f"{sms_count} SMS credits simulated and verified (simulation mode).",
            "simulated":   True,
            "transaction": txn.to_dict(),
            "sms_balance": landlord.sms_balance,
        }), 201

    callback_url = current_app.config.get("PLATFORM_DARAJA_STK_CALLBACK_URL", "")

    try:
        resp_data = daraja_service.stk_push(
            phone=phone,
            amount=amount,
            account_ref=_sms_account_ref(landlord_id),
            description="SMS Credits",
            callback_url=callback_url,
        )
    except DarajaError as e:
        current_app.logger.error(f"Platform STK Push API error (SMS): {e}")
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({"error": "STK Push request failed. Try again."}), 502

    if resp_data.get("ResponseCode") != "0":
        txn.status = BillingTransactionStatus.failed.value
        db.session.commit()
        return jsonify({
            "error":       resp_data.get("ResponseDescription", "STK Push rejected."),
            "daraja_code": resp_data.get("ResponseCode"),
        }), 400

    checkout_request_id   = resp_data.get("CheckoutRequestID", "")
    txn.payment_reference = checkout_request_id
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="buy_sms_stk_initiated",
        entity_type="billing",
        entity_id=txn.id,
        description=(
            f"Platform STK Push for {sms_count} SMS credits (KES {amount}) sent to {phone} "
            f"(CheckoutRequestID: {checkout_request_id})."
        ),
    )
    db.session.commit()

    return jsonify({
        "message":             "STK Push sent. Awaiting confirmation.",
        "checkout_request_id": checkout_request_id,
        "transaction":         txn.to_dict(),
    }), 200


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
        "tax_invoice_url": file_url,
        "transaction":     txn.to_dict(),
    }), 200
