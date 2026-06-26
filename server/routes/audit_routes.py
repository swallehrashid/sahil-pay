"""
routes/audit_routes.py — Landlord-Scoped Audit Trail
Blueprint: audit_bp  |  Prefix: /api/audit

Read-only view of the audit_logs table scoped to the current landlord.
Admin's cross-landlord view lives in admin_routes.py (/api/admin/audit).

AuditLog is append-only — no updates, no deletes via these endpoints.
The `before_data` / `after_data` JSON columns allow forensic diff inspection.
"""

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required

from extensions import db
from models import AuditLog, User
from decorators import require_landlord_or_team, require_permission, get_current_landlord_id

audit_bp = Blueprint("audit", __name__, url_prefix="/api/audit")


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