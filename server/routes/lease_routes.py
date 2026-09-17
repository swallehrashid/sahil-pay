"""
routes/lease_routes.py — tenancy agreements
Blueprint: lease_bp  |  Prefix: /api

STAFF SIDE (landlord / property manager / permitted team member)
  GET    /leases                          every agreement, filterable
  GET    /leases/document-options         standard / custom / uploaded documents to send
  POST   /leases/send-many                one agreement to several tenants at once
  GET    /tenants/<id>/leases             one tenancy's agreements
  POST   /tenants/<id>/leases             prepare one (JSON, or multipart with a file)
  POST   /leases/<id>/send                send it to the tenant to sign
  GET    /leases/<id>/blank               the unsigned, branded copy (preview / print)
  GET    /leases/<id>/scans/<n>           a page the tenant signed by hand
  POST   /leases/<id>/approve             countersign a submitted lease
  POST   /leases/<id>/reject              return it with a reason
  POST   /tenants/<id>/leases/upload      record a lease signed on paper
  GET    /leases/<id>                     detail, including signature provenance
  GET    /leases/<id>/download            the PDF

TENANT SIDE (every tenancy the signed-in PERSON holds)
  GET    /portal/leases                   all their agreements, action-needed first
  GET    /portal/leases/<id>              one agreement (records first view)
  GET    /portal/leases/<id>/blank        branded copy to print and sign by hand
  POST   /portal/leases/<id>/sign         sign electronically
  POST   /portal/leases/<id>/upload       return hand-signed pages (photos / PDF)
  GET    /portal/leases/<id>/download     the final copy, once approved
  GET    /portal/lease  (+ /submit, /download)   single-lease endpoints, kept for
                                                 older app builds

Permission module: `tenants`. A lease belongs to a tenancy, so whoever may
administer tenants may administer their agreements. Every staff route is
additionally property-scoped, so a caretaker restricted to one block cannot
read or approve another block's agreements.
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    DOWNLOADABLE_LEASE_STATUSES, LeaseAgreement, LeaseStatus,
    TENANT_VISIBLE_LEASE_STATUSES, Tenant,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
)
from utils import success, ApiError, accessible_property_ids
from services import lease_service as leases
from services.audit_service import record_audit

lease_bp = Blueprint("leases", __name__, url_prefix="/api")


def _serialise_dt(value):
    return value.isoformat() if value is not None else None


def _actor_id():
    try:
        return int(get_jwt_identity())
    except (TypeError, ValueError):
        return None


def _client_ip() -> str | None:
    """
    The signer's address. X-Forwarded-For's FIRST entry is the client; the rest
    are proxies. Only trusted behind our own reverse proxy, which is why the
    value is recorded as evidence rather than used for any access decision.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _tenant_or_404(landlord_id: int, tenant_id: int) -> Tenant:
    tenant = (
        db.session.query(Tenant)
        .filter(Tenant.id == tenant_id,
                Tenant.landlord_id == landlord_id,
                Tenant.is_deleted.is_(False))
        .first()
    )
    if tenant is None:
        raise ApiError("Tenant not found.", status=404)

    allowed = accessible_property_ids()
    if allowed is not None:
        unit = tenant.unit
        if unit is None or unit.property_id not in allowed:
            raise ApiError("Tenant not found.", status=404)
    return tenant


def _lease_or_404(landlord_id: int, lease_id: int) -> LeaseAgreement:
    lease = (
        db.session.query(LeaseAgreement)
        .filter_by(id=lease_id, landlord_id=landlord_id)
        .first()
    )
    if lease is None:
        raise ApiError("Lease not found.", status=404)

    allowed = accessible_property_ids()
    if allowed is not None and lease.property_id not in allowed:
        raise ApiError("Lease not found.", status=404)
    return lease


def _send_file_from_url(url: str, download_name: str, inline: bool = False):
    """Stream a stored lease back. Local-disk only — leases are never on a CDN."""
    import os

    from flask import current_app
    from werkzeug.exceptions import NotFound

    relative = (url or "").split("/uploads/", 1)[-1].lstrip("/")
    root = os.path.realpath(os.path.join(current_app.root_path, "uploads"))
    path = os.path.realpath(os.path.join(root, relative))
    if not path.startswith(root + os.sep):
        raise ApiError("The lease file is missing from storage.", status=404)
    if inline and "." in relative.rsplit("/", 1)[-1]:
        download_name = f"{download_name}.{relative.rsplit('.', 1)[-1]}"
    try:
        response = send_file(path, as_attachment=not inline, download_name=download_name)
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except (NotFound, FileNotFoundError):
        raise ApiError("The lease file is missing from storage.", status=404)


