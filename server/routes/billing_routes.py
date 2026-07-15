"""
routes/billing_routes.py — Platform Billing & Subscription
Blueprint: billing_bp  |  Prefix: /api/billing

Covers §4.21:
  GET /            — current plan summary
  POST /pay-subscription — pay or switch plan
  POST /buy-sms    — purchase SMS credits (min 100)
  GET /transactions — billing transaction history
  POST /tax-invoice — generate platform-fee tax invoice PDF

Billing cycle discounts (applied server-side):
  monthly  → 0%   (full price)
  3-month  → 10%  discount
  annual   → 15%  discount

SMS pricing: 1 credit = KES 1 (configurable).  The minimum purchase is 100 credits.
"""

import os
import re
import base64
from decimal import Decimal
from datetime import date, datetime

from flask import Blueprint, request, jsonify, Response, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Landlord, Subscription, BillingTransaction, Package,
    SubscriptionPlan, BillingTransactionType, BillingTransactionStatus,
    SubscriptionStatus,
)
from decorators import require_landlord_or_team, get_current_landlord_id
from services.audit_service import record_audit
from services import billing_service

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
_SMS_PRICE_PER_CREDIT = Decimal("1.00")
_SMS_MIN_PURCHASE     = 100


# ---------------------------------------------------------------------------
# GET /api/billing/
# ---------------------------------------------------------------------------
@billing_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def get_billing_summary():
    """
    Return the landlord's current billing plan details:
      - plan name, unit count, cost, billing cycle, discount
      - amount_due, next_billing_date, subscription status
      - sms_balance
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

    # §9.3 the live per-SMS resale price this landlord pays when buying credits:
    # custom rate if they've connected their own sender ID, else the default.
    from services.sms_billing import load_rates
    settings   = landlord.landlord_settings
    uses_own   = bool(settings and settings.at_connected and settings.at_sender_id)
    rates      = load_rates()
    sms_price  = float(rates["custom_price"] if uses_own else rates["default_price"])

    return jsonify({
        "subscription":  subscription.to_dict() if subscription else None,
        "package":       package.to_dict()      if package      else None,
        "sms_balance":   landlord.sms_balance,
        "sms_unit_price": sms_price,
        "sms_uses_own_sender": uses_own,
        "is_on_trial":   landlord.is_on_trial,
        "trial_ends_at": str(landlord.trial_ends_at) if landlord.trial_ends_at else None,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/billing/pay-subscription
# ---------------------------------------------------------------------------
@billing_bp.route("/pay-subscription", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def pay_subscription():
    """
    Pay the current subscription invoice or switch billing cycle.
    Body:
      { billing_cycle: 'monthly'|'quarterly'|'annual',
        payment_reference: str,
        package_id?: int   -- to switch package }

    Server-side discount calculation:
      monthly:   0%   of subscription_cost
      quarterly: 10%  off (3 months billed at 90%)
      annual:    15%  off (12 months billed at 85%)

    Updates Subscription.next_billing_date and status → active.
    Creates a BillingTransaction row of type 'subscription'.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      201: {description: Payment recorded, subscription activated.}
      400: {description: Invalid cycle or missing payment reference.}
    """
    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    data        = request.get_json(silent=True) or {}

    billing_cycle     = data.get("billing_cycle", SubscriptionPlan.monthly.value)
    payment_reference = data.get("payment_reference", "").strip()
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

    # NOTE: this is the self-reported flow — the subscription is activated
    # immediately for UX continuity, but the resulting BillingTransaction is
    # NOT verified (is_verified defaults False) and therefore can NEVER accrue
    # an affiliate commission on its own. An admin can later confirm the money
    # actually arrived via POST /api/admin/billing-transactions/<id>/verify,
    # which is the only thing that flips is_verified and fires accrual. See
    # AFFILIATE_PROGRAM_SPEC.md §3.
    ctx = billing_service.build_subscription_context(
        billing_cycle, months, discount, new_package_id, applied=True
    )
    billing_service.apply_subscription_activation(landlord, subscription, ctx)

    txn = BillingTransaction(
        landlord_id       = landlord_id,
        type              = BillingTransactionType.subscription.value,
        amount            = amount_due,
        payment_reference = payment_reference,
        status            = BillingTransactionStatus.paid.value,
        context_json      = ctx,
    )
    db.session.add(txn)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="pay_subscription",
        entity_type="billing",
        entity_id=txn.id,
        description=(
            f"Subscription payment of KES {amount_due} recorded "
            f"({billing_cycle}, {discount}% discount)."
        ),
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":      "Subscription payment recorded.",
        "transaction":  txn.to_dict(),
        "subscription": subscription.to_dict(),
    }), 201


def _daraja_access_token(consumer_key: str, consumer_secret: str, base_url: str) -> str:
    import requests as ext_requests
    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
    resp = ext_requests.get(
        f"{base_url}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _daraja_stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()


# ---------------------------------------------------------------------------
# POST /api/billing/pay-subscription/stk
# ---------------------------------------------------------------------------
@billing_bp.route("/pay-subscription/stk", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
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
        POST /api/webhooks/mpesa/billing-callback to confirm it.
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
    phone          = (data.get("phone") or landlord.mpesa_number or "").replace("+", "").replace(" ", "")
    if phone.startswith("07") or phone.startswith("01"):
        phone = "254" + phone[1:]

    if not re.match(r"^2547\d{8}$|^2541\d{8}$", phone):
        return jsonify({"error": f"Phone '{phone}' is not a valid Safaricom number."}), 400

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

    shortcode  = os.getenv("PLATFORM_DARAJA_SHORTCODE") or os.getenv("DARAJA_SHORTCODE", "")
    passkey    = os.getenv("PLATFORM_DARAJA_PASSKEY") or os.getenv("DARAJA_PASSKEY", "")
    consumer_key    = os.getenv("PLATFORM_DARAJA_CONSUMER_KEY") or os.getenv("DARAJA_CONSUMER_KEY", "")
    consumer_secret = os.getenv("PLATFORM_DARAJA_CONSUMER_SECRET") or os.getenv("DARAJA_CONSUMER_SECRET", "")
    base_url   = os.getenv("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")
    callback   = os.getenv("PLATFORM_DARAJA_STK_CALLBACK_URL") or os.getenv("DARAJA_STK_CALLBACK_URL", "")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    password  = _daraja_stk_password(shortcode, passkey, timestamp)

    try:
        token = _daraja_access_token(consumer_key, consumer_secret, base_url)
    except Exception as e:
        current_app.logger.error(f"Daraja token error: {e}")
        db.session.rollback()
        return jsonify({"error": "Could not obtain M-Pesa API token. Check credentials."}), 502

    stk_payload = {
        "BusinessShortCode": shortcode,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            int(float(amount_due)),
        "PartyA":            phone,
        "PartyB":            shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback,
        "AccountReference":  f"SUB-{landlord_id}"[:12],
        "TransactionDesc":   "Subscription"[:13],
    }

    try:
        import requests as ext_requests
        resp = ext_requests.post(
            f"{base_url}/mpesa/stkpush/v1/processrequest",
            json=stk_payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        resp_data = resp.json()
    except Exception as e:
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
# POST /api/billing/buy-sms
# ---------------------------------------------------------------------------
@billing_bp.route("/buy-sms", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
def buy_sms():
    """
    Purchase SMS credits.
    Body: { sms_count: int (min 100), payment_reference: str }

    Amount = sms_count × KES 1 (per credit).
    Immediately increments landlords.sms_balance.
    Creates a BillingTransaction row of type 'sms_purchase'.
    ---
    tags: [Billing]
    security:
      - Bearer: []
    responses:
      201: {description: SMS credits purchased.}
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

    # §9.3 reselling price: the admin-set custom rate for landlords who have
    # connected their own Africa's Talking sender ID, else the default rate.
    from services.sms_billing import load_rates
    settings   = landlord.landlord_settings
    uses_own   = bool(settings and settings.at_connected and settings.at_sender_id)
    rates      = load_rates()
    unit_price = rates["custom_price"] if uses_own else rates["default_price"]
    amount     = (unit_price * sms_count).quantize(Decimal("0.01"))

    landlord.sms_balance += sms_count

    txn = BillingTransaction(
        landlord_id       = landlord_id,
        type              = BillingTransactionType.sms_purchase.value,
        amount            = amount,
        sms_count         = sms_count,
        payment_reference = payment_reference,
        status            = BillingTransactionStatus.paid.value,
    )
    db.session.add(txn)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="buy_sms",
        entity_type="billing",
        entity_id=txn.id,
        description=f"{sms_count} SMS credits purchased for KES {amount}.",
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":        f"{sms_count} SMS credits added.",
        "transaction":    txn.to_dict(),
        "sms_balance":    landlord.sms_balance,
    }), 201


# ---------------------------------------------------------------------------
# GET /api/billing/transactions
# ---------------------------------------------------------------------------
@billing_bp.route("/transactions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
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