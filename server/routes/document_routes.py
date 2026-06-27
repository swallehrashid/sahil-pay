"""
routes/document_routes.py — Document Templates & Delivery
Blueprint: document_bp  |  Prefix: /api/documents

Covers §4.18: lease agreements, tenancy notices, deposit receipts, etc.

A DocumentTemplate stores either:
  a) An HTML body string (rendered by WeasyPrint at send time), or
  b) A URL to an uploaded static file (PDF/Word).

When /send is called, the template is rendered with per-tenant data
(placeholders: {tenant_name}, {unit_name}, {property_name}, {rent_amount},
{lease_start}, {lease_expiry}, {landlord_name}, etc.) and delivered via
the channel specified (email = PDF attachment; WhatsApp/SMS = link).
"""

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    DocumentTemplate, Tenant, Landlord, CommunicationLog,
    CommunicationStatus, MessageChannel, RecipientType,
)
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from services.audit_service    import record_audit
from services.storage_service  import upload_to_s3
from services.pdf_service      import render_document_template

document_bp = Blueprint("documents", __name__, url_prefix="/api/documents")


# ---------------------------------------------------------------------------
# GET /api/documents/templates
# ---------------------------------------------------------------------------
@document_bp.route("/templates", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def list_templates():
    """
    List all document templates for this landlord.
    Filters: ?document_type=, ?page=, ?per_page=
    ---
    tags: [Documents]
    security:
      - Bearer: []
    responses:
      200: {description: Document template list.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = DocumentTemplate.query.filter_by(landlord_id=landlord_id)

    if v := request.args.get("document_type"):
        query = query.filter(DocumentTemplate.document_type == v)

    paginated = query.order_by(DocumentTemplate.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "templates":    [t.to_dict() for t in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/documents/templates
# ---------------------------------------------------------------------------
@document_bp.route("/templates", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def create_template():
    """
    Create a document template.
    Accepts either:
      - JSON  { name, document_type?, content: str }  — for HTML/WeasyPrint templates
      - Multipart  { name, document_type?, file }        — for uploaded PDF/Word files

    Supported placeholders in content:
      {tenant_name}, {unit_name}, {property_name}, {rent_amount},
      {lease_start}, {lease_expiry}, {landlord_name}, {landlord_company}
    ---
    tags: [Documents]
    security:
      - Bearer: []
    responses:
      201: {description: Template created.}
      400: {description: Validation error.}
    """
    landlord_id = get_current_landlord_id()

    if request.is_json:
        data     = request.get_json(silent=True) or {}
        file_url = None
        content = data.get("content")
    else:
        data      = request.form.to_dict()
        file      = request.files.get("file")
        file_url  = upload_to_s3(file, folder=f"documents/{landlord_id}") if file else None
        content = None

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required."}), 400
    if not content and not file_url:
        return jsonify({"error": "Either content or a file upload is required."}), 400

    tmpl = DocumentTemplate(
        landlord_id   = landlord_id,
        name          = name,
        document_type = data.get("document_type"),
        content     = content,
        file_url      = file_url,
    )
    db.session.add(tmpl)
    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="create_document_template",
        entity_type="document_template",
        entity_id=tmpl.id,
        description=f"Document template '{name}' created.",
        after_data=tmpl.to_dict(),
    )
    db.session.commit()
    return jsonify(tmpl.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/documents/templates/<id>
# ---------------------------------------------------------------------------
@document_bp.route("/templates/<int:template_id>", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def update_template(template_id):
    """Update a document template's name, type, or HTML body."""
    landlord_id = get_current_landlord_id()
    tmpl        = _get_or_404(landlord_id, template_id)
    data        = request.get_json(silent=True) or {}
    before      = tmpl.to_dict()

    for field in ["name", "document_type", "content"]:
        if field in data:
            setattr(tmpl, field, data[field])

    db.session.commit()

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="update_document_template",
        entity_type="document_template",
        entity_id=tmpl.id,
        description=f"Document template '{tmpl.name}' updated.",
        before_data=before,
        after_data=tmpl.to_dict(),
    )
    db.session.commit()
    return jsonify(tmpl.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/documents/templates/<id>
# ---------------------------------------------------------------------------
@document_bp.route("/templates/<int:template_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def delete_template(template_id):
    """Hard-delete a document template."""
    landlord_id = get_current_landlord_id()
    tmpl        = _get_or_404(landlord_id, template_id)

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="delete_document_template",
        entity_type="document_template",
        entity_id=template_id,
        description=f"Document template '{tmpl.name}' deleted.",
        before_data=tmpl.to_dict(),
    )
    db.session.commit()
    db.session.delete(tmpl)
    db.session.commit()

    return jsonify({"message": f"Template '{tmpl.name}' deleted."}), 200


# ---------------------------------------------------------------------------
# POST /api/documents/send
# ---------------------------------------------------------------------------
@document_bp.route("/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def send_document():
    """
    Render a document template for each target tenant and deliver it.
    Body:
      { template_id: int,
        tenant_ids: [int],
        channel: 'email' | 'sms' | 'whatsapp'  (default: email) }

    For HTML templates: renders to PDF via WeasyPrint, attaches to email or
    uploads to S3 and shares the link via SMS/WhatsApp.
    For file-based templates: forwards the stored file_url directly.

    Writes one CommunicationLog row per recipient.
    ---
    tags: [Documents]
    security:
      - Bearer: []
    responses:
      200: {description: Document sent to all recipients.}
      400: {description: Validation error.}
      404: {description: Template not found.}
    """
    landlord_id = get_current_landlord_id()
    data        = request.get_json(silent=True) or {}

    template_id = data.get("template_id")
    tenant_ids  = data.get("tenant_ids", [])
    channel     = data.get("channel", MessageChannel.email.value)

    if not template_id or not tenant_ids:
        return jsonify({"error": "template_id and tenant_ids are required."}), 400

    tmpl = _get_or_404(landlord_id, template_id)

    tenants = Tenant.query.filter(
        Tenant.id.in_(tenant_ids),
        Tenant.landlord_id == landlord_id,
        Tenant.is_deleted.is_(False),
    ).all()

    landlord = db.session.get(Landlord, landlord_id)

    log_ids = []
    for tenant in tenants:
        # Build placeholder context
        unit     = tenant.unit
        property = unit.property if unit else None

        context = {
            "{tenant_name}":      f"{tenant.first_name} {tenant.last_name}",
            "{unit_name}":        unit.name if unit else "",
            "{property_name}":    property.name if property else "",
            "{rent_amount}":      str(unit.rent_amount) if unit else "",
            "{lease_start}":      str(tenant.lease_start_date or ""),
            "{lease_expiry}":     str(tenant.lease_expiry_date or ""),
            "{landlord_name}":    landlord.user.email if landlord.user else "",
            "{landlord_company}": landlord.company_name or "",
            "{phone}":            tenant.phone or "",
        }

        if tmpl.content:
            body = tmpl.content
            for placeholder, value in context.items():
                body = body.replace(placeholder, value)
            # Render to PDF and send
            pdf_bytes = render_document_template(body)
            _dispatch_document(
                landlord_id=landlord_id,
                tenant=tenant,
                channel=channel,
                template_name=tmpl.name,
                pdf_bytes=pdf_bytes,
                file_url=None,
            )
        else:
            # Static file — share the URL
            _dispatch_document(
                landlord_id=landlord_id,
                tenant=tenant,
                channel=channel,
                template_name=tmpl.name,
                pdf_bytes=None,
                file_url=tmpl.file_url,
            )

    db.session.commit()

    return jsonify({
        "message": f"Document '{tmpl.name}' sent to {len(tenants)} tenant(s) via {channel}.",
    }), 200


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------
def _dispatch_document(
    landlord_id, tenant, channel, template_name,
    pdf_bytes=None, file_url=None
):
    """Write a CommunicationLog row and dispatch the document."""
    from services.email_service import send_document_email
    from services.sms_service   import send_sms

    content = f"Please find your {template_name} document."
    if file_url:
        content += f" Link: {file_url}"

    if channel == MessageChannel.email.value and tenant.email:
        send_document_email.delay(
            tenant.email, tenant.first_name, template_name, pdf_bytes, file_url
        )
    elif channel in (MessageChannel.sms.value, MessageChannel.whatsapp.value):
        recipient = tenant.phone
        if recipient:
            send_sms(recipient, content)

    log = CommunicationLog(
        landlord_id    = landlord_id,
        message_type   = channel,
        recipient_type = RecipientType.tenant.value,
        tenant_id      = tenant.id,
        content        = content,
        status         = CommunicationStatus.pending.value,
    )
    db.session.add(log)
    return log


def _get_or_404(landlord_id: int, template_id: int) -> DocumentTemplate:
    t = DocumentTemplate.query.filter_by(id=template_id, landlord_id=landlord_id).first()
    if not t:
        abort(404, description="Document template not found.")
    return t