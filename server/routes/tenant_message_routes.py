"""
routes/tenant_message_routes.py — Landlord/Team side of the tenant↔landlord
conversation.  Blueprint: tenant_message_bp  |  Prefix: /api/tenant-messages

The tenant side lives in tenant_portal_routes.py (GET/POST /api/portal/messages).
Here the landlord — and any team member with the `messages` permission — reads
the inbox of tenant threads and replies. A reply fans an in-app notification
back to the tenant, mirroring how the tenant's outbound message already
notifies the landlord/team.

A "thread" is simply every TenantMessage row sharing (landlord_id, tenant_id).
Messages module is landlord-scoped (not property-scoped), consistent with the
existing communications module.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from extensions import db
from models import TenantMessage, Tenant, Landlord
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
)
from utils import get_jwt_user

tenant_message_bp = Blueprint("tenant_message", __name__, url_prefix="/api/tenant-messages")


def _actor_identity():
    """Return (sender_role, sender_user_id, sender_name) for the caller."""
    user = get_jwt_user()
    if user.role == "team_member":
        tm = user.team_member_profile
        name = f"{tm.first_name} {tm.last_name}".strip() if tm else "Team member"
        return "team_member", user.id, name
    # landlord / property_manager / system_admin acting in landlord scope
    landlord_id = get_current_landlord_id()
    landlord = db.session.get(Landlord, landlord_id)
    name = landlord.company_name if landlord and landlord.company_name else "Landlord"
    return "landlord", user.id, name


def _tenant_display(tenant: Tenant) -> dict:
    unit = tenant.unit
    return {
        "tenant_id":     tenant.id,
        "tenant_name":   f"{tenant.first_name} {tenant.last_name}".strip(),
        "unit_name":     unit.name if unit else None,
        "property_name": unit.property.name if unit and unit.property else None,
    }


# ---------------------------------------------------------------------------
# GET /api/tenant-messages/  — inbox of threads
# ---------------------------------------------------------------------------
@tenant_message_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def list_threads():
    """
    One row per tenant who has a conversation, newest activity first, each with
    the last message preview and a count of unread (tenant-sent) messages.
    ---
    tags: [Tenant Messages]
    security:
      - Bearer: []
    responses:
      200: {description: Threads.}
    """
    landlord_id = get_current_landlord_id()

    rows = (
        TenantMessage.query
        .filter_by(landlord_id=landlord_id)
        .order_by(TenantMessage.created_at.asc())
        .all()
    )

    threads: dict[int, dict] = {}
    for m in rows:
        t = threads.setdefault(m.tenant_id, {
            "tenant_id": m.tenant_id, "last_message": None, "last_at": None,
            "last_sender_role": None, "unread": 0,
        })
        t["last_message"]     = m.body
        t["last_at"]          = m.created_at.isoformat() if m.created_at else None
        t["last_sender_role"] = m.sender_role
        if m.sender_role == "tenant" and not m.is_read:
            t["unread"] += 1

    # Attach tenant display info; drop threads whose tenant was deleted.
    result = []
    for tenant_id, t in threads.items():
        tenant = Tenant.query.filter_by(id=tenant_id, is_deleted=False).first()
        if not tenant:
            continue
        t.update(_tenant_display(tenant))
        result.append(t)

    result.sort(key=lambda x: x["last_at"] or "", reverse=True)

    return jsonify({
        "threads":      result,
        "total":        len(result),
        "total_unread": sum(t["unread"] for t in result),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/tenant-messages/<tenant_id>  — one thread
# ---------------------------------------------------------------------------
@tenant_message_bp.route("/<int:tenant_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def get_thread(tenant_id):
    """
    Full conversation with one tenant, oldest-first. Marks the tenant's
    inbound messages as read.
    ---
    tags: [Tenant Messages]
    security:
      - Bearer: []
    responses:
      200: {description: Thread.}
      404: {description: Tenant not found.}
    """
    landlord_id = get_current_landlord_id()

    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id, is_deleted=False).first()
    if not tenant:
        abort(404, description="Tenant not found.")

    msgs = (
        TenantMessage.query
        .filter_by(landlord_id=landlord_id, tenant_id=tenant_id)
        .order_by(TenantMessage.created_at.asc())
        .all()
    )

    unread = [m for m in msgs if m.sender_role == "tenant" and not m.is_read]
    if unread:
        for m in unread:
            m.is_read = True
            m.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify({
        "tenant":   _tenant_display(tenant),
        "messages": [m.to_dict() for m in msgs],
        "total":    len(msgs),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/tenant-messages/<tenant_id>  — reply
# ---------------------------------------------------------------------------
@tenant_message_bp.route("/<int:tenant_id>", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def reply(tenant_id):
    """
    Landlord/team replies to a tenant. Notifies the tenant in-app.
    Body: { body (required) }
    ---
    tags: [Tenant Messages]
    security:
      - Bearer: []
    responses:
      201: {description: Reply sent.}
      400: {description: Validation error.}
      404: {description: Tenant not found.}
    """
    from services.notification_service import notify

    landlord_id = get_current_landlord_id()
    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id, is_deleted=False).first()
    if not tenant:
        abort(404, description="Tenant not found.")

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Message body is required."}), 400

    sender_role, sender_user_id, sender_name = _actor_identity()

    msg = TenantMessage(
        landlord_id    = landlord_id,
        tenant_id      = tenant.id,
        sender_role    = sender_role,
        sender_user_id = sender_user_id,
        sender_name    = sender_name,
        category       = None,
        body           = body,
        is_read        = False,
    )
    db.session.add(msg)
    db.session.flush()

    if tenant.user_id:
        preview = body if len(body) <= 120 else body[:117] + "…"
        notify(
            recipient_user_id=tenant.user_id,
            category="tenant_message",
            title=f"New message from {sender_name}",
            body=preview,
            sender_user_id=sender_user_id,
            landlord_id=landlord_id,
            link="/portal/messages",
            entity_type="tenant_message",
            entity_id=msg.id,
        )

    db.session.commit()

    return jsonify({
        "message": "Reply sent.",
        "data":    msg.to_dict(),
    }), 201
