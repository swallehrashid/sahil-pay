"""
routes/webhook_routes.py — Provider Callbacks
Blueprint: webhook_bp  |  Prefix: /api/webhooks

Endpoints hit by external providers (Safaricom Daraja), never by the
frontend. No @jwt_required() — these are authenticated implicitly by
knowledge of identifiers Daraja itself generated (CheckoutRequestID,
OriginatorConversationID), by an IP allowlist (DARAJA_ALLOWED_IPS, see
_daraja_ip_allowed below), and by being reachable only via the callback URLs
Sahil registered with Safaricom.

Daraja convention: ALWAYS return HTTP 200 with a small JSON body, even on
a business-logic failure — a non-200 makes Daraja retry the callback
indefinitely. Log real errors; never surface a 500 here.

Safaricom REJECTS any callback URL containing the word "mpesa" or
"safaricom" (discovered registering C2B URLs for production paybill 4326127)
— every route here lives under /api/webhooks/daraja/..., never
/api/webhooks/mpesa/.... The original /api/webhooks/mpesa/billing-callback
path is kept registered too (pointing at the same handler) only because it
may already be referenced somewhere; new configuration must use the
/daraja/ path.

See MPESA_INTEGRATION_SPEC.md for the full architecture:
  POST /daraja/billing-callback   — platform subscription/SMS STK confirmation.
    Confirming a transaction here is one of the ways a BillingTransaction
    becomes is_verified=True — the sole gate on subscription activation, SMS
    credit issuance, and (for subscriptions) affiliate commission accrual.
    See services/billing_service.py::finalize_subscription_payment /
    finalize_sms_purchase and AFFILIATE_PROGRAM_SPEC.md §3.
  POST /daraja/c2b/validation      — optional pre-check for a direct paybill
    payment (only fires if External Validation is enabled on the paybill).
  POST /daraja/c2b/confirmation    — direct paybill payment landed; routed by
    BillRefNumber (SUB-{landlord_id} / SMS-{landlord_id}) to the same
    finalize_* functions as the STK path.
  POST /daraja/b2c/result          — affiliate payout (B2C) outcome.
  POST /daraja/b2c/timeout         — affiliate payout (B2C) timed out.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, current_app

from extensions import db, limiter
from models import (
    BillingTransaction, BillingTransactionStatus, BillingTransactionType,
    PlatformC2BPayment, DarajaCallbackLog, AffiliateWithdrawal,
    Landlord, User, UserRole,
)

webhook_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")

logger = logging.getLogger(__name__)

_MAX_PAYLOAD_BYTES = 32 * 1024


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Safaricom's published Daraja callback source addresses. Used when the app is
# LIVE (simulation off) and DARAJA_ALLOWED_IPS was left empty — an empty list
# used to mean "accept anyone", so a forged "payment received" POST from any
# machine on the internet would have been processed. Override with
# DARAJA_ALLOWED_IPS if Safaricom publishes new ranges.
SAFARICOM_CALLBACK_IPS = (
    "196.201.214.200", "196.201.214.206", "196.201.213.114", "196.201.214.207",
    "196.201.214.208", "196.201.213.44", "196.201.212.127", "196.201.212.138",
    "196.201.212.129", "196.201.212.136", "196.201.212.74", "196.201.212.69",
)


def _caller_ip() -> str:
    """
    The address that actually connected to our edge.

    X-Forwarded-For is "client, proxy1, proxy2…" and each proxy APPENDS. Anything
    to the left of what our own proxies added was written by the caller and can
    be forged. With TRUSTED_PROXY_HOPS proxies we control (nginx = 1; Cloudflare
    + nginx = 2), the real client is the entry that many places from the right.
    Reading the FIRST entry — as this used to — let anyone claim to be Safaricom
    by sending the header themselves.
    """
    if not current_app.config.get("TRUST_PROXY"):
        return request.remote_addr or ""
    cf = request.headers.get("CF-Connecting-IP")
    hops = int(current_app.config.get("TRUSTED_PROXY_HOPS", 1) or 1)
    chain = [p.strip() for p in (request.headers.get("X-Forwarded-For") or "").split(",") if p.strip()]
    if cf and hops >= 2:
        return cf.strip()
    if len(chain) >= hops:
        return chain[-hops]
    return request.remote_addr or ""


def _daraja_ip_allowed() -> bool:
    """
    True if the caller is an allowed Daraja source.

    Configured DARAJA_ALLOWED_IPS wins. Empty + simulation (dev/test) = allow all.
    Empty + LIVE = Safaricom's published addresses only.
    """
    configured = [r.strip() for r in (current_app.config.get("DARAJA_ALLOWED_IPS") or "").split(",") if r.strip()]
    if configured:
        allowed_ranges = configured
    elif current_app.config.get("MPESA_SIMULATION_MODE", True):
        return True
    else:
        allowed_ranges = list(SAFARICOM_CALLBACK_IPS)

    try:
        ip = ipaddress.ip_address(_caller_ip())
    except ValueError:
        return False

    for cidr in allowed_ranges:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _log_callback(kind: str, payload: dict) -> DarajaCallbackLog:
    raw = json.dumps(payload)
    if len(raw.encode()) > _MAX_PAYLOAD_BYTES:
        payload = {"_truncated": True, "_original_size": len(raw)}
    entry = DarajaCallbackLog(
        kind=kind,
        remote_ip=_caller_ip()[:45] or request.remote_addr,
        payload_json=payload,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def _notify_all_admins(category: str, title: str, body: str, **kwargs) -> None:
    from services.notification_service import notify_many
    admin_user_ids = [
        uid for (uid,) in db.session.query(User.id).filter(User.role == UserRole.system_admin.value).all()
    ]
    if admin_user_ids:
        notify_many(admin_user_ids, category=category, title=title, body=body, **kwargs)


def _extract_callback_items(callback: dict) -> dict:
    items = {}
    for item in (callback.get("CallbackMetadata") or {}).get("Item", []):
        name = item.get("Name")
        if name:
            items[name] = item.get("Value")
    return items


def _accepted(log_entry: DarajaCallbackLog | None = None, error: str | None = None):
    """The standard Daraja-happy 200 response. Marks the log entry processed
    (or stamps the error) and commits — always the last thing a handler does."""
    if log_entry is not None:
        log_entry.processed = error is None
        log_entry.error = error
        db.session.commit()
    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200


def _finalize_billing_transaction(txn: BillingTransaction):
    """Dispatch a verified BillingTransaction to the right finalizer by type."""
    from services import billing_service
    if txn.type == BillingTransactionType.sms_purchase.value:
        billing_service.finalize_sms_purchase(txn)
    else:
        billing_service.finalize_subscription_payment(txn)


# ---------------------------------------------------------------------------
# POST /api/webhooks/daraja/billing-callback  (also mounted at the legacy
# /api/webhooks/mpesa/billing-callback path — see module docstring)
# ---------------------------------------------------------------------------
def _billing_callback():
    """
    Daraja STK callback for a platform subscription OR SMS-credit payment
    (landlord → Sahil's own paybill, triggered by POST
    /api/billing/pay-subscription/stk or POST /api/billing/buy-sms/stk).

    Always returns 200 — Daraja retries on anything else.
    ---
    tags: [Webhooks]
    responses:
      200: {description: Acknowledged (regardless of business outcome).}
    """
    payload = request.get_json(silent=True) or {}
    log_entry = _log_callback("stk", payload)

    if not _daraja_ip_allowed():
        logger.warning("billing_callback: rejected IP %s (not an allowed Daraja source).", _caller_ip())
        return _accepted(log_entry, error="IP not in allowlist; not processed.")

    try:
        callback = (payload.get("Body") or {}).get("stkCallback") or {}
        checkout_request_id = callback.get("CheckoutRequestID")
        result_code          = callback.get("ResultCode")

        if not checkout_request_id:
            logger.warning("billing_callback: no CheckoutRequestID in payload: %s", payload)
            return _accepted(log_entry, error="No CheckoutRequestID in payload.")

        txn = BillingTransaction.query.filter_by(
            payment_reference=checkout_request_id,
            status=BillingTransactionStatus.pending.value,
        ).first()

        if txn is None:
            # Either an unknown reference, or a duplicate callback for a
            # transaction we already finalised — idempotent no-op either way
            # (E10/E16 in AFFILIATE_PROGRAM_SPEC.md §10).
            logger.info("billing_callback: no pending txn for %s (already finalised or unknown).",
                        checkout_request_id)
            return _accepted(log_entry)

        if result_code == 0:
            items   = _extract_callback_items(callback)
            receipt = items.get("MpesaReceiptNumber")
            paid_amount = items.get("Amount")

            # Amount must match to the shilling — never trust the callback
            # blindly (MPESA_INTEGRATION_SPEC.md §10). A mismatch is flagged
            # for admin review instead of silently activating anything.
            try:
                amounts_match = paid_amount is not None and Decimal(str(paid_amount)) == Decimal(str(txn.amount))
            except (InvalidOperation, TypeError):
                amounts_match = False

            if not amounts_match:
                logger.error(
                    "billing_callback: AMOUNT MISMATCH txn %s expected %s got %s (receipt %s).",
                    txn.id, txn.amount, paid_amount, receipt,
                )
                _notify_all_admins(
                    category="billing_amount_mismatch",
                    title="M-Pesa amount mismatch",
                    body=(
                        f"Billing transaction #{txn.id} expected KES {txn.amount} but the Daraja "
                        f"callback reported KES {paid_amount} (receipt {receipt}). Not finalised — review manually."
                    ),
                    entity_type="billing", entity_id=txn.id,
                )
                return _accepted(log_entry, error=f"Amount mismatch: expected {txn.amount}, got {paid_amount}.")

            # SECOND, INDEPENDENT CONFIRMATION. A callback is an inbound POST; the
            # STK status query is us asking Safaricom over our authenticated API
            # connection. Money is marked received only when both agree. If the
            # query cannot be made right now the payment stays PENDING — the
            # reconciliation sweep asks again every five minutes.
            if not current_app.config.get("MPESA_SIMULATION_MODE", True):
                from services import daraja_service
                from services.daraja_service import DarajaError
                try:
                    query = daraja_service.stk_query(checkout_request_id)
                    confirmed = str(query.get("ResultCode")) == "0"
                except DarajaError:
                    logger.warning("billing_callback: stk_query failed for %s — left pending.", checkout_request_id)
                    return _accepted(log_entry, error="Could not cross-check with Safaricom; left pending.")
                if not confirmed:
                    logger.error("billing_callback: callback said paid but stk_query says %s for txn %s.",
                                 query.get("ResultCode"), txn.id)
                    _notify_all_admins(
                        category="billing_callback_disputed", title="M-Pesa callback not confirmed",
                        body=(f"Billing transaction #{txn.id}: a success callback arrived but Safaricom's "
                              f"status query returned {query.get('ResultCode')}. Not finalised."),
                        entity_type="billing", entity_id=txn.id,
                    )
                    return _accepted(log_entry, error="Callback not confirmed by stk_query.")

            if receipt:
                txn.payment_reference = receipt
            ctx = dict(txn.context_json or {})
            ctx["checkout_request_id"] = checkout_request_id
            if items.get("PhoneNumber"):
                ctx["payer_phone"] = str(items.get("PhoneNumber"))
            txn.context_json = ctx

            _finalize_billing_transaction(txn)
            db.session.commit()
            logger.info("billing_callback: txn %s verified (receipt %s).", txn.id, receipt)
            _notify_landlord_paid(txn)
        else:
            from services.billing_service import mark_subscription_payment_failed
            mark_subscription_payment_failed(txn)
            db.session.commit()
            logger.info("billing_callback: txn %s failed (ResultCode %s: %s).",
                        txn.id, result_code, callback.get("ResultDesc"))

        return _accepted(log_entry)

    except Exception:
        # E25 — never a 500 here; log and acknowledge so Daraja doesn't retry-loop.
        db.session.rollback()
        logger.exception("billing_callback: unhandled error processing payload.")
        return _accepted(error="Unhandled exception — see server logs.")


webhook_bp.add_url_rule("/daraja/billing-callback", view_func=_billing_callback,
                         methods=["POST"], endpoint="daraja_billing_callback")
webhook_bp.add_url_rule("/mpesa/billing-callback", view_func=_billing_callback,
                         methods=["POST"], endpoint="mpesa_billing_callback_legacy")


# ---------------------------------------------------------------------------
# POST /api/webhooks/daraja/c2b/validation
# ---------------------------------------------------------------------------
@webhook_bp.route("/daraja/c2b/validation", methods=["POST"])
@limiter.limit("60 per minute")
def c2b_validation():
    """
    Optional pre-check for a direct-paybill payment — only fires if External
    Validation is enabled on the platform paybill (org portal setting). We
    never bounce money here: accept everything, even payments we can't
    immediately identify (they land in the unmatched admin queue via the
    confirmation callback instead).
    ---
    tags: [Webhooks]
    responses:
      200: {description: Always accepted.}
    """
    payload = request.get_json(silent=True) or {}
    log_entry = _log_callback("c2b_validation", payload)

    if not _daraja_ip_allowed():
        logger.warning("c2b_validation: rejected IP %s.", request.remote_addr)
        return _accepted(log_entry, error="IP not in allowlist; not processed.")

    return _accepted(log_entry)


# ---------------------------------------------------------------------------
# POST /api/webhooks/daraja/c2b/confirmation
# ---------------------------------------------------------------------------
@webhook_bp.route("/daraja/c2b/confirmation", methods=["POST"])
@limiter.limit("60 per minute")
def c2b_confirmation():
    """
    A direct-paybill (C2B) payment landed on the platform shortcode
    (subscriptions/SMS credits only — tenant rent never touches this
    shortcode, MPESA_INTEGRATION_SPEC.md D1). Routed by BillRefNumber:
      SUB-{landlord_id} -> subscription payment
      SMS-{landlord_id} -> SMS credit purchase
      anything else / unknown landlord -> unmatched admin queue
    ---
    tags: [Webhooks]
    responses:
      200: {description: Always accepted.}
    """
    payload = request.get_json(silent=True) or {}
    log_entry = _log_callback("c2b_confirmation", payload)

    if not _daraja_ip_allowed():
        logger.warning("c2b_confirmation: rejected IP %s.", request.remote_addr)
        return _accepted(log_entry, error="IP not in allowlist; not processed.")

    try:
        trans_id     = (payload.get("TransID") or "").strip()
        trans_amount = payload.get("TransAmount")
        bill_ref     = (payload.get("BillRefNumber") or "").strip()
        msisdn       = payload.get("MSISDN")
        trans_time   = payload.get("TransTime")
        payer_name   = " ".join(filter(None, [
            payload.get("FirstName"), payload.get("MiddleName"), payload.get("LastName"),
        ])) or None

        if not trans_id:
            logger.warning("c2b_confirmation: no TransID in payload: %s", payload)
            return _accepted(log_entry, error="No TransID in payload.")

        # Idempotency: a duplicate confirmation for the same M-Pesa receipt
        # is a safe no-op.
        if PlatformC2BPayment.query.filter_by(trans_id=trans_id).first() is not None:
            logger.info("c2b_confirmation: duplicate TransID %s, ignoring.", trans_id)
            return _accepted(log_entry)

        try:
            amount = Decimal(str(trans_amount))
        except (InvalidOperation, TypeError):
            amount = Decimal("0")

        c2b = PlatformC2BPayment(
            trans_id=trans_id, amount=amount, bill_ref=bill_ref,
            msisdn=str(msisdn) if msisdn is not None else None,
            payer_name=payer_name, trans_time=str(trans_time) if trans_time is not None else None,
        )
        db.session.add(c2b)
        db.session.flush()

        landlord_id, kind = _parse_bill_ref(bill_ref)
        landlord = None
        if landlord_id is not None:
            landlord = db.session.get(Landlord, landlord_id)

        if landlord is None or kind is None:
            c2b.status = "unmatched"
            db.session.commit()
            logger.warning("c2b_confirmation: unmatched BillRefNumber '%s' (TransID %s).", bill_ref, trans_id)
            _notify_all_admins(
                category="platform_payment_unmatched",
                title="Unmatched paybill payment",
                body=f"KES {amount} received (ref '{bill_ref}', receipt {trans_id}) — could not match to a landlord.",
                entity_type="platform_c2b_payment", entity_id=c2b.id,
            )
            return _accepted(log_entry)

        matched_txn = _apply_c2b_to_landlord(c2b, landlord, kind)
        if matched_txn is None:
            c2b.status = "unmatched"
            db.session.commit()
            logger.warning("c2b_confirmation: could not apply KES %s for landlord %s kind %s.",
                           amount, landlord.id, kind)
            _notify_all_admins(
                category="platform_payment_unmatched",
                title="Unmatched paybill payment",
                body=(
                    f"KES {amount} received from landlord #{landlord.id} ({landlord.company_name}) "
                    f"(ref '{bill_ref}', receipt {trans_id}) — could not be applied automatically."
                ),
                entity_type="platform_c2b_payment", entity_id=c2b.id,
            )
            return _accepted(log_entry)

        db.session.commit()
        logger.info("c2b_confirmation: txn %s verified via C2B (receipt %s).", matched_txn.id, trans_id)
        _notify_landlord_paid(matched_txn)
        return _accepted(log_entry)

    except Exception:
        db.session.rollback()
        logger.exception("c2b_confirmation: unhandled error processing payload.")
        return _accepted(error="Unhandled exception — see server logs.")


def _apply_c2b_to_landlord(c2b, landlord, kind: str):
    """
    Apply a paybill payment Safaricom reported (C2B) to a landlord. Returns the
    verified BillingTransaction, or None if it cannot be applied.

    Subscription: ANY amount is an installment against the balance — a pending
    STK transaction for exactly this amount is reused so it does not linger.
    SMS: a pending purchase for exactly this amount, else floor(amount / price)
    credits.
    """
    from services import billing_service

    amount = Decimal(str(c2b.amount or 0))
    if amount <= 0:
        return None
    txn_type = (BillingTransactionType.subscription.value if kind == "subscription"
                else BillingTransactionType.sms_purchase.value)

    txn = (
        BillingTransaction.query
        .filter_by(landlord_id=landlord.id, type=txn_type, status=BillingTransactionStatus.pending.value)
        .filter(BillingTransaction.amount == amount, BillingTransaction.is_verified.is_(False))
        .order_by(BillingTransaction.created_at.desc())
        .first()
    )
    if txn is None and kind == "subscription":
        if landlord.subscription is None:
            return None
        txn = BillingTransaction(
            landlord_id=landlord.id, type=txn_type, amount=amount,
            status=BillingTransactionStatus.pending.value,
            context_json=billing_service.build_balance_context(amount, cycle=None, payer_phone=c2b.msisdn),
        )
        db.session.add(txn)
        db.session.flush()
    elif txn is None:
        from services.sms_billing import effective_price_per_sms
        price = effective_price_per_sms(landlord.landlord_settings, landlord=landlord)
        credits = int(amount / price) if price and price > 0 else 0
        if credits < 1:
            return None
        txn = BillingTransaction(
            landlord_id=landlord.id, type=txn_type, amount=amount, sms_count=credits,
            status=BillingTransactionStatus.pending.value,
            context_json={"sms_count": credits, "unit_price": str(price), "applied": False,
                          "payer_phone": c2b.msisdn},
        )
        db.session.add(txn)
        db.session.flush()

    ctx = dict(txn.context_json or {})
    ctx.setdefault("payer_phone", c2b.msisdn)
    ctx["paid_via"] = "paybill"
    txn.context_json = ctx
    txn.payment_reference = c2b.trans_id
    _finalize_billing_transaction(txn)
    c2b.landlord_id = landlord.id
    c2b.billing_transaction_id = txn.id
    c2b.status = "matched"
    return txn


def _notify_landlord_paid(txn) -> None:
    """Tell the landlord their payment is confirmed (bell). Never raises."""
    try:
        from services.notification_service import notify
        landlord = txn.landlord
        if landlord is None or landlord.user_id is None:
            return
        what = "SMS credits" if txn.type == BillingTransactionType.sms_purchase.value else "subscription"
        notify(recipient_user_id=landlord.user_id, category="billing",
               title="Payment confirmed",
               body=f"KES {txn.amount} for {what} was received (M-Pesa {txn.payment_reference}). "
                    "Your receipt is ready in Settings → Billing.",
               landlord_id=landlord.id, link="/landlord/settings/billing",
               entity_type="billing", entity_id=txn.id)
        db.session.commit()
    except Exception:                                  # noqa: BLE001
        db.session.rollback()


def _parse_bill_ref(bill_ref: str):
    """Return (landlord_id, kind) from 'SUB-{id}' / 'SMS-{id}', else (None, None)."""
    ref = (bill_ref or "").strip().upper()
    for prefix, kind in (("SUB-", "subscription"), ("SMS-", "sms_purchase")):
        if ref.startswith(prefix):
            suffix = ref[len(prefix):]
            if suffix.isdigit():
                return int(suffix), kind
    return None, None


# ---------------------------------------------------------------------------
# POST /api/webhooks/daraja/b2c/result
# ---------------------------------------------------------------------------
@webhook_bp.route("/daraja/b2c/result", methods=["POST"])
@limiter.limit("60 per minute")
def b2c_result():
    """
    Outcome of an affiliate payout sent via Daraja B2C
    (POST /api/admin/affiliates/withdrawals/<id>/pay-b2c).
    ---
    tags: [Webhooks]
    responses:
      200: {description: Always accepted.}
    """
    payload = request.get_json(silent=True) or {}
    log_entry = _log_callback("b2c_result", payload)

    if not _daraja_ip_allowed():
        logger.warning("b2c_result: rejected IP %s.", request.remote_addr)
        return _accepted(log_entry, error="IP not in allowlist; not processed.")

    try:
        result = (payload.get("Result") or {})
        originator_id = result.get("OriginatorConversationID")
        result_code   = result.get("ResultCode")
        result_desc   = result.get("ResultDesc")

        if not originator_id:
            logger.warning("b2c_result: no OriginatorConversationID in payload: %s", payload)
            return _accepted(log_entry, error="No OriginatorConversationID in payload.")

        withdrawal = AffiliateWithdrawal.query.filter_by(b2c_originator_id=originator_id).first()
        if withdrawal is None:
            logger.warning("b2c_result: unknown OriginatorConversationID %s.", originator_id)
            return _accepted(log_entry, error="Unknown OriginatorConversationID.")

        # Idempotent: a duplicate result callback is a safe no-op.
        if withdrawal.b2c_status in ("result_received",) or withdrawal.status == "paid":
            logger.info("b2c_result: withdrawal %s already finalised, ignoring duplicate.", withdrawal.id)
            return _accepted(log_entry)

        withdrawal.b2c_result_code = result_code
        withdrawal.b2c_result_desc = result_desc

        if result_code == 0:
            params = {p.get("Key"): p.get("Value") for p in (result.get("ResultParameters") or {}).get("ResultParameter", [])}
            receipt = params.get("TransactionReceipt") or originator_id

            from services import affiliate_service as svc
            svc.pay_withdrawal(withdrawal, admin_id=withdrawal.processed_by_admin_id, mpesa_reference=str(receipt))
            withdrawal.b2c_status = "result_received"
            db.session.commit()
            logger.info("b2c_result: withdrawal %s paid via B2C (receipt %s).", withdrawal.id, receipt)
        else:
            withdrawal.b2c_status = "failed"
            db.session.commit()
            logger.error("b2c_result: withdrawal %s B2C failed (code %s: %s).", withdrawal.id, result_code, result_desc)
            _notify_all_admins(
                category="affiliate_payout_failed",
                title="Affiliate payout failed",
                body=(
                    f"B2C payout for withdrawal #{withdrawal.id} failed (code {result_code}: {result_desc}). "
                    f"Retry via B2C or pay manually."
                ),
                entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
            )

        return _accepted(log_entry)

    except Exception:
        db.session.rollback()
        logger.exception("b2c_result: unhandled error processing payload.")
        return _accepted(error="Unhandled exception — see server logs.")


# ---------------------------------------------------------------------------
# POST /api/webhooks/daraja/b2c/timeout
# ---------------------------------------------------------------------------
@webhook_bp.route("/daraja/b2c/timeout", methods=["POST"])
@limiter.limit("60 per minute")
def b2c_timeout():
    """
    An affiliate payout sent via Daraja B2C timed out without a result.
    The withdrawal stays 'processing' for manual follow-up — the M-Pesa
    Organization portal statement is the source of truth for what actually
    happened; we never auto-retry a money movement.
    ---
    tags: [Webhooks]
    responses:
      200: {description: Always accepted.}
    """
    payload = request.get_json(silent=True) or {}
    log_entry = _log_callback("b2c_timeout", payload)

    if not _daraja_ip_allowed():
        logger.warning("b2c_timeout: rejected IP %s.", request.remote_addr)
        return _accepted(log_entry, error="IP not in allowlist; not processed.")

    try:
        result = (payload.get("Result") or {})
        originator_id = result.get("OriginatorConversationID")

        withdrawal = (
            AffiliateWithdrawal.query.filter_by(b2c_originator_id=originator_id).first()
            if originator_id else None
        )
        if withdrawal is None:
            logger.warning("b2c_timeout: unknown/missing OriginatorConversationID %s.", originator_id)
            return _accepted(log_entry, error="Unknown OriginatorConversationID.")

        if withdrawal.b2c_status not in ("result_received",) and withdrawal.status != "paid":
            withdrawal.b2c_status = "timeout"
            db.session.commit()
            _notify_all_admins(
                category="affiliate_payout_failed",
                title="Affiliate payout timed out",
                body=f"B2C payout for withdrawal #{withdrawal.id} timed out. Check the M-Pesa portal or pay manually.",
                entity_type="affiliate_withdrawal", entity_id=withdrawal.id,
            )

        return _accepted(log_entry)

    except Exception:
        db.session.rollback()
        logger.exception("b2c_timeout: unhandled error processing payload.")
        return _accepted(error="Unhandled exception — see server logs.")
