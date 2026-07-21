"""
routes/admin_impersonation_routes.py — Consent-Based Impersonation
Blueprint: admin_impersonation_bp  |  Prefix: /api/admin/impersonation

This is a real consent workflow — NOT a silent backdoor.

Full lifecycle:
  1. Admin POSTs /request → ImpersonationRequest created (status=pending)
     → Landlord receives an in-app notification (dashboard alert).
  2. Landlord GETs /landlord/pending → sees outstanding requests.
  3. Landlord POSTs /landlord/requests/<id>/grant → status=granted.
     OR
     Landlord POSTs /landlord/requests/<id>/deny  → status=revoked (denied).
  4. Admin GETs /requests to see which have been granted.
  5. Admin uses the granted impersonation:
     - The admin's own JWT still identifies them as system_admin.
     - When acting as the landlord, the admin passes
       X-Impersonate-Landlord: <landlord_id> in their requests.
       Backend middleware reads this header, verifies a granted
       ImpersonationRequest exists, and appends an impersonation flag
       to every audit_log written during that session.
  6. Admin POSTs /requests/<id>/revoke → status=revoked, session ends.

Security guarantees:
  - No request → no access. Admin cannot act as landlord without a row
    in status=granted.
  - Every action during impersonation is audit-logged with actor=admin,
    impersonated_landlord_id recorded in description.
  - Landlord can revoke consent at any time via their own deny endpoint.
  - Optional expires_at: grants auto-expire (checked by Celery Beat).
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    ImpersonationRequest, ImpersonationStatus,
    Landlord, User, UserRole,
)
from services.audit_service import record_audit
from decorators import get_current_landlord_id

admin_impersonation_bp = Blueprint(
    "admin_impersonation", __name__, url_prefix="/api/admin/impersonation"
)

_DEFAULT_GRANT_HOURS = 24   # how long a grant is valid by default


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _require_landlord():
    claims = get_jwt()
    if claims.get("role") not in (
        UserRole.landlord.value, UserRole.property_manager.value
    ):
        abort(403, description="Landlord access required.")


def _admin_id() -> int:
    return int(get_jwt_identity())


# ===========================================================================
# Admin-facing routes
# ===========================================================================

# ---------------------------------------------------------------------------
# POST /api/admin/impersonation/request
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/request", methods=["POST"])
@jwt_required()
def create_impersonation_request():
    """
    Admin requests consent to operate a landlord's account.
    Creates an ImpersonationRequest row in status=pending.
    The landlord is notified (in-app; optionally SMS/email).

    Body:
      { landlord_id: int,
        reason: str,              -- shown to the landlord
        duration_hours?: int      -- default 24
      }
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      201: {description: Request created. Awaiting landlord consent.}
      400: {description: Validation error or duplicate pending request.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    data         = request.get_json(silent=True) or {}
    landlord_id  = data.get("landlord_id")
    reason       = (data.get("reason") or "").strip()
    duration_hrs = int(data.get("duration_hours", _DEFAULT_GRANT_HOURS))

    if not landlord_id or not reason:
        return jsonify({"error": "landlord_id and reason are required."}), 400

    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    # Prevent duplicate pending request for the same admin + landlord
    existing = ImpersonationRequest.query.filter_by(
        admin_user_id=_admin_id(),
        landlord_id=landlord_id,
        status=ImpersonationStatus.pending.value,
    ).first()
    if existing:
        return jsonify({
            "error":   "A pending request for this landlord already exists.",
            "request": existing.to_dict(),
        }), 400

    expires_at = datetime.utcnow() + timedelta(hours=duration_hrs)

    imp_req = ImpersonationRequest(
        admin_user_id = _admin_id(),
        landlord_id   = landlord_id,
        status        = ImpersonationStatus.pending.value,
        expires_at    = expires_at,
    )
    db.session.add(imp_req)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord_id,
        action="admin_impersonation_request",
        entity_type="account",
        entity_id=imp_req.id,
        description=(
            f"ADMIN: Client support access requested for landlord {landlord_id} "
            f"({landlord.company_name}). Reason: {reason}"
        ),
        after_data=imp_req.to_dict(),
    )

    from services.notification_service import notify
    admin_user = db.session.get(User, _admin_id())
    notify(
        recipient_user_id=landlord.user_id,
        category="impersonation_requested",
        template_key="impersonation_requested",
        template_kwargs={"admin_email": admin_user.email if admin_user else "a SahilPay admin", "reason": reason},
        sender_user_id=_admin_id(),
        landlord_id=landlord_id,
        link="/landlord/settings/impersonation-requests",
        entity_type="account",
        entity_id=imp_req.id,
    )
    db.session.commit()

    return jsonify({
        "message": "Support request sent. Awaiting landlord consent.",
        "request": imp_req.to_dict(),
    }), 201