def _pdf_response(pdf: bytes, filename: str):
    from flask import Response
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store",
    })


def _body() -> dict:
    """JSON or multipart form — the create/send routes accept both."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    data = request.form.to_dict()
    if "tenant_ids" in request.form:
        data["tenant_ids"] = request.form.getlist("tenant_ids")
        if len(data["tenant_ids"]) == 1:
            data["tenant_ids"] = data["tenant_ids"][0]
    return data


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


# ===========================================================================
# Staff
# ===========================================================================

@lease_bp.route("/leases", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def list_leases():
    """Every agreement on the account, newest first. Filters: ?status= &tenant_id="""
    landlord_id = get_current_landlord_id()
    query = db.session.query(LeaseAgreement).filter_by(landlord_id=landlord_id)

    allowed = accessible_property_ids()
    if allowed is not None:
        query = query.filter(LeaseAgreement.property_id.in_(allowed or {0}))

    if status := request.args.get("status"):
        if status not in {s.value for s in LeaseStatus}:
            raise ApiError("Unknown status filter.", status=422)
        query = query.filter(LeaseAgreement.status == status)
    if tenant_id := request.args.get("tenant_id"):
        query = query.filter(LeaseAgreement.tenant_id == int(tenant_id))

    rows = query.order_by(LeaseAgreement.created_at.desc()).limit(500).all()

    tenants = {
        t.id: f"{t.first_name} {t.last_name}".strip()
        for t in db.session.query(Tenant).filter_by(landlord_id=landlord_id).all()
    }
    items = []
    for lease in rows:
        data = lease.to_dict()
        data["tenant_name"] = tenants.get(lease.tenant_id)
        data["unit_name"] = lease.unit.name if lease.unit else None
        data["property_name"] = lease.property.name if lease.property else None
        items.append(data)

    return success({
        "items": items,
        "count": len(items),
        "awaiting_review": sum(1 for r in rows
                               if r.status == LeaseStatus.submitted.value),
        "with_tenant": sum(1 for r in rows if r.awaiting_tenant),
        "signed": sum(1 for r in rows if r.is_downloadable),
    })


@lease_bp.route("/tenants/<int:tenant_id>/leases", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def tenant_leases(tenant_id: int):
    landlord_id = get_current_landlord_id()
    tenant = _tenant_or_404(landlord_id, tenant_id)
    rows = (
        db.session.query(LeaseAgreement)
        .filter_by(tenant_id=tenant.id)
        .order_by(LeaseAgreement.created_at.desc())
        .all()
    )
    return success({"items": [r.to_dict() for r in rows], "count": len(rows)})


@lease_bp.route("/tenants/<int:tenant_id>/leases", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def create_lease(tenant_id: int):
    """
    Prepare an agreement.

    JSON:      { document_kind?: standard|custom|uploaded, template_id?, title?, send? }
    Multipart: file (the lease document to send), title?, send?
    """
    landlord_id = get_current_landlord_id()
    tenant = _tenant_or_404(landlord_id, tenant_id)
    body = _body()

    lease = leases.create_for_tenant(
        tenant, template_id=body.get("template_id") or None, actor_user_id=_actor_id(),
        document_kind=body.get("document_kind"), upload=request.files.get("file"),
        title=body.get("title"),
    )
    send = _truthy(body.get("send"))
    if send:
        leases.send_to_tenant(lease, actor_user_id=_actor_id())

    record_audit(
        _actor_id(), landlord_id, "create_lease", "lease", lease.id,
        f"Lease ({lease.document_kind}) prepared for {tenant.first_name} {tenant.last_name}"
        + (" and sent to them." if send else "."),
    )
    db.session.commit()

    if send:
        _tell_tenant_lease_sent(lease)
    return success(lease.to_dict(include_body=True), status=201)


@lease_bp.route("/leases/send-many", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def send_many():
    """
    One agreement to several tenancies. Body (JSON or multipart):
      tenant_ids: [..] (or comma-separated), document_kind?, template_id?, title?, file?

    Each tenant gets their OWN lease, filled from their own tenancy. An uploaded
    file is stored once and shared, not re-uploaded per tenant.
    """
    landlord_id = get_current_landlord_id()
    body = _body()
    raw_ids = body.get("tenant_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [x for x in raw_ids.split(",") if x.strip()]
    try:
        tenant_ids = sorted({int(x) for x in raw_ids})
    except (TypeError, ValueError):
        raise ApiError("tenant_ids must be numbers.", status=422)
    if not tenant_ids:
        raise ApiError("Choose at least one tenant.", status=422, errors={"tenant_ids": "required"})
    if len(tenant_ids) > 200:
        raise ApiError("Send to at most 200 tenants at a time.", status=422)

    tenants = [_tenant_or_404(landlord_id, tid) for tid in tenant_ids]

    upload = request.files.get("file")
    shared_template_id = body.get("template_id") or None
    created = []
    for index, tenant in enumerate(tenants):
        lease = leases.create_for_tenant(
            tenant, template_id=shared_template_id, actor_user_id=_actor_id(),
            document_kind=body.get("document_kind"),
            upload=upload if index == 0 else None, title=body.get("title"),
        )
        if index == 0 and upload is not None:
            shared_source = lease.source_document_url
        elif upload is not None:
            from models import LeaseDocumentKind
            lease.document_kind = LeaseDocumentKind.uploaded.value
            lease.source_document_url = shared_source
            lease.body_html = None
        leases.send_to_tenant(lease, actor_user_id=_actor_id())
        created.append(lease)

    record_audit(_actor_id(), landlord_id, "send_leases", "lease", created[0].id,
                 f"Lease sent to {len(created)} tenant(s).")
    db.session.commit()
    for lease in created:
        _tell_tenant_lease_sent(lease)
    return success({"items": [l.to_dict() for l in created], "count": len(created)},
                   message=f"Sent to {len(created)} tenant(s).", status=201)


@lease_bp.route("/leases/document-options", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def document_options():
    """What can be sent: the standard agreement, written templates, uploaded files."""
    from models import DocumentTemplate

    landlord_id = get_current_landlord_id()
    rows = (db.session.query(DocumentTemplate)
            .filter_by(landlord_id=landlord_id)
            .order_by(DocumentTemplate.created_at.desc()).all())
    custom = [{"id": t.id, "name": t.name, "document_type": t.document_type}
              for t in rows if t.content]
    uploaded = [{"id": t.id, "name": t.name, "document_type": t.document_type}
                for t in rows if not t.content and t.file_url]
    return success({
        "standard": {"name": "Sahil Pay standard tenancy agreement",
                     "description": "A complete Kenyan residential tenancy agreement, filled in from each tenancy."},
        "custom": custom,
        "uploaded": uploaded,
    })


@lease_bp.route("/leases/<int:lease_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def lease_detail(lease_id: int):
    """Full detail INCLUDING the signature's provenance — staff only."""
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    return success(lease.to_audit_dict())


