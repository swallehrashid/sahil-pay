"""
routes/communication_routes.py — Communications Log & Message Templates
Blueprint: comms_bp  |  Prefix: /api/communications

Every outbound SMS decrements landlords.sms_balance by sms_charge and
writes an append-only communication_logs row.
WhatsApp and email writes do NOT decrement sms_balance.

Templates support dynamic placeholders: {tenant_name}, {balance},
{invoice_items}, {due_date}, etc. — substitution happens at send time.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    CommunicationLog, MessageTemplate, Tenant, Landlord,
    MessageChannel, CommunicationStatus, RecipientType,
    MessageTemplateType,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service        import record_audit
from services.communication_service import dispatch_message

comms_bp = Blueprint("communications", __name__, url_prefix="/api/communications")

_SMS_COST_PER_MESSAGE = 1   # 1 SMS credit per message (adjust to your AT pricing)


# ---------------------------------------------------------------------------
# GET /api/communications/
# ---------------------------------------------------------------------------
@comms_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def list_logs():
    """
    Return the communications log with counters and filters.
    Filters: ?channel=, ?status=, ?tenant_id=, ?start_date=, ?end_date=,
             ?page=, ?per_page=
    Counters: total_sent, total_delivered, total_failed (returned in summary).
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated comms log + counters.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = CommunicationLog.query.filter_by(landlord_id=landlord_id)

    if v := request.args.get("channel"):
        query = query.filter(CommunicationLog.message_type == v)
    if v := request.args.get("status"):
        query = query.filter(CommunicationLog.status == v)
    if v := request.args.get("tenant_id", type=int):
        query = query.filter(CommunicationLog.tenant_id == v)
    if v := request.args.get("start_date"):
        query = query.filter(CommunicationLog.sent_at >= v)
    if v := request.args.get("end_date"):
        query = query.filter(CommunicationLog.sent_at <= v)

    # Counters (unfiltered, full history for this landlord)
    base_q         = CommunicationLog.query.filter_by(landlord_id=landlord_id)
    total_sent     = base_q.count()
    total_delivered = base_q.filter_by(status=CommunicationStatus.delivered.value).count()
    total_failed   = base_q.filter_by(status=CommunicationStatus.failed.value).count()

    paginated = query.order_by(CommunicationLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for log in paginated.items:
        d = log.to_dict()
        if log.tenant:
            d["tenant_name"] = f"{log.tenant.first_name} {log.tenant.last_name}"
        items.append(d)

    return jsonify({
        "summary": {
            "total_sent":      total_sent,
            "total_delivered": total_delivered,
            "total_failed":    total_failed,
        },
        "logs":         items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/communications/send
# ---------------------------------------------------------------------------
@comms_bp.route("/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def send_message():
    """
    Send a message to one or more tenants.
    Body:
      { channel: 'sms'|'whatsapp'|'email',
        tenant_ids: [int],
        content: str,
        template_id?: int   -- if provided, overrides content after placeholder substitution }

    For SMS: checks sms_balance >= number of recipients before sending.
    Queues dispatch via Celery; returns immediately with a log_ids list.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Message(s) dispatched.}
      400: {description: Insufficient SMS balance or missing fields.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    channel    = data.get("channel", MessageChannel.sms.value)
    tenant_ids = data.get("tenant_ids", [])
    content    = (data.get("content") or "").strip()
    template_id = data.get("template_id")

    if not tenant_ids:
        return jsonify({"error": "tenant_ids list is required."}), 400

    # Resolve template content if provided
    if template_id:
        tmpl = MessageTemplate.query.filter_by(
            id=template_id, landlord_id=landlord_id
        ).first()
        if tmpl:
            content = tmpl.body

    if not content:
        return jsonify({"error": "content or a valid template_id is required."}), 400

    # SMS balance check
    landlord = db.session.get(Landlord, landlord_id)
    if channel == MessageChannel.sms.value:
        cost = _SMS_COST_PER_MESSAGE * len(tenant_ids)
        if landlord.sms_balance < cost:
            return jsonify({
                "error": f"Insufficient SMS balance. Required: {cost}, Available: {landlord.sms_balance}."
            }), 400

    # Fetch tenants
    tenants = Tenant.query.filter(
        Tenant.id.in_(tenant_ids),
        Tenant.landlord_id == landlord_id,
        Tenant.is_deleted.is_(False),
    ).all()

    log_ids = []
    for tenant in tenants:
        personalized = content\
            .replace("{tenant_name}", tenant.first_name or "")\
            .replace("{balance}", str(abs(float(tenant.balance or 0))))\
            .replace("{phone}", tenant.phone or "")

        log = dispatch_message(
            landlord_id=landlord_id,
            tenant=tenant,
            channel=channel,
            content=personalized,
        )
        log_ids.append(log.id if log else None)

        # Decrement SMS balance in-process (atomic commit follows)
        if channel == MessageChannel.sms.value:
            landlord.sms_balance = max(0, landlord.sms_balance - _SMS_COST_PER_MESSAGE)

    db.session.commit()

    return jsonify({
        "message":  f"{len(tenants)} message(s) dispatched via {channel}.",
        "log_ids":  log_ids,
        "sms_balance_remaining": landlord.sms_balance,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/communications/<id>/resend
# ---------------------------------------------------------------------------
@comms_bp.route("/<int:log_id>/resend", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def resend_message(log_id):
    """
    Resend a previously logged message (typically failed ones).
    Re-dispatches the exact same content and channel.
    Decrements SMS balance again if channel is SMS.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Message resent.}
      404: {description: Log entry not found.}
    """
    landlord_id = get_current_landlord_id()
    log         = CommunicationLog.query.filter_by(
        id=log_id, landlord_id=landlord_id
    ).first()
    if not log:
        return jsonify({"error": "Communication log entry not found."}), 404

    landlord = db.session.get(Landlord, landlord_id)

    # SMS balance check
    if log.message_type == MessageChannel.sms.value:
        if landlord.sms_balance < _SMS_COST_PER_MESSAGE:
            return jsonify({"error": "Insufficient SMS balance to resend."}), 400

    tenant = log.tenant
    new_log = dispatch_message(
        landlord_id=landlord_id,
        tenant=tenant,
        channel=log.message_type,
        content=log.content,
    )

    if log.message_type == MessageChannel.sms.value:
        landlord.sms_balance = max(0, landlord.sms_balance - _SMS_COST_PER_MESSAGE)

    db.session.commit()

    return jsonify({
        "message": "Message resent.",
        "new_log_id": new_log.id if new_log else None,
    }), 200


# ===========================================================================
# Message Templates
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /api/communications/templates
# ---------------------------------------------------------------------------
@comms_bp.route("/templates", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def list_templates():
    """
    List message templates for this landlord.
    Filters: ?channel=, ?template_type=
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Template list.}
    """
    landlord_id = get_current_landlord_id()
    query       = MessageTemplate.query.filter_by(landlord_id=landlord_id)

    if v := request.args.get("channel"):
        query = query.filter(MessageTemplate.channel == v)
    if v := request.args.get("template_type"):
        query = query.filter(MessageTemplate.template_type == v)

    templates = query.order_by(MessageTemplate.name).all()
    return jsonify({
        "templates": [t.to_dict() for t in templates],
        "total":     len(templates),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/communications/templates
# ---------------------------------------------------------------------------
@comms_bp.route("/templates", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def create_template():
    """
    Create a reusable message template.
    Body: { name, channel: 'sms'|'whatsapp'|'email',
            template_type?, body }
    Supported placeholders in body: {tenant_name}, {balance},
    {invoice_items}, {due_date}, {phone}.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      201: {description: Template created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    name    = (data.get("name") or "").strip()
    channel = data.get("channel")
    body    = (data.get("body") or "").strip()

    if not name or not body:
        return jsonify({"error": "name and body are required."}), 400

    tmpl = MessageTemplate(
        landlord_id   = landlord_id,
        name          = name,
        channel       = channel,
        template_type = data.get("template_type"),
        body          = body,
    )
    db.session.add(tmpl)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_message_template",
        entity_type="template",
        entity_id=tmpl.id,
        description=f"Message template '{name}' created.",
        after_data=tmpl.to_dict(),
    )
    db.session.commit()
    return jsonify(tmpl.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/communications/templates/<id>
# ---------------------------------------------------------------------------
@comms_bp.route("/templates/<int:template_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def update_template(template_id):
    """Update a message template's fields."""
    landlord_id = get_current_landlord_id()
    tmpl        = _get_template_or_404(landlord_id, template_id)
    data        = request.get_json(silent=True) or {}
    before      = tmpl.to_dict()

    for field in ["name", "channel", "template_type", "body"]:
        if field in data:
            setattr(tmpl, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_message_template",
        entity_type="template",
        entity_id=tmpl.id,
        description=f"Message template '{tmpl.name}' updated.",
        before_data=before,
        after_data=tmpl.to_dict(),
    )
    db.session.commit()
    return jsonify(tmpl.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/communications/templates/<id>
# ---------------------------------------------------------------------------
@comms_bp.route("/templates/<int:template_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def delete_template(template_id):
    """Hard-delete a message template."""
    landlord_id = get_current_landlord_id()
    tmpl        = _get_template_or_404(landlord_id, template_id)

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_message_template",
        entity_type="template",
        entity_id=template_id,
        description=f"Message template '{tmpl.name}' deleted.",
        before_data=tmpl.to_dict(),
    )
    db.session.commit()
    db.session.delete(tmpl)
    db.session.commit()

    return jsonify({"message": f"Template '{tmpl.name}' deleted."}), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_template_or_404(landlord_id: int, template_id: int) -> MessageTemplate:
    t = MessageTemplate.query.filter_by(id=template_id, landlord_id=landlord_id).first()
    if not t:
        abort(404, description="Message template not found.")
    return t