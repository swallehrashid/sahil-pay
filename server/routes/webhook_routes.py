"""
routes/webhook_routes.py — Provider Callbacks
Blueprint: webhook_bp  |  Prefix: /api/webhooks

Endpoints hit by external providers (Safaricom Daraja), never by the
frontend. No @jwt_required() — these are authenticated implicitly by
knowledge of the CheckoutRequestID Daraja itself generated, and by being
reachable only via the callback URL Sahil registered with Safaricom.

Daraja convention: ALWAYS return HTTP 200 with a small JSON body, even on
a business-logic failure — a non-200 makes Daraja retry the callback
indefinitely. Log real errors; never surface a 500 here.

  POST /mpesa/billing-callback — platform subscription STK confirmation.
    Confirming a transaction here is the ONLY non-simulated way a
    subscription BillingTransaction becomes is_verified=True, which is the
    sole gate on affiliate commission accrual — see
    services/billing_service.py::finalize_subscription_payment and
    AFFILIATE_PROGRAM_SPEC.md §3.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify

from extensions import db
from models import BillingTransaction, BillingTransactionStatus

webhook_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")

logger = logging.getLogger(__name__)


def _extract_callback_items(callback: dict) -> dict:
    items = {}
    for item in (callback.get("CallbackMetadata") or {}).get("Item", []):
        name = item.get("Name")
        if name:
            items[name] = item.get("Value")
    return items


# ---------------------------------------------------------------------------
# POST /api/webhooks/mpesa/billing-callback
# ---------------------------------------------------------------------------
@webhook_bp.route("/mpesa/billing-callback", methods=["POST"])
def mpesa_billing_callback():
    """
    Daraja STK callback for a platform subscription payment (landlord → Sahil's
    own paybill, triggered by POST /api/billing/pay-subscription/stk).

    Always returns 200 — Daraja retries on anything else.
    ---
    tags: [Webhooks]
    responses:
      200: {description: Acknowledged (regardless of business outcome).}
    """
    try:
        payload  = request.get_json(silent=True) or {}
        callback = (payload.get("Body") or {}).get("stkCallback") or {}
        checkout_request_id = callback.get("CheckoutRequestID")
        result_code          = callback.get("ResultCode")

        if not checkout_request_id:
            logger.warning("mpesa_billing_callback: no CheckoutRequestID in payload: %s", payload)
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

        txn = BillingTransaction.query.filter_by(
            payment_reference=checkout_request_id,
            status=BillingTransactionStatus.pending.value,
        ).first()

        if txn is None:
            # Either an unknown reference, or a duplicate callback for a
            # transaction we already finalised — idempotent no-op either way
            # (E10/E16 in AFFILIATE_PROGRAM_SPEC.md §10).
            logger.info("mpesa_billing_callback: no pending txn for %s (already finalised or unknown).",
                        checkout_request_id)
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

        if result_code == 0:
            items = _extract_callback_items(callback)
            receipt = items.get("MpesaReceiptNumber")
            if receipt:
                txn.payment_reference = receipt

            from services.billing_service import finalize_subscription_payment
            finalize_subscription_payment(txn)
            db.session.commit()
            logger.info("mpesa_billing_callback: txn %s verified (receipt %s).", txn.id, receipt)
        else:
            from services.billing_service import mark_subscription_payment_failed
            mark_subscription_payment_failed(txn)
            db.session.commit()
            logger.info("mpesa_billing_callback: txn %s failed (ResultCode %s: %s).",
                        txn.id, result_code, callback.get("ResultDesc"))

        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

    except Exception:
        # E25 — never a 500 here; log and acknowledge so Daraja doesn't retry-loop.
        db.session.rollback()
        logger.exception("mpesa_billing_callback: unhandled error processing payload.")
        return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
