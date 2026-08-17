"""
routes/communication_routes.py — Communications Log & Message Templates
Blueprint: comms_bp  |  Prefix: /api/communications

Every outbound SMS decrements landlords.sms_balance by sms_charge and
writes an append-only communication_logs row.
WhatsApp and email writes do NOT decrement sms_balance.

Templates support dynamic placeholders: {tenant_name}, {balance},
{invoice_items}, {due_date}, etc. — substitution happens at send time.
"""

import time
from datetime import datetime

from flask import Blueprint, current_app, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    CommunicationLog, MessageTemplate, Tenant, TeamMember, Unit, Landlord,
    MessageChannel, CommunicationStatus, RecipientType,
    MessageTemplateType,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from utils import accessible_property_ids
from services.audit_service        import record_audit
from services.communication_service import dispatch_message
from services.message_variables     import render_message, UNIVERSAL_VARIABLES, DEFAULT_TEMPLATES

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
# GET /api/communications/sms-balance
# ---------------------------------------------------------------------------
@comms_bp.route("/sms-balance", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def sms_balance():
    """
    The remaining SMS credits and the sender this account sends as.

    Deliberately separate from GET /api/settings/sms-provider, which carries the
    landlord's own provider API key and is therefore gated on the `settings`
    module. The Communications page only ever needed the BALANCE, so gating it
    behind `settings` meant the people who actually send the messages — a
    secretary holding `messages` — could not see how many credits were left, and
    found out by a send failing. Worse, `settings` is not a grantable module at
    all (it is absent from models.PermissionModule), so no team member could
    ever have been given it.

    Everything returned here is operational, not secret: a credit count, the
    sender ID that appears on the tenant's handset, and the per-SMS price. The
    API key is not included and must never be added to this payload.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: SMS credit balance and sender identity.}
    """
    from services.sms_billing import load_rates, DEFAULT_PLATFORM_SENDER

    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    settings    = landlord.landlord_settings if landlord else None

    # Sender mode and price are resolved EXACTLY as GET /api/settings/sms-provider
    # does, so the two screens can never quote different numbers for one account.
    has_own_sender = bool(getattr(settings, "sms_sender_id", None)
                          and getattr(settings, "sms_api_key", None))
    rates = load_rates()
    balance = landlord.sms_balance if landlord else 0
    threshold = getattr(settings, "low_sms_balance_threshold", 50) or 50

    return jsonify({
        "sms_balance":   balance,
        "sms_enabled":   bool(getattr(settings, "sms_enabled", True)),
        "sender_id":     getattr(settings, "sms_sender_id", None) or DEFAULT_PLATFORM_SENDER,
        "sender_mode":   "custom" if has_own_sender else "default",
        "price_per_sms": float(rates["custom_price"] if has_own_sender else rates["default_price"]),
        "currency":      getattr(landlord, "currency", "KES") or "KES",
        "low_balance":   balance <= threshold,
        "low_balance_threshold": threshold,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/communications/quote  — pre-send SMS cost calculator
# ---------------------------------------------------------------------------
@comms_bp.route("/quote", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def quote_message():
    """
    Estimate the CREDIT cost of an SMS send BEFORE sending, so the landlord sees
    exactly how many credits it will use (email/in-app are free — quote SMS only).
    Body:
      { content?: str, template_id?: int, tenant_ids?: [int] }
    When tenant_ids are given, the message is resolved per tenant (so {breakdown},
    {landlord_details}, … expand) and credits are summed per-recipient, since a
    longer personalised message can cost more credits than a shorter one.
    Returns per-message breakdown + totals and the landlord's current balance.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Credit-cost quote.}
    """
    from services.sms_billing import price_sms, load_credit_ranges

    landlord_id = get_current_landlord_id()
    landlord    = db.session.get(Landlord, landlord_id)
    settings    = landlord.landlord_settings if landlord else None
    data        = request.get_json(silent=True) or {}

    content     = (data.get("content") or "").strip()
    template_id = data.get("template_id")
    tenant_ids  = data.get("tenant_ids") or []

    if template_id:
        tmpl = MessageTemplate.query.filter_by(id=template_id, landlord_id=landlord_id).first()
        if tmpl:
            content = tmpl.body

    ranges = load_credit_ranges()
    per_recipient = []
    total_credits = 0

    if tenant_ids:
        tenants = Tenant.query.filter(
            Tenant.id.in_(tenant_ids), Tenant.landlord_id == landlord_id,
            Tenant.is_deleted.is_(False),
        ).all()
        for t in tenants:
            resolved = render_message(content, t, landlord) if content else ""
            econ = price_sms(resolved, settings, ranges=ranges)
            per_recipient.append({
                "tenant_id": t.id,
                "name": f"{t.first_name} {t.last_name}",
                "words": econ["words"], "credits": econ["credits"],
            })
            total_credits += econ["credits"]
    else:
        econ = price_sms(content, settings, ranges=ranges)
        per_recipient.append({"tenant_id": None, "name": None,
                              "words": econ["words"], "credits": econ["credits"]})
        total_credits = econ["credits"]

    return jsonify({
        "recipients":     len(per_recipient),
        "per_recipient":  per_recipient,
        "total_credits":  total_credits,
        "sms_balance":    landlord.sms_balance if landlord else 0,
        "sufficient":     (landlord.sms_balance if landlord else 0) >= total_credits,
        "ranges":         ranges,
        "uses_own_sender": bool(settings and settings.sms_connected and settings.sms_sender_id),
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
    team_member_ids = data.get("team_member_ids", [])
    content    = (data.get("content") or "").strip()
    template_id = data.get("template_id")

    valid_channels = {c.value for c in MessageChannel}
    if channel not in valid_channels:
        return jsonify({
            "error": f"Unknown channel '{channel}'. "
                     f"Use one of: {', '.join(sorted(valid_channels))}."
        }), 400

    if not tenant_ids and not team_member_ids:
        return jsonify({
            "error": "Choose at least one recipient (tenant_ids or team_member_ids)."
        }), 400

    # Resolve template content if provided
    if template_id:
        tmpl = MessageTemplate.query.filter_by(
            id=template_id, landlord_id=landlord_id
        ).first()
        if tmpl:
            content = tmpl.body

    if not content:
        return jsonify({"error": "content or a valid template_id is required."}), 400

    landlord = db.session.get(Landlord, landlord_id)

    # Fetch tenants — scoped to the account AND to the caller's own properties,
    # so a team member restricted to one block cannot message another block's
    # tenants by putting their ids in the request body.
    tenants = []
    if tenant_ids:
        query = Tenant.query.filter(
            Tenant.id.in_(tenant_ids),
            Tenant.landlord_id == landlord_id,
            Tenant.is_deleted.is_(False),
        )
        allowed_properties = accessible_property_ids()
        if allowed_properties is not None:
            query = (query.join(Tenant.unit)
                          .filter(Unit.property_id.in_(allowed_properties or {0})))
        tenants = query.all()

    # Fetch team members. Only ACTIVE ones: an invitation that was never
    # accepted has no working contact route, and a deactivated member should
    # stop receiving the account's messages the moment they are switched off.
    team_members = []
    if team_member_ids:
        team_members = TeamMember.query.filter(
            TeamMember.id.in_(team_member_ids),
            TeamMember.landlord_id == landlord_id,
            TeamMember.is_active.is_(True),
        ).all()
        allowed_properties = accessible_property_ids()
        if allowed_properties is not None:
            # A scoped member may only message colleagues who share at least one
            # of their properties (or who can see everything anyway).
            team_members = [
                m for m in team_members
                if m.property_access_all
                or {a.property_id for a in m.property_accesses} & set(allowed_properties)
            ]

    # SMS balance check — cost is the sum of each message's CREDIT cost (from the
    # admin word→credit tiers), not a flat 1-per-recipient, so a batch of long
    # messages is correctly gated up-front.
    if channel == MessageChannel.sms.value:
        from services.sms_billing import price_sms
        settings = landlord.landlord_settings if landlord else None
        cost = 0
        for t in tenants:
            resolved = render_message(content, t, landlord) if content else content
            cost += price_sms(resolved, settings)["credits"]
        for _ in team_members:
            # Team members get the content unsubstituted — tenant placeholders
            # like {balance} mean nothing for a colleague.
            cost += price_sms(content, settings)["credits"]
        if landlord.sms_balance < cost:
            return jsonify({
                "error": f"Insufficient SMS balance. Required: {cost} credit(s), Available: {landlord.sms_balance}."
            }), 400

    simulate = current_app.config.get("COMMS_SIMULATION_MODE", True)

    log_ids = []
    recipients_sent = 0
    for i, tenant in enumerate(tenants):
        # Substitute every universal variable ({tenant_name}, {unit}, {balance},
        # {payment_method}, …) for this specific tenant + landlord.
        personalized = render_message(content, tenant, landlord)

        log = dispatch_message(
            landlord_id=landlord_id,
            tenant=tenant,
            channel=channel,
            content=personalized,
        )
        log_ids.append(log.id if log else None)
        # NB: the SMS balance is decremented inside dispatch_message() (the single
        # chokepoint). Decrementing again here would double-charge every SMS.

        # FluxSMS allows 100 req/min per API key — throttle real SMS sends so
        # a large selection here doesn't burst past the rate limit.
        if channel == MessageChannel.sms.value and not simulate and i < len(tenants) - 1:
            time.sleep(0.75)
        recipients_sent += 1

    for i, member in enumerate(team_members):
        # No placeholder substitution: {balance}/{unit} describe a tenancy, and
        # rendering them for a colleague would emit blanks or nonsense.
        log = dispatch_message(
            landlord_id=landlord_id,
            tenant=member,
            channel=channel,
            content=content,
            recipient_type="team_member",
        )
        log_ids.append(log.id if log else None)
        if channel == MessageChannel.sms.value and not simulate and i < len(team_members) - 1:
            time.sleep(0.75)
        recipients_sent += 1

    db.session.commit()

    return jsonify({
        "message":  f"{recipients_sent} message(s) dispatched via {channel}.",
        "log_ids":  log_ids,
        "recipients": {"tenants": len(tenants), "team_members": len(team_members)},
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
# GET /api/communications/variables
# ---------------------------------------------------------------------------
@comms_bp.route("/variables", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def list_variables():
    """
    The universal placeholder catalogue landlords can drop into any template
    ({tenant_name}, {unit}, {balance}, {payment_method}, …). Substituted per
    tenant at send time.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Variable catalogue.}
    """
    get_current_landlord_id()
    return jsonify({"variables": UNIVERSAL_VARIABLES}), 200


# ---------------------------------------------------------------------------
# GET /api/communications/default-templates
# ---------------------------------------------------------------------------
@comms_bp.route("/default-templates", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "view")
def list_default_templates():
    """
    The ready-to-use starter templates (invoice, payment reminder, overdue
    balance) — each already includes {payment_method}. A landlord can send
    these as-is or install them as editable copies.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      200: {description: Default template catalogue.}
    """
    get_current_landlord_id()
    return jsonify({"templates": DEFAULT_TEMPLATES}), 200


# ---------------------------------------------------------------------------
# POST /api/communications/templates/install-defaults
# ---------------------------------------------------------------------------
@comms_bp.route("/templates/install-defaults", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("messages", "edit")
def install_default_templates():
    """
    Copy the default starter templates into this landlord's own editable
    templates. Skips any whose name already exists, so it is safe to re-run.
    ---
    tags: [Communications]
    security:
      - Bearer: []
    responses:
      201: {description: Defaults installed.}
    """
    landlord_id = get_current_landlord_id()
    existing = {t.name for t in MessageTemplate.query.filter_by(landlord_id=landlord_id).all()}

    created = []
    for spec in DEFAULT_TEMPLATES:
        if spec["name"] in existing:
            continue
        tmpl = MessageTemplate(
            landlord_id   = landlord_id,
            name          = spec["name"],
            channel       = spec["channel"],
            template_type = spec["template_type"],
            body          = spec["body"],
        )
        db.session.add(tmpl)
        created.append(tmpl)

    db.session.commit()
    for tmpl in created:
        record_audit(
            actor_user_id=int(get_jwt_identity()),
            landlord_id=landlord_id,
            action="install_default_template",
            entity_type="template",
            entity_id=tmpl.id,
            description=f"Default template '{tmpl.name}' installed.",
            after_data=tmpl.to_dict(),
        )
    db.session.commit()

    return jsonify({
        "message":   f"{len(created)} default template(s) installed.",
        "installed": [t.to_dict() for t in created],
    }), 201


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