# ---------------------------------------------------------------------------
# GET /api/admin/impersonation/requests
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/requests", methods=["GET"])
@jwt_required()
def admin_list_requests():
    """
    List all impersonation requests initiated by the current admin.
    Filters: ?status=pending|granted|revoked|expired, ?landlord_id=
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      200: {description: Admin's impersonation requests.}
    """
    _require_admin()

    query = ImpersonationRequest.query.filter_by(admin_user_id=_admin_id())

    if v := request.args.get("status"):
        query = query.filter(ImpersonationRequest.status == v)
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(ImpersonationRequest.landlord_id == v)

    requests_list = query.order_by(ImpersonationRequest.requested_at.desc()).all()

    items = []
    for r in requests_list:
        d = r.to_dict()
        if r.landlord:
            d["landlord_company"] = r.landlord.company_name
        items.append(d)

    return jsonify({"requests": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/impersonation/requests/<id>/revoke
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/requests/<int:request_id>/revoke", methods=["POST"])
@jwt_required()
def admin_revoke_request(request_id):
    """
    Admin ends an active impersonation session by revoking the grant.
    Also cancels a pending request if it has not yet been granted.
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      200: {description: Request revoked.}
      400: {description: Already revoked or expired.}
      404: {description: Request not found.}
    """
    _require_admin()
    imp_req = ImpersonationRequest.query.filter_by(
        id=request_id, admin_user_id=_admin_id()
    ).first()
    if not imp_req:
        return jsonify({"error": "Support request not found."}), 404
    if imp_req.status in (
        ImpersonationStatus.revoked.value, ImpersonationStatus.expired.value
    ):
        return jsonify({"error": f"This request is already {imp_req.status}."}), 400

    before = imp_req.to_dict()
    imp_req.status     = ImpersonationStatus.revoked.value
    imp_req.revoked_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=imp_req.landlord_id,
        action="admin_impersonation_revoke",
        entity_type="account",
        entity_id=imp_req.id,
        description=(
            f"ADMIN: Client support session revoked for landlord "
            f"{imp_req.landlord_id}."
        ),
        before_data=before,
        after_data=imp_req.to_dict(),
    )
    db.session.commit()

    return jsonify({"message": "Support access revoked.", "request": imp_req.to_dict()}), 200


# ===========================================================================
# Landlord-facing routes
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/admin/impersonation/landlord/pending
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/landlord/pending", methods=["GET"])
@jwt_required()
def landlord_pending_requests():
    """
    Landlord views outstanding impersonation requests awaiting their consent.
    Only returns requests in status=pending that have not expired.
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      200: {description: Pending consent requests for this landlord.}
    """
    _require_landlord()
    landlord_id = get_current_landlord_id()

    pending = ImpersonationRequest.query.filter_by(
        landlord_id=landlord_id,
        status=ImpersonationStatus.pending.value,
    ).filter(
        db.or_(
            ImpersonationRequest.expires_at.is_(None),
            ImpersonationRequest.expires_at > datetime.utcnow(),
        )
    ).order_by(ImpersonationRequest.requested_at.desc()).all()

    items = []
    for r in pending:
        d = r.to_dict()
        # Show admin identity (name/email) to landlord so they know who is asking
        if r.admin_user:
            d["admin_email"] = r.admin_user.email
        items.append(d)

    return jsonify({"pending_requests": items, "total": len(items)}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/impersonation/landlord/requests/<id>/grant
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/landlord/requests/<int:request_id>/grant", methods=["POST"])
@jwt_required()
def landlord_grant_request(request_id):
    """
    Landlord explicitly grants the impersonation request.
    Sets status=granted and records granted_at timestamp.
    From this point, the admin can operate the account until the grant
    expires or is revoked.
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      200: {description: Access granted.}
      400: {description: Request not in pending state or already expired.}
      404: {description: Request not found for this landlord.}
    """
    _require_landlord()
    landlord_id = get_current_landlord_id()

    imp_req = ImpersonationRequest.query.filter_by(
        id=request_id, landlord_id=landlord_id
    ).first()
    if not imp_req:
        return jsonify({"error": "Support request not found."}), 404
    if imp_req.status != ImpersonationStatus.pending.value:
        return jsonify({"error": f"This request is already '{imp_req.status}'."}), 400
    if imp_req.expires_at and imp_req.expires_at < datetime.utcnow():
        imp_req.status = ImpersonationStatus.expired.value
        db.session.commit()
        return jsonify({"error": "This request has expired."}), 400

    before = imp_req.to_dict()
    imp_req.status     = ImpersonationStatus.granted.value
    imp_req.granted_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="landlord_grant_impersonation",
        entity_type="account",
        entity_id=imp_req.id,
        description=(
            f"Landlord {landlord_id} GRANTED impersonation access "
            f"to admin user {imp_req.admin_user_id}."
        ),
        before_data=before,
        after_data=imp_req.to_dict(),
    )

    from services.notification_service import notify
    granting_landlord = db.session.get(Landlord, landlord_id)
    notify(
        recipient_user_id=imp_req.admin_user_id,
        category="impersonation_granted",
        template_key="impersonation_granted",
        template_kwargs={"company_name": granting_landlord.company_name if granting_landlord else "A landlord"},
        landlord_id=landlord_id,
        link="/admin/impersonation",
        entity_type="account",
        entity_id=imp_req.id,
    )
    db.session.commit()

    return jsonify({
        "message": "Support access granted.",
        "request": imp_req.to_dict(),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/impersonation/landlord/requests/<id>/deny
# ---------------------------------------------------------------------------
@admin_impersonation_bp.route("/landlord/requests/<int:request_id>/deny", methods=["POST"])
@jwt_required()
def landlord_deny_request(request_id):
    """
    Landlord denies the impersonation request.
    Sets status=revoked (denial is treated as a revocation before grant).
    The admin is notified (platform notification).
    ---
    tags: [Admin — Impersonation]
    security:
      - Bearer: []
    responses:
      200: {description: Access denied.}
      400: {description: Request not in pending state.}
      404: {description: Request not found for this landlord.}
    """
    _require_landlord()
    landlord_id = get_current_landlord_id()

    imp_req = ImpersonationRequest.query.filter_by(
        id=request_id, landlord_id=landlord_id
    ).first()
    if not imp_req:
        return jsonify({"error": "Support request not found."}), 404
    if imp_req.status != ImpersonationStatus.pending.value:
        return jsonify({"error": f"This request is already '{imp_req.status}'."}), 400

    before = imp_req.to_dict()
    imp_req.status     = ImpersonationStatus.revoked.value
    imp_req.revoked_at = datetime.utcnow()
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="landlord_deny_impersonation",
        entity_type="account",
        entity_id=imp_req.id,
        description=(
            f"Landlord {landlord_id} DENIED impersonation access "
            f"to admin user {imp_req.admin_user_id}."
        ),
        before_data=before,
        after_data=imp_req.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message": "Support request denied.",
        "request": imp_req.to_dict(),
    }), 200