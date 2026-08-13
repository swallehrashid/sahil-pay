"""
routes/admin_trial_routes.py — Trial Configuration (Global + Per-Landlord)
Blueprint: admin_trial_bp  |  Prefix: /api/admin/trials

Two levels of trial configuration:

1. Global (scope='global', one row in trial_configs):
   - duration_days  — default for new signups
   - is_active      — whether new accounts get a trial at all

2. Per-landlord override (scope='per_landlord', landlord_id set):
   - One row per landlord; supersedes the global config for that account.
   - Admin can extend, reduce, revoke, or grant a fresh trial.

The partial unique index on trial_configs ensures exactly one global row
and at most one per-landlord override row (UniqueConstraint on landlord_id).

Celery Beat reads these settings when running the trial-expiration check job.
The service layer (apply_global_trial) is called at landlord registration.
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import TrialConfig, Landlord, UserRole, TrialScope
from services.audit_service import record_audit

admin_trial_bp = Blueprint("admin_trials", __name__, url_prefix="/api/admin/trials")


def _require_admin():
    """Admin gate — delegates to the ONE shared implementation, which also
    enforces two-factor authentication (decorators.require_system_admin)."""
    from decorators import require_system_admin

    require_system_admin()

def _admin_id() -> int:
    return int(get_jwt_identity())


# ---------------------------------------------------------------------------
# GET /api/admin/trials/global
# ---------------------------------------------------------------------------
@admin_trial_bp.route("/global", methods=["GET"])
@jwt_required()
def get_global_trial():
    """
    Return the single global trial configuration row.
    Creates it with defaults (30 days, active) if it has never been set.
    ---
    tags: [Admin — Trials]
    security:
      - Bearer: []
    responses:
      200: {description: Global trial config.}
    """
    _require_admin()
    config = _get_or_create_global_config()
    return jsonify(config.to_dict()), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/trials/global
# ---------------------------------------------------------------------------
@admin_trial_bp.route("/global", methods=["PUT"])
@jwt_required()
def update_global_trial():
    """
    Update the platform-wide default trial settings.
    Body: { duration_days?: int, is_active?: bool }

    Changing duration_days does NOT retroactively adjust existing landlords'
    trial_ends_at — it only affects new signups from this point forward.
    To adjust an existing landlord, use PUT /api/admin/trials/landlords/<id>.
    ---
    tags: [Admin — Trials]
    security:
      - Bearer: []
    responses:
      200: {description: Global trial settings updated.}
      400: {description: Validation error.}
    """
    _require_admin()
    data   = request.get_json(silent=True) or {}
    config = _get_or_create_global_config()
    before = config.to_dict()

    if "duration_days" in data:
        days = int(data["duration_days"])
        if days < 0:
            return jsonify({"error": "duration_days must be >= 0."}), 400
        config.duration_days = days

    if "is_active" in data:
        config.is_active = bool(data["is_active"])

    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=None,
        action="admin_update_global_trial",
        entity_type="account",
        entity_id=config.id,
        description=(
            f"ADMIN: Global trial config updated — "
            f"duration_days={config.duration_days}, is_active={config.is_active}."
        ),
        before_data=before,
        after_data=config.to_dict(),
    )
    db.session.commit()

    return jsonify(config.to_dict()), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/trials/landlords/<id>
# ---------------------------------------------------------------------------
@admin_trial_bp.route("/landlords/<int:landlord_id>", methods=["PUT"])
@jwt_required()
def update_landlord_trial(landlord_id):
    """
    Set or update the per-landlord trial override.

    Body:
      { action: 'extend' | 'reduce' | 'revoke' | 'activate',
        duration_days?: int,   -- required for extend / reduce / activate
        reason: str            -- mandatory for all actions
      }

    Actions:
      extend   — add N more days to trial_ends_at (from today if already expired)
      reduce   — shorten trial_ends_at by N days (minimum = today)
      revoke   — set trial_ends_at = now, is_on_trial = False immediately
      activate — grant a fresh trial of N days starting now

    All changes are audit-logged with the mandatory reason.
    ---
    tags: [Admin — Trials]
    security:
      - Bearer: []
    responses:
      200: {description: Landlord trial updated.}
      400: {description: Invalid action or missing fields.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    data          = request.get_json(silent=True) or {}
    action        = (data.get("action") or "").strip()
    duration_days = data.get("duration_days")
    reason        = (data.get("reason") or "").strip()

    valid_actions = {"extend", "reduce", "revoke", "activate"}
    if action not in valid_actions:
        return jsonify({"error": f"action must be one of: {sorted(valid_actions)}."}), 400
    if not reason:
        return jsonify({"error": "reason is required for all trial actions."}), 400
    if action in {"extend", "reduce", "activate"} and duration_days is None:
        return jsonify({"error": f"duration_days is required for action '{action}'."}), 400

    now    = datetime.utcnow()
    before = {
        "trial_ends_at": landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
        "is_on_trial":   landlord.is_on_trial,
    }

    if action == "extend":
        base           = max(landlord.trial_ends_at or now, now)
        landlord.trial_ends_at = base + timedelta(days=int(duration_days))
        landlord.is_on_trial   = True
        desc = f"Extended trial by {duration_days} days (new end: {landlord.trial_ends_at.date()})."

    elif action == "reduce":
        base           = landlord.trial_ends_at or now
        new_end        = base - timedelta(days=int(duration_days))
        # Can't reduce past today
        landlord.trial_ends_at = max(new_end, now)
        if landlord.trial_ends_at <= now:
            landlord.is_on_trial = False
        desc = f"Reduced trial by {duration_days} days (new end: {landlord.trial_ends_at.date()})."

    elif action == "revoke":
        landlord.trial_ends_at = now
        landlord.is_on_trial   = False
        desc = "Trial revoked immediately."

    elif action == "activate":
        landlord.trial_ends_at = now + timedelta(days=int(duration_days))
        landlord.is_on_trial   = True
        desc = f"Fresh trial of {duration_days} days granted (ends: {landlord.trial_ends_at.date()})."

    # Upsert per-landlord TrialConfig row for Celery Beat reference
    override = TrialConfig.query.filter_by(
        scope=TrialScope.per_landlord.value, landlord_id=landlord.id
    ).first()
    if not override:
        override = TrialConfig(
            scope       = TrialScope.per_landlord.value,
            landlord_id = landlord.id,
            duration_days = int(duration_days) if duration_days is not None else 0,
            is_active   = landlord.is_on_trial,
        )
        db.session.add(override)
    else:
        if duration_days is not None:
            override.duration_days = int(duration_days)
        override.is_active = landlord.is_on_trial

    db.session.commit()

    after = {
        "trial_ends_at": landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
        "is_on_trial":   landlord.is_on_trial,
    }

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord.id,
        action=f"admin_trial_{action}",
        entity_type="landlord",
        entity_id=landlord.id,
        description=f"ADMIN TRIAL [{action.upper()}] for '{landlord.company_name}': {desc} Reason: {reason}",
        before_data=before,
        after_data=after,
    )
    db.session.commit()

    return jsonify({
        "message":         desc,
        "landlord_id":     landlord.id,
        "trial_ends_at":   landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
        "is_on_trial":     landlord.is_on_trial,
        "trial_override":  override.to_dict(),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/trials/landlords/<id>
# ---------------------------------------------------------------------------
@admin_trial_bp.route("/landlords/<int:landlord_id>", methods=["GET"])
@jwt_required()
def get_landlord_trial(landlord_id):
    """
    Return the current trial state for a specific landlord,
    including their per-landlord override row if it exists.
    ---
    tags: [Admin — Trials]
    security:
      - Bearer: []
    responses:
      200: {description: Landlord trial state.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    override = TrialConfig.query.filter_by(
        scope=TrialScope.per_landlord.value, landlord_id=landlord.id
    ).first()

    return jsonify({
        "landlord_id":    landlord.id,
        "company_name":   landlord.company_name,
        "is_on_trial":    landlord.is_on_trial,
        "trial_ends_at":  landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
        "override":       override.to_dict() if override else None,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/trials/expire-due
# ---------------------------------------------------------------------------
@admin_trial_bp.route("/expire-due", methods=["POST"])
@jwt_required()
def run_trial_expiry():
    """
    Manually run the trial-expiration sweep now: end every trial whose
    trial_ends_at has passed (flip is_on_trial, move the subscription to
    active, notify + audit). This is the same routine Celery Beat runs daily;
    exposing it lets an admin force the check without waiting for the schedule.
    ---
    tags: [Admin — Trials]
    security:
      - Bearer: []
    responses:
      200: {description: Number of trials expired.}
    """
    _require_admin()
    from services.trial_service import expire_due_trials

    result = expire_due_trials()
    return jsonify({
        "message":      f"{result['count']} trial(s) expired.",
        "count":        result["count"],
        "landlord_ids": result["landlord_ids"],
    }), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_or_create_global_config() -> TrialConfig:
    """Fetch or bootstrap the single global TrialConfig row."""
    config = TrialConfig.query.filter_by(scope=TrialScope.global_scope.value).first()
    if not config:
        config = TrialConfig(
            scope         = TrialScope.global_scope.value,
            landlord_id   = None,
            duration_days = 30,
            is_active     = True,
        )
        db.session.add(config)
        db.session.commit()
    return config