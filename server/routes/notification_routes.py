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
from services.notification_service import notify, notify_many, notify_tenants, TEMPLATES
from services.audit_service import record_audit

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


def _current_user_id() -> int:
    """The numeric User.id of the caller, or -1 for a tenant token.

    Tenant tokens carry a namespaced identity ("tenant:<id>", see
    otp_routes.py) that is deliberately not a User.id. Notifications are keyed
    by recipient User.id, and OTP-only tenants have no User row, so a tenant
    caller simply owns no notification rows — return a sentinel that matches
    nothing rather than crashing on int("tenant:..."). (Do not resolve this to
    the tenant's id: that is exactly the cross-account collision this identity
    scheme was introduced to prevent.)
    """
    identity = get_jwt_identity()
    if isinstance(identity, str) and identity.startswith("tenant:"):
        return -1
    return int(identity)


def _current_role() -> str:
    return get_jwt().get("role")


def _current_tenant_id():
    """The tenant_id claim for a tenant token, else None."""
    return get_jwt().get("tenant_id")


def _scope_to_recipient(query):
    """
    Scope a Notification query to the caller's own rows. A tenant caller reads
    their recipient_tenant_id rows; every other caller reads their
    recipient_user_id rows.
    """
    from models import Notification
    tenant_id = _current_tenant_id()
    if tenant_id:
        return query.filter(Notification.recipient_tenant_id == tenant_id)
    return query.filter(Notification.recipient_user_id == _current_user_id())


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
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = _scope_to_recipient(Notification.query)
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
    count = _scope_to_recipient(Notification.query).filter(Notification.is_read.is_(False)).count()
    return jsonify({"unread_count": count}), 200


# ---------------------------------------------------------------------------
# POST /api/notifications/<id>/read
# ---------------------------------------------------------------------------
@notification_bp.route("/<int:notification_id>/read", methods=["POST"])
@jwt_required()
def mark_read(notification_id):
    """Mark one of the caller's own notifications as read."""
    from datetime import datetime

    note = _scope_to_recipient(Notification.query.filter(Notification.id == notification_id)).first()
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

    updated = _scope_to_recipient(
        Notification.query.filter(Notification.is_read.is_(False))
    ).update({"is_read": True, "read_at": datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return jsonify({"message": f"{updated} notification(s) marked as read."}), 200


# ---------------------------------------------------------------------------
# GET /api/notifications/templates
# ---------------------------------------------------------------------------
@notification_bp.route("/templates", methods=["GET"])
@jwt_required()
def list_templates():
    """
    List notification template keys for the send UI's template picker.

    #11 — a landlord/team member only sees templates they can actually send to
    tenants/team members; platform templates (trial_expiring, low_sms_balance,
    impersonation_*, etc.) are admin/system-originated and are hidden from them.
    Admins still see the full registry. An optional ?audience=tenant|team narrows
    the landlord list further.
    """
    from flask_jwt_extended import get_jwt_identity
    from models import User, UserRole
    from services.notification_service import (
        LANDLORD_SENDABLE_TEMPLATES, LANDLORD_TENANT_TEMPLATES, LANDLORD_TEAM_TEMPLATES,
    )

    user = db.session.get(User, int(get_jwt_identity())) if get_jwt_identity() else None
    role = user.role if user else None

    if role == UserRole.system_admin.value:
        keys = list(TEMPLATES.keys())
    else:
        audience = request.args.get("audience")
        if audience == "tenant":
            keys = list(LANDLORD_TENANT_TEMPLATES)
        elif audience == "team":
            keys = list(LANDLORD_TEAM_TEMPLATES)
        else:
            keys = list(LANDLORD_SENDABLE_TEMPLATES)

    return jsonify({"templates": keys}), 200


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

    # Tenants are addressed by TENANT id (they may have no User row); everyone
    # else is addressed by User id. We collect into the matching bucket so an
    # OTP-only tenant is never silently dropped for lacking a user_id.
    recipient_user_ids: list[int] = []
    recipient_tenant_ids: list[int] = []
    scope_landlord_id = caller_landlord_id

    if audience == "all_landlords":
        recipient_user_ids = [u for (u,) in db.session.query(Landlord.user_id).all() if u]

    elif audience == "landlord":
        if not target_id:
            return jsonify({"error": "target_id (landlord_id) is required."}), 400
        landlord = db.session.get(Landlord, target_id)
        if not landlord:
            return jsonify({"error": "Landlord not found."}), 404
        recipient_user_ids = [landlord.user_id] if landlord.user_id else []
        scope_landlord_id = landlord.id

    elif audience == "all_tenants":
        landlord_id = target_id if is_admin and target_id else caller_landlord_id
        query = db.session.query(Tenant.id).filter(Tenant.is_deleted.is_(False))
        if landlord_id:
            query = query.filter(Tenant.landlord_id == landlord_id)
            scope_landlord_id = landlord_id
        recipient_tenant_ids = [t for (t,) in query.all()]

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
        recipient_tenant_ids = [
            t for (t,) in db.session.query(Tenant.id)
            .join(Unit, Unit.id == Tenant.unit_id)
            .filter(Unit.property_id == prop.id, Tenant.is_deleted.is_(False))
            .all()
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
        if not row:
            return jsonify({"error": f"{target_type.title()} not found."}), 404
        # A landlord caller may only message their own tenant/team-member;
        # they can never target another landlord's account this way.
        row_landlord_id = row.id if target_type == "landlord" else row.landlord_id
        if not is_admin and (target_type == "landlord" or row_landlord_id != caller_landlord_id):
            abort(403, description="That recipient does not belong to your account.")
        # Tenants are addressed by tenant id (no User needed); others by user id.
        if target_type == "tenant":
            recipient_tenant_ids = [row.id]
        elif row.user_id:
            recipient_user_ids = [row.user_id]
        else:
            return jsonify({"error": f"{target_type.title()} has no login account to notify."}), 400
        scope_landlord_id = row_landlord_id

    if not recipient_user_ids and not recipient_tenant_ids:
        return jsonify({"error": "No recipients matched that audience."}), 400

    common = dict(
        category=template_key if template_key in TEMPLATES else "broadcast",
        title=title, body=body,
        template_key=template_key, template_kwargs=template_kwargs,
        sender_user_id=_current_user_id() if _current_user_id() != -1 else None,
        landlord_id=scope_landlord_id,
        link=link,
    )
    notes = notify_many(recipient_user_ids, **common) if recipient_user_ids else []
    notes += notify_tenants(recipient_tenant_ids, **common) if recipient_tenant_ids else []
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