@lease_bp.route("/leases/<int:lease_id>/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def send_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    leases.send_to_tenant(lease, actor_user_id=_actor_id())

    record_audit(_actor_id(), landlord_id, "send_lease", "lease", lease.id,
                 "Lease sent to the tenant to sign.")
    db.session.commit()

    _tell_tenant_lease_sent(lease)
    return success(lease.to_dict(), message="Sent to the tenant.")


@lease_bp.route("/leases/<int:lease_id>/approve", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def approve_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    leases.approve(lease, actor_user_id=_actor_id())

    record_audit(_actor_id(), landlord_id, "approve_lease", "lease", lease.id,
                 f"Lease approved (signed by {lease.signed_name}).",
                 after_data=lease.to_audit_dict())
    db.session.commit()

    _notify_tenant(lease, "Your lease has been approved",
                   "Your tenancy agreement has been approved. Download your final "
                   "copy from Leases in your portal.")
    return success(lease.to_dict(), message="Lease approved.")


@lease_bp.route("/leases/<int:lease_id>/reject", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def reject_lease(lease_id: int):
    """Body: { reason }. The reason is required — see the service."""
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    reason = (request.get_json(silent=True) or {}).get("reason")
    leases.reject(lease, reason=reason, actor_user_id=_actor_id())

    record_audit(_actor_id(), landlord_id, "reject_lease", "lease", lease.id,
                 f"Lease returned to the tenant: {lease.rejection_reason}")
    db.session.commit()

    _notify_tenant(lease, "Your lease needs a correction",
                   f"Please review and resubmit your tenancy agreement. "
                   f"Note from your landlord: {lease.rejection_reason}")
    return success(lease.to_dict(), message="Returned to the tenant.")


@lease_bp.route("/tenants/<int:tenant_id>/leases/upload", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "edit")
def upload_lease(tenant_id: int):
    """
    Record a lease signed on paper — one PDF, or a photo of the signed pages.

    Goes straight to `uploaded`: a person witnessed the signing, so there is
    nothing left to review.
    """
    landlord_id = get_current_landlord_id()
    tenant = _tenant_or_404(landlord_id, tenant_id)

    file = request.files.get("file")
    if file is None or not file.filename:
        raise ApiError("Choose the signed lease to upload.", status=422,
                       errors={"file": "required"})

    lease = leases.attach_scan(tenant, file, actor_user_id=_actor_id(),
                               filename=file.filename)
    record_audit(_actor_id(), landlord_id, "upload_lease", "lease", lease.id,
                 f"Signed lease uploaded for {tenant.first_name} {tenant.last_name}.")
    db.session.commit()
    return success(lease.to_dict(), message="Signed lease stored.", status=201)


@lease_bp.route("/leases/<int:lease_id>/download", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def download_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    # Staff may open a SUBMITTED lease too — that is how it gets reviewed.
    reviewable = lease.status == LeaseStatus.submitted.value and lease.document_url
    if not (lease.is_downloadable or reviewable):
        raise ApiError("This lease is not signed yet.", status=409)
    return _send_file_from_url(lease.document_url, f"lease-{lease.tenant_id}.pdf")


@lease_bp.route("/leases/<int:lease_id>/blank", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def staff_blank_lease(lease_id: int):
    """The unsigned, branded copy — exactly what the tenant downloads to print."""
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    return _pdf_response(leases.render_blank_pdf(lease), f"lease-{lease.id}-unsigned.pdf")


@lease_bp.route("/leases/<int:lease_id>/scans/<int:index>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("leases", "view")
def staff_scan_page(lease_id: int, index: int):
    """One page the tenant signed by hand and uploaded, for review."""
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    pages = lease.tenant_scan_urls or []
    if index < 0 or index >= len(pages):
        raise ApiError("No such page.", status=404)
    return _send_file_from_url(pages[index], f"lease-{lease.id}-page-{index + 1}", inline=True)


def _notify_tenant(lease, title: str, body: str) -> None:
    """
    Put a notification on the TENANT's bell. Never breaks the request.

    Addressed by recipient_tenant_id. This used to require tenant.user_id and
    return early without one — but tenants sign in with a phone code and have
    no User row, so NO tenant ever received a lease notification: the office saw
    "with the tenant" while the tenant's portal showed nothing at all.
    """
    from services.notification_service import notify

    tenant = lease.tenant
    if tenant is None:
        return
    try:
        notify(recipient_user_id=None, recipient_tenant_id=tenant.id, category="lease",
               title=title, body=body, landlord_id=lease.landlord_id,
               link=f"/portal/leases/{lease.id}", entity_type="lease", entity_id=lease.id)
        db.session.commit()
    except Exception:                                  # noqa: BLE001
        db.session.rollback()


def _tell_tenant_lease_sent(lease) -> None:
    """
    A lease was sent: bell + SMS + email, so the tenant hears about it wherever
    they look. SMS and email go through dispatch_message (billed, logged, in the
    landlord's identity). Delivery problems are logged, never raised — the lease
    is already sent and must stay sent.
    """
    import logging

    from flask import current_app

    company = getattr(lease.landlord, "company_name", None) or "Your landlord"
    unit = lease.unit.name if lease.unit else None
    what = f"for Unit {unit}" if unit else "for your home"
    _notify_tenant(lease, "You have a lease to sign",
                   f"{company} has sent you a tenancy agreement {what}. Open Leases to read "
                   "it, then sign in the portal or download, sign on paper and upload it.")

    tenant = lease.tenant
    if tenant is None:
        return
    link = f"{current_app.config.get('FRONTEND_URL', '').rstrip('/')}/portal/leases/{lease.id}"
    try:
        from services.communication_service import dispatch_message
        if tenant.phone:
            dispatch_message(
                landlord_id=lease.landlord_id, tenant=tenant, channel="sms",
                content=(f"Hi {tenant.first_name}, {company} has sent you a tenancy agreement {what} "
                         f"to sign. Log in to your tenant portal: {link}"),
            )
        if tenant.email:
            from services import email_templates as T
            from services.document_brand import email_brand
            html = T.render_email(
                brand=email_brand(lease.landlord),
                heading="Your tenancy agreement is ready to sign",
                intro=f"Hi {T.escape(tenant.first_name or 'there')},",
                blocks=[
                    T.paragraph(f"{T.escape(company)} has sent you a tenancy agreement {T.escape(what)}."),
                    T.steps([
                        "Open your tenant portal and go to <strong>Leases</strong>.",
                        "Read the agreement through.",
                        "Sign it in the portal — or download it, sign on paper, and upload a photo or scan.",
                        "Your landlord reviews it, and you can both download the final copy.",
                    ]),
                    T.button("Open my lease", link),
                ],
                preheader=f"{company} sent you a tenancy agreement to sign.",
            )
            dispatch_message(landlord_id=lease.landlord_id, tenant=tenant, channel="email",
                             content=f"{company} has sent you a tenancy agreement to sign: {link}",
                             email_subject=f"{company}: your tenancy agreement is ready to sign",
                             email_html=html)
        db.session.commit()
    except Exception:                                  # noqa: BLE001
        db.session.rollback()
        logging.getLogger(__name__).exception("Lease %s: SMS/email to tenant failed.", lease.id)


def _notify_staff(lease, title: str, body: str) -> None:
    """
    Tell the office a lease needs them: the landlord through their alert
    settings, and every active team member who can edit leases on that property
    (a secretary or caretaker doing the reviewing) on their bell.
    """
    from models import TeamMember, TeamMemberPermission, TeamMemberPropertyAccess
    from services.alert_service import dispatch_alert
    from services.notification_service import notify

    try:
        dispatch_alert(lease.landlord_id, "lease", title=title, body=body,
                       link="/landlord/leases", entity_type="lease", entity_id=lease.id)
        members = (
            db.session.query(TeamMember)
            .join(TeamMemberPermission, TeamMemberPermission.team_member_id == TeamMember.id)
            .filter(TeamMember.landlord_id == lease.landlord_id,
                    TeamMember.is_active.is_(True),
                    TeamMemberPermission.module.in_(("leases", "tenants")),
                    TeamMemberPermission.can_edit.is_(True))
            .distinct().all()
        )
        for member in members:
            scoped = db.session.query(TeamMemberPropertyAccess.property_id).filter_by(
                team_member_id=member.id).all()
            if scoped and lease.property_id not in {pid for (pid,) in scoped}:
                continue
            notify(recipient_user_id=member.user_id, category="lease", title=title, body=body,
                   landlord_id=lease.landlord_id, link="/team/leases",
                   entity_type="lease", entity_id=lease.id)
        db.session.commit()
    except Exception:                                  # noqa: BLE001
        db.session.rollback()


# ===========================================================================
# Tenant portal
# ===========================================================================

def _portal_tenant() -> Tenant:
    """
    The signed-in tenant, resolved by the portal's own helper.

    Reused rather than reimplemented: that helper also honours the multi-unit
    switcher's X-Tenant-Id header, and ONLY for tenancies belonging to the same
    person. Rolling our own here would quietly drop that check and turn the
    header into a way to read any tenant's lease by guessing an id.
    """
    from routes.tenant_portal_routes import _get_portal_tenant

    tenant, _ = _get_portal_tenant()
    if tenant is None:
        raise ApiError("Tenant session required.", status=403)
    return tenant


@lease_bp.route("/portal/lease", methods=["GET"])
@jwt_required()
def portal_lease():
    """
    The agreement this tenant must sign, or the one they already signed.

    A draft is invisible: a lease the landlord has not yet sent is not the
    tenant's business, and showing it invites arguments about which version is
    binding.
    """
    tenant = _portal_tenant()

    # The copy they may keep, resolved SEPARATELY from the one they must act
    # on. During a renewal those are two different documents: the lease that
    # matters is the unsigned one, but the lease they can still download is
    # last year's signed agreement. Reporting is_downloadable off the current
    # lease alone withdrew that copy the moment a renewal went out — the
    # download endpoint would happily have served it, but the portal stopped
    # offering the button.
    settled = leases.latest_downloadable_for_tenant(tenant.id)
    signed = None
    if settled is not None:
        signed = {
            "id":         settled.id,
            "status":     settled.status,
            "signed_name": settled.signed_name,
            "signed_at":  _serialise_dt(settled.signed_at),
            "reviewed_at": _serialise_dt(settled.reviewed_at),
        }

    lease = leases.current_for_tenant(tenant.id)
    if lease is None or lease.status not in TENANT_VISIBLE_LEASE_STATUSES:
        return success({"lease": None, "signed_copy": signed})

    data = lease.to_dict(include_body=True)
    data["can_sign"] = lease.awaiting_tenant
    return success({"lease": data, "signed_copy": signed})


@lease_bp.route("/portal/lease/submit", methods=["POST"])
@jwt_required()
def portal_submit_lease():
    """
    Fill in, sign and submit. Body: { signed_name, agreed: true, field_values? }

    `agreed` is a separate, explicit act from typing a name: the name alone
    could be a half-finished form, whereas the tick is the consent being
    recorded.
    """
    tenant = _portal_tenant()
    body = request.get_json(silent=True) or {}

    lease = leases.current_for_tenant(tenant.id)
    if lease is None or not lease.awaiting_tenant:
        raise ApiError("There is no lease waiting for your signature.", status=409)

    if not body.get("agreed"):
        raise ApiError("Tick the box to confirm you agree to the terms.",
                       status=422, errors={"agreed": "required"})

    leases.submit(
        lease,
        signed_name=body.get("signed_name"),
        field_values=body.get("field_values") or {},
        ip=_client_ip(),
        user_agent=request.headers.get("User-Agent"),
    )

    record_audit(None, lease.landlord_id, "submit_lease", "lease", lease.id,
                 f"Tenant {lease.signed_name} signed and submitted their lease.",
                 after_data=lease.to_audit_dict())
    db.session.commit()

    _notify_staff(lease, "A lease is ready for review",
                  f"{lease.signed_name} has signed their tenancy agreement.")
    return success(lease.to_dict(), message="Signed and sent for review.")


@lease_bp.route("/portal/lease/download", methods=["GET"])
@jwt_required()
def portal_download_lease():
    """
    The tenant's own copy, once it is settled.

    Resolved by latest_downloadable_for_tenant(), NOT current_for_tenant(): when
    a renewal has been sent, the lease that "matters now" is the unsigned one,
    but the copy they can still download is the signed agreement they already
    have. Going through current_for_tenant() would withdraw that copy the moment
    a renewal went out.
    """
    tenant = _portal_tenant()
    lease = leases.latest_downloadable_for_tenant(tenant.id)
    if lease is None:
        raise ApiError("Your lease is not available to download yet.", status=409)
    if not lease.document_url:
        raise ApiError("Your lease file is missing. Please contact your landlord.",
                       status=404)
    return _send_file_from_url(lease.document_url, "tenancy-agreement.pdf")


# ---------------------------------------------------------------------------
# Tenant portal — every agreement the person holds
# ---------------------------------------------------------------------------

def _portal_person_lease(lease_id: int) -> LeaseAgreement:
    """
    A lease belonging to ANY tenancy of the signed-in person, or 404.

    SECURITY: resolved against leases_for_person() — the same sibling set the
    unit switcher is authorised by — so guessing another tenant's lease id
    returns exactly what a missing id returns.
    """
    tenant = _portal_tenant()
    for lease in leases.leases_for_person(tenant):
        if lease.id == lease_id:
            return lease
    raise ApiError("Lease not found.", status=404)


def _portal_item(lease: LeaseAgreement, include_body: bool = False) -> dict:
    data = lease.to_dict(include_body=include_body)
    data.pop("document_url", None)          # files are fetched through the API only
    data["unit_name"] = lease.unit.name if lease.unit else None
    data["property_name"] = lease.property.name if lease.property else None
    data["landlord_name"] = getattr(lease.landlord, "company_name", None)
    data["can_sign"] = lease.awaiting_tenant
    data["can_download_blank"] = lease.awaiting_tenant or lease.status == LeaseStatus.submitted.value
    return data


@lease_bp.route("/portal/leases", methods=["GET"])
@jwt_required()
def portal_leases():
    tenant = _portal_tenant()
    rows = leases.leases_for_person(tenant)
    items = [_portal_item(r) for r in rows]
    return success({
        "items": items,
        "count": len(items),
        "action_needed": sum(1 for r in rows if r.awaiting_tenant),
        "in_review": sum(1 for r in rows if r.status == LeaseStatus.submitted.value),
    })


@lease_bp.route("/portal/leases/<int:lease_id>", methods=["GET"])
@jwt_required()
def portal_lease_detail(lease_id: int):
    lease = _portal_person_lease(lease_id)
    if leases.mark_viewed(lease):
        db.session.commit()
    return success(_portal_item(lease, include_body=True))


@lease_bp.route("/portal/leases/<int:lease_id>/blank", methods=["GET"])
@jwt_required()
def portal_lease_blank(lease_id: int):
    """The branded copy to print, sign by hand and upload back."""
    lease = _portal_person_lease(lease_id)
    if leases.mark_viewed(lease):
        db.session.commit()
    return _pdf_response(leases.render_blank_pdf(lease), "tenancy-agreement-to-sign.pdf")


@lease_bp.route("/portal/leases/<int:lease_id>/sign", methods=["POST"])
@jwt_required()
def portal_lease_sign(lease_id: int):
    """Sign electronically. Body: { signed_name, agreed: true }"""
    lease = _portal_person_lease(lease_id)
    if not lease.awaiting_tenant:
        raise ApiError("This lease is not waiting for your signature.", status=409)
    body = request.get_json(silent=True) or {}
    if not body.get("agreed"):
        raise ApiError("Tick the box to confirm you agree to the terms.",
                       status=422, errors={"agreed": "required"})
    leases.submit(lease, signed_name=body.get("signed_name"), field_values=body.get("field_values") or {},
                  ip=_client_ip(), user_agent=request.headers.get("User-Agent"))
    record_audit(None, lease.landlord_id, "submit_lease", "lease", lease.id,
                 f"Tenant {lease.signed_name} signed their lease electronically.",
                 after_data=lease.to_audit_dict())
    db.session.commit()
    _notify_staff(lease, "A lease is ready for review",
                  f"{lease.signed_name} signed their tenancy agreement in the portal.")
    return success(_portal_item(lease), message="Signed and sent to your landlord for review.")


@lease_bp.route("/portal/leases/<int:lease_id>/upload", methods=["POST"])
@jwt_required()
def portal_lease_upload(lease_id: int):
    """
    Return a hand-signed copy. Multipart: files (one per page, or one PDF),
    signed_name, agreed=true.
    """
    lease = _portal_person_lease(lease_id)
    if not lease.awaiting_tenant:
        raise ApiError("This lease is not waiting for your signature.", status=409)
    if not _truthy(request.form.get("agreed")):
        raise ApiError("Tick the box to confirm these are the pages you signed.",
                       status=422, errors={"agreed": "required"})
    files = request.files.getlist("files") or request.files.getlist("file")
    leases.submit_scan(lease, files, signed_name=request.form.get("signed_name"),
                       ip=_client_ip(), user_agent=request.headers.get("User-Agent"))
    record_audit(None, lease.landlord_id, "submit_lease_scan", "lease", lease.id,
                 f"Tenant {lease.signed_name} uploaded {len(lease.tenant_scan_urls or [])} "
                 "hand-signed page(s).", after_data=lease.to_audit_dict())
    db.session.commit()
    _notify_staff(lease, "A signed lease was uploaded for review",
                  f"{lease.signed_name} signed their tenancy agreement on paper and uploaded "
                  f"{len(lease.tenant_scan_urls or [])} page(s).")
    return success(_portal_item(lease), message="Uploaded and sent to your landlord for review.")


@lease_bp.route("/portal/leases/<int:lease_id>/download", methods=["GET"])
@jwt_required()
def portal_lease_download(lease_id: int):
    lease = _portal_person_lease(lease_id)
    if not lease.is_downloadable:
        raise ApiError("Your lease can be downloaded once your landlord approves it.", status=409)
    return _send_file_from_url(lease.document_url, "tenancy-agreement.pdf")
