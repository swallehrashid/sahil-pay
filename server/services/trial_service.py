"""
SahilPay — services/trial_service.py
=======================================
§10.4  Applies the platform's global trial configuration to a newly
registered landlord. Per-landlord overrides (extend/reduce/revoke/activate)
are admin actions handled directly in routes/admin_trial_routes.py — this
module only covers the "apply the current global default" path used at
registration time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import current_app

logger = logging.getLogger(__name__)


def apply_global_trial(landlord) -> None:
    """
    Set landlord.is_on_trial / landlord.trial_ends_at from the active global
    TrialConfig row (scope="global", is_active=True). Falls back to
    config.DEFAULT_TRIAL_DAYS if no such row exists yet (e.g. first boot,
    before an admin has configured one). Does not commit — called from
    auth_routes.py's registration flow inside the same transaction that
    creates the User/Landlord rows.
    """
    from extensions import db
    from models import TrialConfig

    global_config = (
        db.session.query(TrialConfig)
        .filter(TrialConfig.scope == "global", TrialConfig.is_active.is_(True))
        .first()
    )

    if global_config is not None:
        duration_days = global_config.duration_days
    else:
        duration_days = current_app.config.get("DEFAULT_TRIAL_DAYS", 30)
        logger.info("apply_global_trial: no active global TrialConfig found, using default of %s days.", duration_days)

    landlord.is_on_trial = True
    landlord.trial_ends_at = datetime.utcnow() + timedelta(days=duration_days)
    db.session.add(landlord)


def expire_due_trials(now: datetime | None = None) -> dict:
    """
    End every trial whose ``trial_ends_at`` has passed: flip
    ``landlord.is_on_trial`` to False, transition the subscription out of the
    "trial" status into "active" (so normal billing takes over), notify the
    landlord, and write an audit row per landlord.

    This is the enforcement half of §10.4 — without it a trial never ends.
    Idempotent: only landlords still flagged ``is_on_trial=True`` with an
    elapsed ``trial_ends_at`` are touched, so re-running is a no-op.

    Called by ``tasks.admin_tasks.check_trial_expirations`` (daily) and safe to
    invoke manually. Commits once at the end; returns {"count", "landlord_ids"}.
    """
    from extensions import db
    from models import Landlord, SubscriptionStatus, User, UserRole
    from services.audit_service import record_audit
    from services.notification_service import notify

    now = now or datetime.utcnow()

    # audit_logs.actor_user_id is NOT NULL, so system-initiated actions are
    # attributed to the platform system admin (the closest thing to a
    # "system" actor). If somehow none exists, we still expire trials but
    # skip the audit row rather than crash the whole batch.
    system_actor = db.session.query(User.id).filter(
        User.role == UserRole.system_admin.value
    ).order_by(User.id).first()
    system_actor_id = system_actor[0] if system_actor else None

    due = (
        db.session.query(Landlord)
        .filter(
            # A demo shadow is scaffolding, not a customer — it is never billed
            # and must never be "expired" or notified (DEMO_MODE_SPEC.md §3.4).
            Landlord.is_demo.is_(False),
            Landlord.is_on_trial.is_(True),
            Landlord.trial_ends_at.isnot(None),
            Landlord.trial_ends_at <= now,
        )
        .all()
    )

    expired_ids = []
    for landlord in due:
        before = {"is_on_trial": landlord.is_on_trial,
                  "subscription_status": landlord.subscription.status if landlord.subscription else None}

        landlord.is_on_trial = False
        if landlord.subscription and landlord.subscription.status == SubscriptionStatus.trial.value:
            landlord.subscription.status = SubscriptionStatus.active.value

        if system_actor_id is not None:
            record_audit(
                actor_user_id=system_actor_id,   # platform system admin as system actor
                landlord_id=landlord.id,
                action="trial_expired",
                entity_type="account",
                entity_id=landlord.id,
                description=(
                    f"Automated: trial ended for landlord {landlord.id} "
                    f"({landlord.company_name}); subscription moved to active billing."
                ),
                before_data=before,
                after_data={"is_on_trial": False,
                            "subscription_status": landlord.subscription.status if landlord.subscription else None},
            )

        if landlord.user_id:
            notify(
                recipient_user_id=landlord.user_id,
                category="trial_expiring",
                title="Your trial has ended",
                body="Your SahilPay free trial has ended. Please settle your subscription to keep your account fully active.",
                landlord_id=landlord.id,
                link="/landlord/settings/billing",
                entity_type="account",
                entity_id=landlord.id,
            )

        expired_ids.append(landlord.id)

    db.session.commit()
    logger.info("expire_due_trials: expired %s trial(s): %s", len(expired_ids), expired_ids)
    return {"count": len(expired_ids), "landlord_ids": expired_ids}
