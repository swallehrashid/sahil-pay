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

from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    Landlord, Subscription, BillingTransaction, Package,
    SubscriptionPlan, BillingTransactionType, BillingTransactionStatus,
    SubscriptionStatus,
)
from decorators import require_landlord_or_team, get_current_landlord_id
from services.audit_service import record_audit

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")

# NOTE: the 3-tier discount structure (monthly/quarterly/annual) is keyed by
# SubscriptionPlan, not BillingCycle — BillingCycle only has monthly/yearly
# (it's a different axis: how often the landlord is actually invoiced, not
# which commitment tier's discount applies). The variable name "billing_cycle"
# below is kept as the original route used it, but it's really selecting a
# SubscriptionPlan value.
_CYCLE_DISCOUNTS = {
    SubscriptionPlan.monthly.value:   Decimal("0.00"),
    SubscriptionPlan.quarterly.value: Decimal("10.00"),
    SubscriptionPlan.annual.value:    Decimal("15.00"),
}
_CYCLE_MONTHS = {
    SubscriptionPlan.monthly.value:   1,
    SubscriptionPlan.quarterly.value: 3,
    SubscriptionPlan.annual.value:   12,
}
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

    return jsonify({
        "subscription":  subscription.to_dict() if subscription else None,
        "package":       package.to_dict()      if package      else None,
        "sms_balance":   landlord.sms_balance,
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

    if billing_cycle not in _CYCLE_DISCOUNTS:
        return jsonify({"error": f"billing_cycle must be one of: {list(_CYCLE_DISCOUNTS.keys())}."}), 400
    if not payment_reference:
        return jsonify({"error": "payment_reference is required."}), 400

    subscription = landlord.subscription
    if not subscription:
        return jsonify({"error": "No subscription found for this account."}), 400

    # Optionally switch package
    if new_package_id:
        pkg = Package.query.filter_by(id=new_package_id, is_active=True).first()
        if not pkg:
            return jsonify({"error": "Package not found."}), 404
        landlord.package_id = new_package_id
        subscription.unit_count = (subscription.unit_count or 0)
        # Recalculate cost based on new package
        if pkg.price_per_unit:
            subscription.subscription_cost = pkg.price_per_unit * subscription.unit_count
        elif pkg.flat_price:
            subscription.subscription_cost = pkg.flat_price

    months        = _CYCLE_MONTHS[billing_cycle]
    discount      = _CYCLE_DISCOUNTS[billing_cycle]
    base_cost     = Decimal(str(subscription.subscription_cost or 0))
    discounted    = base_cost * months * (1 - discount / 100)
    amount_due    = discounted.quantize(Decimal("0.01"))

    # Update subscription
    subscription.billing_cycle     = billing_cycle
    subscription.discount_rate     = discount
    subscription.amount_due        = Decimal("0.00")
    subscription.status            = SubscriptionStatus.active.value
    subscription.next_billing_date = date.today() + relativedelta(months=months)

    if landlord.is_on_trial:
        landlord.is_on_trial = False

    txn = BillingTransaction(
        landlord_id       = landlord_id,
        type              = BillingTransactionType.subscription.value,
        amount            = amount_due,
        payment_reference = payment_reference,
        status            = BillingTransactionStatus.paid.value,
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

    amount = (_SMS_PRICE_PER_CREDIT * sms_count).quantize(Decimal("0.01"))

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