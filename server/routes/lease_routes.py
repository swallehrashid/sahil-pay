"""
routes/lease_routes.py — tenancy agreements
Blueprint: lease_bp  |  Prefix: /api

STAFF SIDE (landlord / property manager / permitted team member)
  GET    /leases                          every agreement, filterable
  GET    /tenants/<id>/leases             one tenancy's agreements
  POST   /tenants/<id>/leases             prepare one from a template
  POST   /leases/<id>/send                send it to the tenant to sign
  POST   /leases/<id>/approve             countersign a submitted lease
  POST   /leases/<id>/reject              return it with a reason
  POST   /tenants/<id>/leases/upload      record a lease signed on paper
  GET    /leases/<id>                     detail, including signature provenance
  GET    /leases/<id>/download            the PDF

TENANT SIDE (their own tenancy only)
  GET    /portal/lease                    what they must sign, or have signed
  POST   /portal/lease/submit             fill in, sign, submit
  GET    /portal/lease/download           their copy, once it is settled

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


def _send_file_from_url(url: str, download_name: str):
    """Stream a stored lease back. Local-disk only — leases are never on a CDN."""
    import os

    from flask import current_app
    from werkzeug.exceptions import NotFound

    relative = (url or "").split("/uploads/", 1)[-1].lstrip("/")
    path = os.path.join(current_app.root_path, "uploads", relative)
    try:
        return send_file(path, as_attachment=True, download_name=download_name)
    except (NotFound, FileNotFoundError):
        raise ApiError("The lease file is missing from storage.", status=404)


# ===========================================================================
# Staff
# ===========================================================================

@lease_bp.route("/leases", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
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
        items.append(data)

    return success({
        "items": items,
        "count": len(items),
        "awaiting_review": sum(1 for r in rows
                               if r.status == LeaseStatus.submitted.value),
    })


@lease_bp.route("/tenants/<int:tenant_id>/leases", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
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
@require_permission("tenants", "edit")
def create_lease(tenant_id: int):
    """Prepare an agreement. Body: { template_id?, send? }"""
    landlord_id = get_current_landlord_id()
    tenant = _tenant_or_404(landlord_id, tenant_id)
    body = request.get_json(silent=True) or {}

    lease = leases.create_for_tenant(
        tenant, template_id=body.get("template_id"), actor_user_id=_actor_id(),
    )
    if body.get("send"):
        leases.send_to_tenant(lease, actor_user_id=_actor_id())

    record_audit(
        _actor_id(), landlord_id, "create_lease", "lease", lease.id,
        f"Lease prepared for {tenant.first_name} {tenant.last_name}"
        + (" and sent to them." if body.get("send") else "."),
    )
    db.session.commit()
    return success(lease.to_dict(include_body=True), status=201)


@lease_bp.route("/leases/<int:lease_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def lease_detail(lease_id: int):
    """Full detail INCLUDING the signature's provenance — staff only."""
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    return success(lease.to_audit_dict())


@lease_bp.route("/leases/<int:lease_id>/send", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def send_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    leases.send_to_tenant(lease, actor_user_id=_actor_id())

    record_audit(_actor_id(), landlord_id, "send_lease", "lease", lease.id,
                 "Lease sent to the tenant to sign.")
    db.session.commit()
    return success(lease.to_dict(), message="Sent to the tenant.")


@lease_bp.route("/leases/<int:lease_id>/approve", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
def approve_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    leases.approve(lease, actor_user_id=_actor_id())

    record_audit(_actor_id(), landlord_id, "approve_lease", "lease", lease.id,
                 f"Lease approved (signed by {lease.signed_name}).",
                 after_data=lease.to_audit_dict())
    db.session.commit()

    _notify_tenant(lease, "Your lease has been approved",
                   "Your tenancy agreement has been approved. You can download "
                   "your copy from your portal.")
    db.session.commit()
    return success(lease.to_dict(), message="Lease approved.")


@lease_bp.route("/leases/<int:lease_id>/reject", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
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
    db.session.commit()
    return success(lease.to_dict(), message="Returned to the tenant.")


@lease_bp.route("/tenants/<int:tenant_id>/leases/upload", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "edit")
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
@require_permission("tenants", "view")
def download_lease(lease_id: int):
    landlord_id = get_current_landlord_id()
    lease = _lease_or_404(landlord_id, lease_id)
    if not lease.is_downloadable:
        raise ApiError("This lease is not signed yet.", status=409)
    return _send_file_from_url(lease.document_url, f"lease-{lease.tenant_id}.pdf")


def _notify_tenant(lease, title: str, body: str) -> None:
    """Tell the tenant their lease moved. Never breaks the request if it fails."""
    from services.notification_service import notify

    tenant = lease.tenant
    if tenant is None or not tenant.user_id:
        return
    try:
        notify(recipient_user_id=tenant.user_id, category="lease",
               title=title, body=body, landlord_id=lease.landlord_id,
               link="/portal/lease", entity_type="lease", entity_id=lease.id)
    except Exception:                                  # noqa: BLE001
        pass


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
    lease = leases.current_for_tenant(tenant.id)
    if lease is None or lease.status not in TENANT_VISIBLE_LEASE_STATUSES:
        return success({"lease": None})

    data = lease.to_dict(include_body=True)
    data["can_sign"] = lease.awaiting_tenant
    return success({"lease": data})


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

    from services.alert_service import dispatch_alert
    try:
        dispatch_alert(
            lease.landlord_id, "lease", title="A lease is ready for review",
            body=f"{lease.signed_name} has signed their tenancy agreement.",
            link="/landlord/leases", entity_type="lease", entity_id=lease.id,
        )
        db.session.commit()
    except Exception:                                  # noqa: BLE001
        db.session.rollback()

    return success(lease.to_dict(), message="Signed and sent for review.")


@lease_bp.route("/portal/lease/download", methods=["GET"])
@jwt_required()
def portal_download_lease():
    """The tenant's own copy, once it is settled."""
    tenant = _portal_tenant()
    lease = leases.current_for_tenant(tenant.id)
    if lease is None or lease.status not in DOWNLOADABLE_LEASE_STATUSES:
        raise ApiError("Your lease is not available to download yet.", status=409)
    if not lease.document_url:
        raise ApiError("Your lease file is missing. Please contact your landlord.",
                       status=404)
    return _send_file_from_url(lease.document_url, "tenancy-agreement.pdf")
