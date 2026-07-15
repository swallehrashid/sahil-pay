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
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import BillingTransaction, UserRole
from services import billing_service
from services.audit_service import record_audit

admin_billing_bp = Blueprint(
    "admin_billing", __name__, url_prefix="/api/admin/billing-transactions"
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
    Manually confirm a subscription payment arrived (bank/paybill statement
    reconciliation, or reviewing a legacy self-reported transaction). Flips
    is_verified=True and — if this transaction hasn't already activated its
    subscription (the STK-pending path) — applies that activation now, then
    fires affiliate commission accrual. Idempotent.
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
