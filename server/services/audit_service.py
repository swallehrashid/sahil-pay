"""
SahilPay — services/audit_service.py
======================================
The single chokepoint every route writes through to log a create/update/
delete. Distinct from utils.audit() — that helper resolves the actor and
landlord_id itself from the current JWT/request context, whereas routes
here already have both values in hand (e.g. an admin acting on a landlord's
behalf needs landlord_id to be the *target* landlord, not the admin's own
scope), so record_audit() takes them explicitly instead of re-deriving them.
"""

from __future__ import annotations

import logging

from flask import request

from utils import to_json_safe, active_impersonation, is_demo_scope

logger = logging.getLogger(__name__)


def _resolve_actor_full_name(user, landlord_id: int | None) -> str | None:
    """
    Best-effort display name for an audit actor from their User profile. When a
    landlord_id is in scope, prefer a profile that belongs to that landlord
    (tenant/team member) so a person who exists under several landlords is never
    mislabeled. Falls back to whatever single profile the user has.
    """
    def _name(profile) -> str | None:
        if not profile:
            return None
        first = getattr(profile, "first_name", "") or ""
        last = getattr(profile, "last_name", "") or ""
        full = f"{first} {last}".strip()
        return full or None

    # Prefer a landlord-scoped profile match when we know the landlord.
    if landlord_id is not None:
        for attr in ("tenant_profile", "team_member_profile", "landlord_profile"):
            profile = getattr(user, attr, None)
            if profile is not None and getattr(profile, "landlord_id", None) == landlord_id:
                name = _name(profile)
                if name:
                    return name

    for attr in ("landlord_profile", "team_member_profile", "admin_profile", "tenant_profile"):
        name = _name(getattr(user, attr, None))
        if name:
            return name
    return None


def record_audit(
    actor_user_id: int | None,
    landlord_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    description: str | None = None,
    before_data: dict | None = None,
    after_data: dict | None = None,
    affected_properties: list | None = None,
    file_url: str | None = None,
    actor_full_name: str | None = None,
    actor_username: str | None = None,
):
    """
    Write one immutable audit_logs row. Does NOT commit — the caller commits
    in the same transaction as the mutation it's auditing, so both succeed
    or both roll back together (mirrors utils.audit()'s contract).

    Returns the AuditLog instance (flushed, so .id is populated) so callers
    that need to reference it immediately (e.g. collecting log ids for a
    bulk-send response) can do so without an explicit commit.
    """
    from extensions import db
    from models import AuditLog, User

    # Mark impersonated actions. record_audit() is the chokepoint for most CRUD
    # routes, so without this an admin operating a granted session would leave
    # unmarked rows. active_impersonation() only resolves when the request
    # carries X-Impersonate-Landlord (or the impersonation JWT claim) AND a
    # matching granted, non-expired request exists — so a direct admin action
    # (suspend, correct-data) is never falsely marked.
    try:
        imp = active_impersonation()
    except Exception:
        imp = None
    if imp is not None:
        prefix = f"[Impersonating landlord #{imp.landlord_id}]"
        description = f"{prefix} {description}" if description else prefix

    # Defense-in-depth: mark demo-scope writes (DEMO_MODE_SPEC.md §3.5) — the
    # shadow landlord's own landlord_id already isolates the row either way.
    if is_demo_scope():
        description = f"[DEMO] {description}" if description else "[DEMO]"

    # Callers that already hold the acting entity (e.g. the tenant-portal routes
    # know exactly which Tenant submitted) may pass actor_full_name/actor_username
    # explicitly. This avoids the profile-walk below, which is ambiguous when one
    # login User owns MULTIPLE profiles of the same kind — a person who is a tenant
    # under several landlords has several tenant_profile rows, and picking the first
    # would mislabel the actor (issue #18: a payment showed the wrong tenant's name).
    if actor_user_id and (actor_username is None or actor_full_name is None):
        try:
            user = db.session.get(User, actor_user_id)
            if user is not None:
                if actor_username is None:
                    actor_username = user.email or user.phone
                if actor_full_name is None:
                    actor_full_name = _resolve_actor_full_name(user, landlord_id)
        except Exception:
            logger.warning("record_audit: could not resolve actor #%s", actor_user_id, exc_info=True)

    ip_address = None
    try:
        ip_address = request.remote_addr
    except RuntimeError:
        pass  # outside request context (e.g. a Celery task)

    log = AuditLog(
        landlord_id=landlord_id,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        actor_full_name=actor_full_name,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        description=description,
        before_data=to_json_safe(before_data) if before_data else None,
        after_data=to_json_safe(after_data) if after_data else None,
        affected_properties=affected_properties,
        file_url=file_url,
        ip_address=ip_address,
    )
    db.session.add(log)
    db.session.flush()
    return log
