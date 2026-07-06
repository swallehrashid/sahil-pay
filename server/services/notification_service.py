"""
SahilPay — services/notification_service.py
==============================================
Single chokepoint for creating in-app notifications, mirroring
services/audit_service.py's pattern: real DB writes, no commit (the
caller commits in its own transaction so a notification never persists
without the event that triggered it).

A "send" to many recipients fans out into one Notification row per
recipient — each tenant/team member's read state is independent even
though they all share the same category/title/body.

TEMPLATES is a lightweight Python registry rather than a DB table —
each entry is rendered with **kwargs via str.format(), matching the
{placeholder} convention already used by services/communication_service.py's
message templates.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


TEMPLATES = {
    "payment_received": {
        "title": "Payment received",
        "body": "A payment of KES {amount} was received from {tenant_name} ({unit_name}).",
    },
    "new_maintenance_request": {
        "title": "New maintenance request",
        "body": "{tenant_name} raised a maintenance request: \"{summary}\" ({category}).",
    },
    "trial_expiring": {
        "title": "Your trial is ending soon",
        "body": "Your SahilPay trial ends on {trial_ends_at}. Upgrade to keep using your account without interruption.",
    },
    "lease_expiring": {
        "title": "Lease expiring soon",
        "body": "{tenant_name}'s lease on {unit_name} expires on {lease_expiry_date}.",
    },
    "low_sms_balance": {
        "title": "Low SMS balance",
        "body": "Your SMS balance is down to {sms_balance} credits. Top up to keep sending reminders.",
    },
    "team_member_activated": {
        "title": "Team member activated",
        "body": "{member_name} has activated their account and can now log in.",
    },
    "impersonation_requested": {
        "title": "Support access requested",
        "body": "A SahilPay admin ({admin_email}) has requested temporary access to assist your account. Reason: {reason}",
    },
    "impersonation_granted": {
        "title": "Impersonation access granted",
        "body": "{company_name} has granted you access to assist their account.",
    },
    # ---- #11: landlord → tenant / team member templates ------------------
    # These are the only templated messages a landlord (or their team) should be
    # able to SEND. Platform templates above (trial_expiring, low_sms_balance,
    # impersonation_*, etc.) are admin/system → landlord and must never appear in
    # the landlord's "send notification" template picker.
    "balance_reminder": {
        "title": "Balance reminder",
        "body": "This is a reminder about your outstanding balance. Kindly clear it to avoid penalties — log in to your tenant portal to view the details.",
    },
    "payment_update": {
        "title": "Payment update",
        "body": "This is an update regarding your recent payment. Thank you.",
    },
    "utilities_update_reminder": {
        "title": "Utilities reminder",
        "body": "Please submit your latest utility readings for this month.",
    },
    "lease_renewal_reminder": {
        "title": "Lease renewal",
        "body": "Your lease is due for renewal soon. Please get in touch to renew.",
    },
    "add_units_reminder": {
        "title": "Add units reminder",
        "body": "Reminder: please add the outstanding units/records for the properties you manage.",
    },
    "update_utilities_task": {
        "title": "Update utilities",
        "body": "Reminder: please record this month's utilities for your assigned properties.",
    },
    "broadcast": {
        "title": None,   # custom sends always supply their own title/body
        "body": None,
    },
}

# #11 — the subset of TEMPLATES a landlord/team member may send, split by audience.
LANDLORD_TENANT_TEMPLATES = ["balance_reminder", "payment_update", "utilities_update_reminder", "lease_renewal_reminder"]
LANDLORD_TEAM_TEMPLATES = ["add_units_reminder", "update_utilities_task"]
LANDLORD_SENDABLE_TEMPLATES = LANDLORD_TENANT_TEMPLATES + LANDLORD_TEAM_TEMPLATES


class _SafeDict(dict):
    """format_map helper: leaves unknown {placeholders} intact instead of raising."""
    def __missing__(self, key):
        return "{" + key + "}"


def render_template(template_key: str, **kwargs) -> tuple[str, str]:
    """
    Return (title, body) for a template key, formatted with kwargs. Missing
    placeholders are left intact rather than raising (so a landlord-sent template
    with unfilled {tenant_name}/{balance} still renders instead of 500-ing).
    """
    tmpl = TEMPLATES.get(template_key, TEMPLATES["broadcast"])
    safe = _SafeDict(kwargs)
    title = tmpl["title"].format_map(safe) if tmpl["title"] else kwargs.get("title", "Notification")
    body = tmpl["body"].format_map(safe) if tmpl["body"] else kwargs.get("body", "")
    return title, body


def notify(
    recipient_user_id: int,
    category: str,
    title: str | None = None,
    body: str | None = None,
    template_key: str | None = None,
    template_kwargs: dict | None = None,
    sender_user_id: int | None = None,
    landlord_id: int | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
):
    """
    Write one Notification row. Does NOT commit — same contract as
    services/audit_service.record_audit(): call this before your own
    commit() so the notification and the event it describes succeed or
    roll back together.

    Either pass title+body directly, or template_key+template_kwargs to
    render from the registry.
    """
    from extensions import db
    from models import Notification

    if template_key:
        title, body = render_template(template_key, **(template_kwargs or {}))

    note = Notification(
        recipient_user_id=recipient_user_id,
        sender_user_id=sender_user_id,
        landlord_id=landlord_id,
        category=category,
        title=title or "Notification",
        body=body or "",
        link=link,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.session.add(note)
    db.session.flush()
    return note


def notify_many(recipient_user_ids: list[int], category: str, **kwargs) -> list:
    """Fan-out helper — one row per recipient, same category/content."""
    return [
        notify(recipient_user_id=uid, category=category, **kwargs)
        for uid in recipient_user_ids
    ]
