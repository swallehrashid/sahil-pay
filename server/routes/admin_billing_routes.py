"""
routes/admin_billing_routes.py — Admin Billing Transaction Verification
Blueprint: admin_billing_bp  |  Prefix: /api/admin/billing-transactions

Verification is the load-bearing prerequisite of the affiliate program
(AFFILIATE_PROGRAM_SPEC.md §3): a subscription BillingTransaction only
becomes eligible for affiliate commission accrual once is_verified=True.
The STK path (billing_routes.py::pay_subscription_stk) verifies itself via
the Daraja callback; this blueprint is the admin's manual override for
payments that arrive outside STK (bank transfer, direct paybill deposit,
or a legacy self-reported pay_subscription transaction the admin has since
confirmed against the bank/paybill statement) — and the reversal path for
clawbacks (chargebacks, mistaken entries).

Also covers the Paybill payments queue (MPESA_INTEGRATION_SPEC.md §5.2):
direct-paybill (C2B) payments the webhook couldn't auto-match to a landlord's
pending subscription/SMS charge land in PlatformC2BPayment with
status='unmatched'; an admin resolves them here.
"""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    BillingTransaction, BillingTransactionType, BillingTransactionStatus,
    PlatformC2BPayment, Landlord, UserRole,
)
from services import billing_service
from services.audit_service import record_audit

admin_billing_bp = Blueprint(
    "admin_billing", __name__, url_prefix="/api/admin/billing-transactions"
)
admin_billing_c2b_bp = Blueprint(
    "admin_billing_c2b", __name__, url_prefix="/api/admin/billing/c2b-payments"
)


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _admin_actor_id() -> int:
    return int(get_jwt_identity())


