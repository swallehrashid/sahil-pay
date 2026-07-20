"""
routes/audit_routes.py — Landlord-Scoped Audit Trail
Blueprint: audit_bp  |  Prefix: /api/audit

Read-only view of the audit_logs table scoped to the current landlord.
Admin's cross-landlord view lives in admin_routes.py (/api/admin/audit).

AuditLog is append-only — no updates, no deletes via these endpoints.
The `before_data` / `after_data` JSON columns allow forensic diff inspection.
"""

from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import AuditLog, User, TeamMember, TeamMemberPermission, PermissionModule
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
from utils import get_jwt_user
from services.audit_service import record_audit

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")

# How long two identical view logs (same actor + entity + description) are
# collapsed into one. Stops React double-mounts / quick back-and-forth from
# flooding the landlord's trail while still capturing distinct visits.
_VIEW_DEDUPE_WINDOW = timedelta(seconds=30)


# ---------------------------------------------------------------------------
# GET /api/audit/
# ---------------------------------------------------------------------------
@audit_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def list_audit_logs():
    """
    Return paginated audit logs for the current landlord.

    Filters:
      ?start_date=    YYYY-MM-DD  inclusive
      ?end_date=      YYYY-MM-DD  inclusive
      ?actor_user_id= filter by who performed the action
      ?action=        partial match on action string (e.g. 'create', 'delete')
      ?entity_type=   e.g. 'tenant', 'invoice', 'payment'
      ?entity_id=     specific entity id
      ?page=
      ?per_page=

    Returns each log entry with actor name (denormalized snapshot preserved
    in audit_logs.actor_username / actor_full_name).
    ---
    tags: [Audit]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated audit log.}
    """
    landlord_id = get_current_landlord_id()
    page        = request.args.get("page", 1, type=int)
    per_page    = request.args.get("per_page", 20, type=int)

    query = AuditLog.query.filter_by(landlord_id=landlord_id)

    if v := request.args.get("start_date"):
        query = query.filter(AuditLog.created_at >= v)
    if v := request.args.get("end_date"):
        # Include the full end day
        query = query.filter(AuditLog.created_at < f"{v} 23:59:59")
    if v := request.args.get("actor_user_id", type=int):
        query = query.filter(AuditLog.actor_user_id == v)
    if v := request.args.get("action"):
        query = query.filter(AuditLog.action.ilike(f"%{v}%"))
    if v := request.args.get("entity_type"):
        query = query.filter(AuditLog.entity_type == v)
    if v := request.args.get("entity_id", type=int):
        query = query.filter(AuditLog.entity_id == v)

    paginated = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "logs":         [_enrich(log) for log in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/audit/<id>
# ---------------------------------------------------------------------------
@audit_bp.route("/<int:log_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("settings", "view")
def get_audit_log(log_id):
    """
    Return a single audit log entry with full before/after diff and
    affected_properties array.
    ---
    tags: [Audit]
    security:
      - Bearer: []
    responses:
      200: {description: Single audit log entry.}
      404: {description: Not found.}
    """
    landlord_id = get_current_landlord_id()
    log         = AuditLog.query.filter_by(id=log_id, landlord_id=landlord_id).first()
    if not log:
        abort(404, description="Audit log entry not found.")

    return jsonify(_enrich(log, include_diff=True)), 200


# ---------------------------------------------------------------------------
# POST /api/audit/view  — record a team member's "meaningful view"
# ---------------------------------------------------------------------------
@audit_bp.route("/view", methods=["POST"])
@jwt_required()
def log_view():
    """
    Record a *meaningful view* by a team member so it surfaces on the
    landlord's audit trail (§ team-member activity logging).

    Fires when a team member opens a module page or a specific record's
    detail view. Background polling / dropdown fetches are NOT reported —
    the client only calls this on real navigation.

    Body:
      { module: str,                 -- PermissionModule the page belongs to
        label:  str,                 -- human description, e.g. "Viewed Payments"
        entity_type: str  (optional),
        entity_id:   int  (optional) }

    Behaviour:
      - Only team members produce a log. Any other role is a silent no-op
        (returns 200 {logged: false}) so the client can call it uniformly.
      - The team member must actually hold view access on `module`; without
        it we refuse (they should never have loaded the page anyway).
      - Near-duplicate views (same actor/entity/label inside a 30s window)
        are collapsed so the trail stays readable.
    ---
    tags: [Audit]
    security:
      - Bearer: []
    responses:
      200: {description: View logged (or no-op for non-team-member).}
      403: {description: Team member lacks view access to that module.}
    """
    user = get_jwt_user()

    # Only team-member activity is logged — landlords/admins auditing
    # themselves would just flood their own trail.
    if user.role != "team_member":
        return jsonify({"logged": False, "reason": "not_a_team_member"}), 200

    tm: TeamMember | None = user.team_member_profile
    if tm is None:
        return jsonify({"logged": False, "reason": "no_team_profile"}), 200

    data        = request.get_json(silent=True) or {}
    module      = (data.get("module") or "").strip()
    label       = (data.get("label") or "").strip()
    entity_type = (data.get("entity_type") or "page").strip()
    entity_id   = data.get("entity_id")

    valid_modules = {m.value for m in PermissionModule}
    if module not in valid_modules:
        return jsonify({"error": f"Unknown module '{module}'."}), 400

    # Defence in depth: only log a view the member is actually allowed to make.
    perm = (
        db.session.query(TeamMemberPermission)
        .filter(
            TeamMemberPermission.team_member_id == tm.id,
            TeamMemberPermission.module == module,
        )
        .first()
    )
    if perm is None or not (perm.can_view or perm.can_edit):
        return jsonify({"error": "You do not have view access to that module."}), 403

    description = label or f"Viewed {module}"

    # Collapse near-duplicate views (React double-mount, quick revisits).
    cutoff = datetime.utcnow() - _VIEW_DEDUPE_WINDOW
    recent = (
        db.session.query(AuditLog.id)
        .filter(
            AuditLog.landlord_id   == tm.landlord_id,
            AuditLog.actor_user_id == user.id,
            AuditLog.action        == "view",
            AuditLog.entity_type   == entity_type,
            AuditLog.entity_id     == (int(entity_id) if entity_id is not None else None),
            AuditLog.description   == description,
            AuditLog.created_at    >= cutoff,
        )
        .first()
    )
    if recent is not None:
        return jsonify({"logged": False, "reason": "deduped"}), 200

    record_audit(
        actor_user_id=user.id,
        landlord_id=tm.landlord_id,
        action="view",
        entity_type=entity_type,
        entity_id=int(entity_id) if entity_id is not None else None,
        description=description,
    )
    db.session.commit()
    return jsonify({"logged": True}), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _enrich(log: AuditLog, include_diff: bool = False) -> dict:
    """Add human-readable actor name to a log dict."""
    d = log.to_dict()
    if not include_diff:
        # Omit heavy JSON columns on list view for performance
        d.pop("before_data", None)
        d.pop("after_data", None)
    return d