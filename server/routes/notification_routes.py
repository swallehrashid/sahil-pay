"""
routes/notification_routes.py — In-App Notifications
Blueprint: notification_bp  |  Prefix: /api/notifications

Two halves:
  - Self-service (any authenticated role): list my own notifications,
    unread count, mark one/all as read. Every query filters by
    recipient_user_id = the caller's own User.id from the JWT — never
    from request input.
  - Send (system_admin or landlord/property_manager only): broadcast a
    templated or custom notification to a resolved audience. Fans out
    into one Notification row per recipient. A landlord can only ever
    target their own tenants/team; only system_admin can target other
    landlords or platform-wide audiences.
"""

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    Notification, Tenant, TeamMember, Landlord, Property, Unit, UserRole,
)
from services.notification_service import notify, notify_many, TEMPLATES
from services.audit_service import record_audit

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


def _current_user_id() -> int:
    return int(get_jwt_identity())


def _current_role() -> str:
    return get_jwt().get("role")


# ---------------------------------------------------------------------------
# GET /api/notifications/
# ---------------------------------------------------------------------------
@notification_bp.route("/", methods=["GET"])
@jwt_required()
def list_notifications():
    """
    List the authenticated user's own notifications, unread-first.
    Filters: ?is_read=true|false, ?page=, ?per_page=
    ---
    tags: [Notifications]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated notifications for the current user.}
    """
    user_id  = _current_user_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Notification.query.filter_by(recipient_user_id=user_id)
    if (v := request.args.get("is_read")) is not None:
        query = query.filter(Notification.is_read == (v.lower() == "true"))

    paginated = query.order_by(
        Notification.is_read.asc(), Notification.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "notifications": [n.to_dict() for n in paginated.items],
        "total":         paginated.total,
        "pages":         paginated.pages,
        "current_page":  paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/notifications/unread-count
# ---------------------------------------------------------------------------
@notification_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def unread_count():
    """Return the authenticated user's unread notification count (for a navbar badge)."""
    user_id = _current_user_id()
    count = Notification.query.filter_by(recipient_user_id=user_id, is_read=False).count()
    return jsonify({"unread_count": count}), 200


# ---------------------------------------------------------------------------
# POST /api/notifications/<id>/read
# ---------------------------------------------------------------------------
@notification_bp.route("/<int:notification_id>/read", methods=["POST"])
@jwt_required()
def mark_read(notification_id):
    """Mark one of the caller's own notifications as read."""
    from datetime import datetime

    user_id = _current_user_id()
    note = Notification.query.filter_by(id=notification_id, recipient_user_id=user_id).first()
    if not note:
        return jsonify({"error": "Notification not found."}), 404

    if not note.is_read:
        note.is_read = True
        note.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify(note.to_dict()), 200


# ---------------------------------------------------------------------------
# POST /api/notifications/read-all
# ---------------------------------------------------------------------------
@notification_bp.route("/read-all", methods=["POST"])
@jwt_required()
def mark_all_read():
    """Mark every one of the caller's unread notifications as read."""
    from datetime import datetime

    user_id = _current_user_id()
    updated = Notification.query.filter_by(recipient_user_id=user_id, is_read=False).update(
        {"is_read": True, "read_at": datetime.utcnow()}
    )
    db.session.commit()
    return jsonify({"message": f"{updated} notification(s) marked as read."}), 200


# ---------------------------------------------------------------------------
# GET /api/notifications/templates
# ---------------------------------------------------------------------------
@notification_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    """List available notification template keys (for the send UI's template picker)."""
    return jsonify({"templates": list(TEMPLATES.keys())}), 200


# ---------------------------------------------------------------------------
# POST /api/notifications/send
# ---------------------------------------------------------------------------
@notification_bp.route("/send", methods=["POST"])
@jwt_required()
def send_notification():
    """
    Broadcast a notification to a resolved audience.
    Body:
      { audience: 'user'|'landlord'|'property_tenants'|'all_tenants'|
                  'all_team_members'|'all_landlords',
        target_type?: 'tenant'|'team_member'|'landlord',  -- required when audience='user'
        target_id?: int,   -- tenant_id / team_member_id / landlord_id / property_id
        template_key?: str, template_kwargs?: dict,
        title?: str, body?: str,   -- required unless template_key is given
        link?: str }

    Authorization:
      - system_admin: any audience, any target.
      - landlord/property_manager: only 'user' (within their own tenants/
        team), 'property_tenants' (their own property), and 'all_tenants' /
        'all_team_members' (always scoped to themselves — target_id ignored).
      - Everyone else: 403.
    ---
    tags: [Notifications]
    security:
      - Bearer: []
    responses:
      201: {description: Notification(s) sent.}
      400: {description: Validation error.}
      403: {description: Audience not permitted for this role.}
    """
    role = _current_role()
    if role not in (UserRole.system_admin.value, UserRole.landlord.value, UserRole.property_manager.value):
        abort(403, description="Only admins and landlords can send notifications.")
    is_admin = role == UserRole.system_admin.value

    data         = request.get_json(silent=True) or {}
    audience     = data.get("audience")
    target_type  = data.get("target_type")
    target_id    = data.get("target_id")
    template_key = data.get("template_key")
    template_kwargs = data.get("template_kwargs") or {}
    title        = data.get("title")
    body         = data.get("body")
    link         = data.get("link")

    valid_audiences = {"user", "landlord", "property_tenants", "all_tenants", "all_team_members", "all_landlords"}
    if audience not in valid_audiences:
        return jsonify({"error": f"audience must be one of: {sorted(valid_audiences)}."}), 400
    if not template_key and not (title and body):
        return jsonify({"error": "Either template_key or both title and body are required."}), 400
    if not is_admin and audience in ("all_landlords",):
        abort(403, description="Only system admins may use this audience.")
    if not is_admin and audience == "landlord":
        abort(403, description="Only system admins may notify another landlord.")

    # The landlord_id this send is scoped to, for audit + the Notification rows'
    # own landlord_id column. Admin sends targeting other landlords resolve it
    # per-audience below; a landlord caller is always scoped to themselves.
    caller_landlord_id = None
    if not is_admin:
        from decorators import get_current_landlord_id
        caller_landlord_id = get_current_landlord_id()

    recipient_user_ids: list[int] = []
    scope_landlord_id = caller_landlord_id

    if audience == "all_landlords":
        recipient_user_ids = [u for (u,) in db.session.query(Landlord.user_id).all()]

    elif audience == "landlord":
        if not target_id:
            return jsonify({"error": "target_id (landlord_id) is required."}), 400
        landlord = db.session.get(Landlord, target_id)
        if not landlord:
            return jsonify({"error": "Landlord not found."}), 404
        recipient_user_ids = [landlord.user_id]
        scope_landlord_id = landlord.id

    elif audience == "all_tenants":
        landlord_id = target_id if is_admin and target_id else caller_landlord_id
        query = db.session.query(Tenant.user_id).filter(Tenant.is_deleted.is_(False))
        if landlord_id:
            query = query.filter(Tenant.landlord_id == landlord_id)
            scope_landlord_id = landlord_id
        recipient_user_ids = [u for (u,) in query.all() if u]

    elif audience == "all_team_members":
        landlord_id = target_id if is_admin and target_id else caller_landlord_id
        query = db.session.query(TeamMember.user_id).filter(TeamMember.is_active.is_(True))
        if landlord_id:
            query = query.filter(TeamMember.landlord_id == landlord_id)
            scope_landlord_id = landlord_id
        recipient_user_ids = [u for (u,) in query.all() if u]

    elif audience == "property_tenants":
        if not target_id:
            return jsonify({"error": "target_id (property_id) is required."}), 400
        prop = db.session.get(Property, target_id)
        if not prop or prop.is_deleted:
            return jsonify({"error": "Property not found."}), 404
        if not is_admin and prop.landlord_id != caller_landlord_id:
            abort(403, description="That property does not belong to your account.")
        recipient_user_ids = [
            u for (u,) in db.session.query(Tenant.user_id)
            .join(Unit, Unit.id == Tenant.unit_id)
            .filter(Unit.property_id == prop.id, Tenant.is_deleted.is_(False))
            .all() if u
        ]
        scope_landlord_id = prop.landlord_id

    elif audience == "user":
        if target_type not in ("tenant", "team_member", "landlord") or not target_id:
            return jsonify({"error": "target_type ('tenant'|'team_member'|'landlord') and target_id are required."}), 400
        if target_type == "tenant":
            row = Tenant.query.filter_by(id=target_id, is_deleted=False).first()
        elif target_type == "team_member":
            row = TeamMember.query.filter_by(id=target_id).first()
        else:
            row = Landlord.query.filter_by(id=target_id).first()
        if not row or not row.user_id:
            return jsonify({"error": f"{target_type.title()} not found."}), 404
        # A landlord caller may only message their own tenant/team-member;
        # they can never target another landlord's account this way.
        row_landlord_id = row.id if target_type == "landlord" else row.landlord_id
        if not is_admin and (target_type == "landlord" or row_landlord_id != caller_landlord_id):
            abort(403, description="That recipient does not belong to your account.")
        recipient_user_ids = [row.user_id]
        scope_landlord_id = row_landlord_id

    if not recipient_user_ids:
        return jsonify({"error": "No recipients matched that audience."}), 400

    notes = notify_many(
        recipient_user_ids,
        category=template_key if template_key in TEMPLATES else "broadcast",
        title=title, body=body,
        template_key=template_key, template_kwargs=template_kwargs,
        sender_user_id=_current_user_id(),
        landlord_id=scope_landlord_id,
        link=link,
    )
    db.session.commit()

    record_audit(
        actor_user_id=_current_user_id(),
        landlord_id=scope_landlord_id,
        action="send_notification",
        entity_type="notification",
        entity_id=None,
        description=(
            f"Notification sent to {len(notes)} recipient(s) "
            f"(audience={audience}, template={template_key or 'custom'})."
        ),
        after_data={"title": notes[0].title, "body": notes[0].body, "recipient_count": len(notes)},
    )
    db.session.commit()

    return jsonify({
        "message": f"Notification sent to {len(notes)} recipient(s).",
        "recipient_count": len(notes),
    }), 201
