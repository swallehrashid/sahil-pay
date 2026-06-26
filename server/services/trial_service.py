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
