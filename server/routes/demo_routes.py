"""
routes/demo_routes.py — Demo Mode
Blueprint: demo_bp  |  Prefix: /api/demo

See DEMO_MODE_SPEC.md. Lets a landlord/PM turn on a fully interactive,
pre-filled "practice" copy of the portal (a hidden shadow Landlord) without
touching their real account. These routes are the only place that manages
the shadow's lifecycle — everywhere else, entering demo mode is just a
request header (X-Demo-Mode: 1) that utils.current_landlord_id() resolves
to the shadow's id.

IMPORTANT: every handler here resolves the caller's REAL landlord directly
from their JWT profile — never through the demo-aware current_landlord_id()
resolver — because these routes manage the shadow itself, they don't operate
inside it.
"""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from extensions import db
from utils import get_jwt_user, ApiError
from decorators import require_role
from services.audit_service import record_audit
from services.demo_service import ensure_demo_landlord, reset_demo_data, get_demo_shadow

demo_bp = Blueprint("demo", __name__, url_prefix="/api/demo")


def _real_landlord():
    user = get_jwt_user()
    if user.landlord_profile is None:
        raise ApiError("This action requires a landlord account.", status=403, code="no_landlord_scope")
    return user.landlord_profile


# ---------------------------------------------------------------------------
# GET /api/demo/status
# ---------------------------------------------------------------------------
@demo_bp.route("/status", methods=["GET"])
@jwt_required()
@require_role("landlord", "property_manager")
def demo_status():
    """
    Whether this landlord already has a demo shadow, and when it was
    created/last reset. Used by the frontend to skip re-seeding on re-entry.
    ---
    tags: [Demo Mode]
    security:
      - Bearer: []
    responses:
      200: {description: Demo shadow status.}
    """
    landlord = _real_landlord()
    shadow = get_demo_shadow(landlord.id)
    return jsonify({
        "exists":         shadow is not None,
        "created_at":     shadow.demo_created_at.isoformat() if shadow and shadow.demo_created_at else None,
        "last_reset_at":  shadow.demo_last_reset_at.isoformat() if shadow and shadow.demo_last_reset_at else None,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/demo/enter
# ---------------------------------------------------------------------------
@demo_bp.route("/enter", methods=["POST"])
@jwt_required()
@require_role("landlord", "property_manager")
def demo_enter():
    """
    Idempotent. Creates + seeds the shadow landlord on first call; a repeat
    call is a no-op that just confirms readiness. The frontend calls this
    BEFORE setting X-Demo-Mode locally, so demo mode never activates without
    a shadow behind it.
    ---
    tags: [Demo Mode]
    security:
      - Bearer: []
    responses:
      200: {description: Demo shadow ready.}
    """
    landlord = _real_landlord()
    shadow = ensure_demo_landlord(landlord)

    record_audit(
        actor_user_id=get_jwt_user().id,
        landlord_id=landlord.id,
        action="demo_mode_entered",
        entity_type="landlord",
        entity_id=landlord.id,
        description="Entered demo mode.",
    )
    db.session.commit()

    return jsonify({"ready": True}), 200


# ---------------------------------------------------------------------------
# POST /api/demo/exit
# ---------------------------------------------------------------------------
@demo_bp.route("/exit", methods=["POST"])
@jwt_required()
@require_role("landlord", "property_manager")
def demo_exit():
    """
    Audit-only — the frontend clears its own local demo flag regardless of
    this response, so exiting can never get a landlord "stuck" in demo mode.
    ---
    tags: [Demo Mode]
    security:
      - Bearer: []
    responses:
      200: {description: Exit recorded.}
    """
    landlord = _real_landlord()

    record_audit(
        actor_user_id=get_jwt_user().id,
        landlord_id=landlord.id,
        action="demo_mode_exited",
        entity_type="landlord",
        entity_id=landlord.id,
        description="Exited demo mode.",
    )
    db.session.commit()

    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# POST /api/demo/reset
# ---------------------------------------------------------------------------
@demo_bp.route("/reset", methods=["POST"])
@jwt_required()
@require_role("landlord", "property_manager")
def demo_reset():
    """
    Wipes every row scoped to this landlord's demo shadow and reseeds it
    from scratch. 404 if no shadow exists yet (call /enter first).
    ---
    tags: [Demo Mode]
    security:
      - Bearer: []
    responses:
      200: {description: Demo data reset.}
      404: {description: No demo shadow exists for this landlord.}
    """
    landlord = _real_landlord()
    if get_demo_shadow(landlord.id) is None:
        return jsonify({"error": "Demo mode has not been entered yet."}), 404

    reset_demo_data(landlord)

    record_audit(
        actor_user_id=get_jwt_user().id,
        landlord_id=landlord.id,
        action="demo_mode_reset",
        entity_type="landlord",
        entity_id=landlord.id,
        description="Reset demo data.",
    )
    db.session.commit()

    return jsonify({"ok": True}), 200