# ---------------------------------------------------------------------------
# GET /api/admin/billing-transactions
# ---------------------------------------------------------------------------
@admin_billing_bp.route("", methods=["GET"])
@jwt_required()
def list_billing_transactions():
    """
    List subscription/SMS billing transactions across all landlords.
    Filters: ?type=, ?is_verified=true|false, ?landlord_id=, ?page=, ?per_page=
    ---
    tags: [Admin, Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated billing transactions.}
    """
    _require_admin()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = BillingTransaction.query
    if v := request.args.get("type"):
        query = query.filter(BillingTransaction.type == v)
    if v := request.args.get("landlord_id"):
        query = query.filter(BillingTransaction.landlord_id == int(v))
    if (v := request.args.get("is_verified")) is not None:
        query = query.filter(BillingTransaction.is_verified.is_(v.lower() == "true"))

    paginated = query.order_by(BillingTransaction.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for txn in paginated.items:
        d = txn.to_dict()
        d["landlord_name"] = txn.landlord.company_name if txn.landlord else None
        items.append(d)

    return jsonify({
        "transactions": items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/billing-transactions/<id>/verify
# ---------------------------------------------------------------------------
@admin_billing_bp.route("/<int:txn_id>/verify", methods=["POST"])
@jwt_required()
def verify_billing_transaction(txn_id):
    """
    Manually confirm a payment arrived (bank/paybill statement reconciliation,
    or reviewing a legacy self-reported transaction). Flips is_verified=True
    and — if this transaction hasn't already applied its deferred effect (the
    STK-pending path) — applies it now:
      - subscription: activates the subscription, fires affiliate commission
        accrual.
      - sms_purchase: credits landlords.sms_balance.
    Idempotent.
    ---
    tags: [Admin, Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Transaction verified.}
      404: {description: Transaction not found.}
      409: {description: Already verified.}
    """
    _require_admin()
    txn = db.session.get(BillingTransaction, txn_id)
    if not txn:
        return jsonify({"error": "Billing transaction not found."}), 404
    if txn.is_verified:
        return jsonify({"error": "This transaction is already verified.", "transaction": txn.to_dict()}), 409

    before = txn.to_dict()
    if txn.type == BillingTransactionType.sms_purchase.value:
        billing_service.finalize_sms_purchase(txn, admin_id=_admin_actor_id())
    else:
        billing_service.finalize_subscription_payment(txn, admin_id=_admin_actor_id())
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=txn.landlord_id,
        action="verify_billing_transaction",
        entity_type="billing",
        entity_id=txn.id,
        description=f"Admin manually verified billing transaction #{txn.id} (KES {txn.amount}).",
        before_data=before,
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({"message": "Transaction verified.", "transaction": txn.to_dict()}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/billing-transactions/<id>/reverse
# ---------------------------------------------------------------------------
@admin_billing_bp.route("/<int:txn_id>/reverse", methods=["POST"])
@jwt_required()
def reverse_billing_transaction(txn_id):
    """
    Reverse a verified transaction (chargeback, mistaken entry). Claws back
    any affiliate commission tied to it (D10/E6 in AFFILIATE_PROGRAM_SPEC.md
    §2/§10) — the affiliate's balance may go negative and nets against future
    commissions. Does not un-apply the landlord's subscription activation.
    Body: { reason: str }
    ---
    tags: [Admin, Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Transaction reversed.}
      400: {description: Not yet verified, or reason missing.}
      404: {description: Transaction not found.}
      409: {description: Already reversed.}
    """
    _require_admin()
    txn = db.session.get(BillingTransaction, txn_id)
    if not txn:
        return jsonify({"error": "Billing transaction not found."}), 404
    if not txn.is_verified:
        return jsonify({"error": "Only a verified transaction can be reversed."}), 400
    if txn.is_reversed:
        return jsonify({"error": "This transaction is already reversed.", "transaction": txn.to_dict()}), 409

    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "reason is required."}), 400

    before = txn.to_dict()
    billing_service.reverse_billing_transaction(txn, admin_id=_admin_actor_id(), reason=reason)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=txn.landlord_id,
        action="reverse_billing_transaction",
        entity_type="billing",
        entity_id=txn.id,
        description=f"Admin reversed billing transaction #{txn.id} (KES {txn.amount}): {reason}",
        before_data=before,
        after_data=txn.to_dict(),
    )
    db.session.commit()

    return jsonify({"message": "Transaction reversed.", "transaction": txn.to_dict()}), 200


# ===========================================================================
# Paybill payments queue (MPESA_INTEGRATION_SPEC.md §5.2)
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/admin/billing/c2b-payments
# ---------------------------------------------------------------------------
@admin_billing_c2b_bp.route("", methods=["GET"])
@jwt_required()
def list_c2b_payments():
    """
    List direct-paybill (C2B) payments received on the platform shortcode.
    Filters: ?status=matched|unmatched|resolved, ?page=, ?per_page=
    ---
    tags: [Admin, Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated C2B payments.}
    """
    _require_admin()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = PlatformC2BPayment.query
    if v := request.args.get("status"):
        query = query.filter(PlatformC2BPayment.status == v)

    paginated = query.order_by(PlatformC2BPayment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for c2b in paginated.items:
        d = c2b.to_dict()
        d["landlord_name"] = c2b.landlord.company_name if c2b.landlord else None
        items.append(d)

    unmatched_count = PlatformC2BPayment.query.filter_by(status="unmatched").count()

    return jsonify({
        "payments":        items,
        "total":           paginated.total,
        "pages":           paginated.pages,
        "current_page":    paginated.page,
        "unmatched_count": unmatched_count,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/billing/c2b-payments/<id>/resolve
# ---------------------------------------------------------------------------
@admin_billing_c2b_bp.route("/<int:c2b_id>/resolve", methods=["POST"])
@jwt_required()
def resolve_c2b_payment(c2b_id):
    """
    Manually resolve an unmatched paybill payment.
    Body: { landlord_id: int, apply_as: 'subscription'|'sms'|'ignore', note?: str }

    subscription: creates (if needed) and verifies a subscription
      BillingTransaction for the landlord's current cycle price, funded by
      this payment's amount.
    sms: computes sms_count = floor(amount / current unit price) and
      verifies an sms_purchase BillingTransaction for that many credits.
    ignore: marks the row resolved with no financial effect (e.g. a refund
      already issued outside the platform).
    ---
    tags: [Admin, Billing]
    security:
      - Bearer: []
    responses:
      200: {description: Payment resolved.}
      400: {description: Invalid apply_as or missing landlord_id.}
      404: {description: Payment or landlord not found.}
      409: {description: Already resolved.}
    """
    _require_admin()
    c2b = db.session.get(PlatformC2BPayment, c2b_id)
    if not c2b:
        return jsonify({"error": "C2B payment not found."}), 404
    if c2b.status == "resolved" or c2b.billing_transaction_id is not None:
        return jsonify({"error": "This payment has already been resolved.", "payment": c2b.to_dict()}), 409

    data        = request.get_json(silent=True) or {}
    landlord_id = data.get("landlord_id")
    apply_as    = (data.get("apply_as") or "").strip()
    note        = (data.get("note") or "").strip() or None

    if apply_as not in ("subscription", "sms", "ignore"):
        return jsonify({"error": "apply_as must be 'subscription', 'sms', or 'ignore'."}), 400

    before = c2b.to_dict()

    if apply_as == "ignore":
        c2b.status = "resolved"
        c2b.resolved_by_admin_id = _admin_actor_id()
        c2b.resolution_note = note
        db.session.commit()

        record_audit(
            actor_user_id=_admin_actor_id(), landlord_id=None,
            action="resolve_c2b_payment_ignore", entity_type="platform_c2b_payment", entity_id=c2b.id,
            description=f"Admin marked paybill payment #{c2b.id} (KES {c2b.amount}, receipt {c2b.trans_id}) as ignored.",
            before_data=before, after_data=c2b.to_dict(),
        )
        db.session.commit()
        return jsonify({"message": "Payment marked resolved (ignored).", "payment": c2b.to_dict()}), 200

    if not landlord_id:
        return jsonify({"error": "landlord_id is required."}), 400

    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    if apply_as == "subscription":
        subscription = landlord.subscription
        if not subscription:
            return jsonify({"error": "This landlord has no subscription."}), 400

        ctx = billing_service.build_subscription_context(
            subscription.billing_cycle or "monthly", 1, Decimal("0"), None, applied=False
        )
        txn = BillingTransaction(
            landlord_id=landlord.id, type=BillingTransactionType.subscription.value,
            amount=c2b.amount, payment_reference=c2b.trans_id,
            status=BillingTransactionStatus.pending.value, context_json=ctx,
        )
        db.session.add(txn)
        db.session.flush()
        billing_service.finalize_subscription_payment(txn, admin_id=_admin_actor_id())

    else:  # sms
        from services.sms_billing import load_rates
        settings   = landlord.landlord_settings
        uses_own   = bool(settings and settings.sms_connected and settings.sms_sender_id)
        rates      = load_rates()
        unit_price = rates["custom_price"] if uses_own else rates["default_price"]
        sms_count  = int(c2b.amount // unit_price) if unit_price else 0
        if sms_count < 1:
            return jsonify({"error": "Payment amount is too small to buy any SMS credits at the current rate."}), 400

        txn = BillingTransaction(
            landlord_id=landlord.id, type=BillingTransactionType.sms_purchase.value,
            amount=c2b.amount, sms_count=sms_count, payment_reference=c2b.trans_id,
            status=BillingTransactionStatus.pending.value,
            context_json={"sms_count": sms_count, "unit_price": str(unit_price), "applied": False},
        )
        db.session.add(txn)
        db.session.flush()
        billing_service.finalize_sms_purchase(txn, admin_id=_admin_actor_id())

    c2b.landlord_id = landlord.id
    c2b.billing_transaction_id = txn.id
    c2b.status = "resolved"
    c2b.resolved_by_admin_id = _admin_actor_id()
    c2b.resolution_note = note
    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(), landlord_id=landlord.id,
        action=f"resolve_c2b_payment_{apply_as}", entity_type="platform_c2b_payment", entity_id=c2b.id,
        description=(
            f"Admin resolved paybill payment #{c2b.id} (KES {c2b.amount}, receipt {c2b.trans_id}) "
            f"as {apply_as} for landlord #{landlord.id} ({landlord.company_name}); billing txn #{txn.id}."
        ),
        before_data=before, after_data=c2b.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message": "Payment resolved.",
        "payment": c2b.to_dict(),
        "transaction": txn.to_dict(),
    }), 200
