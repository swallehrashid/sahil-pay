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

from utils import to_json_safe, active_impersonation

logger = logging.getLogger(__name__)


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

    actor_username = None
    actor_full_name = None
    if actor_user_id:
        try:
            user = db.session.get(User, actor_user_id)
            if user is not None:
                actor_username = user.email or user.phone
                for profile_attr in ("landlord_profile", "team_member_profile", "admin_profile", "tenant_profile"):
                    profile = getattr(user, profile_attr, None)
                    if profile:
                        first = getattr(profile, "first_name", "") or ""
                        last = getattr(profile, "last_name", "") or ""
                        if first or last:
                            actor_full_name = f"{first} {last}".strip()
                            break
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
