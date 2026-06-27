"""
routes/admin_routes.py — System Admin Core
Blueprint: admin_bp  |  Prefix: /api/admin

Platform health monitoring, landlord account control, manual data
corrections, dispute resolution, and the master cross-landlord audit log.

Security contract:
  - EVERY endpoint requires @require_admin (role = system_admin).
  - EVERY write action (suspend, reactivate, correct-data, revert) is
    recorded in audit_logs with the admin as actor and no exception.
  - "correct_data" is intentionally broad — the admin provides a
    structured payload describing what they changed and why.  The audit
    row captures before/after; no silent corrections are possible.
  - "revert" creates a new audit_logs row explaining the revert rather
    than modifying the original row.  audit_logs is append-only.
"""

from datetime import datetime

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    User, Landlord, TeamMember, Tenant, Unit, Property,
    AuditLog, Subscription, SubscriptionStatus, UserRole,
)
from services.audit_service import record_audit

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _require_admin():
    """Abort 403 if the caller is not a system_admin."""
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _admin_actor_id() -> int:
    return int(get_jwt_identity())


# ---------------------------------------------------------------------------
# GET /api/admin/dashboard
# ---------------------------------------------------------------------------
@admin_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def admin_dashboard():
    """
    Platform health dashboard — aggregated stats across ALL landlords.
    Returns one row per landlord with their unit count, active tenant
    count, team member count, subscription status, and trial info.
    Filterable by ?search= (company name / email).
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Platform-wide landlord summary table.}
      403: {description: Admin only.}
    """
    _require_admin()

    search   = request.args.get("search", "").strip()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    query = Landlord.query
    if search:
        query = query.join(User, User.id == Landlord.user_id).filter(
            db.or_(
                Landlord.company_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )

    paginated = query.order_by(Landlord.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    platform_totals = {
        "total_landlords":    Landlord.query.count(),
        "total_properties":   Property.query.filter_by(is_deleted=False).count(),
        "total_units":        Unit.query.filter_by(is_deleted=False).count(),
        "total_active_tenants": Tenant.query.filter_by(is_deleted=False).count(),
    }

    items = []
    for landlord in paginated.items:
        d = landlord.to_dict()
        d["email"]          = landlord.user.email       if landlord.user else None
        d["unit_count"]     = Unit.query.join(Property).filter(
                                  Property.landlord_id == landlord.id,
                                  Property.is_deleted.is_(False),
                                  Unit.is_deleted.is_(False),
                              ).count()
        d["active_tenants"] = Tenant.query.filter_by(
                                  landlord_id=landlord.id, is_deleted=False
                              ).count()
        d["team_members"]   = TeamMember.query.filter_by(
                                  landlord_id=landlord.id
                              ).count()
        d["subscription_status"] = (
            landlord.subscription.status if landlord.subscription else None
        )
        items.append(d)

    return jsonify({
        "platform_totals":  platform_totals,
        "landlords":        items,
        "total":            paginated.total,
        "pages":            paginated.pages,
        "current_page":     paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/landlords
# ---------------------------------------------------------------------------
@admin_bp.route("/landlords", methods=["GET"])
@jwt_required()
def list_landlords():
    """
    Paginated searchable list of all registered landlords/PMs.
    Filters: ?search=, ?status= (trial|active|past_due|suspended), ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Landlord list.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search   = request.args.get("search", "").strip()
    status   = request.args.get("status", "")

    query = Landlord.query.join(User, User.id == Landlord.user_id)
    if search:
        query = query.filter(
            db.or_(
                Landlord.company_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )
    if status:
        query = query.join(Subscription, Subscription.landlord_id == Landlord.id)\
                     .filter(Subscription.status == status)

    paginated = query.order_by(Landlord.company_name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for landlord in paginated.items:
        d = landlord.to_dict()
        d["email"]               = landlord.user.email if landlord.user else None
        d["is_active"]           = landlord.user.is_active if landlord.user else None
        d["subscription_status"] = landlord.subscription.status if landlord.subscription else None
        d["unit_count"]          = Unit.query.join(Property).filter(
                                       Property.landlord_id == landlord.id,
                                       Property.is_deleted.is_(False),
                                       Unit.is_deleted.is_(False),
                                   ).count()
        d["active_tenants"]      = Tenant.query.filter_by(
                                       landlord_id=landlord.id, is_deleted=False
                                   ).count()
        items.append(d)

    return jsonify({
        "landlords":    items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/landlords/<id>
# ---------------------------------------------------------------------------
@admin_bp.route("/landlords/<int:landlord_id>", methods=["GET"])
@jwt_required()
def get_landlord(landlord_id):
    """
    Drill into a single landlord account — full profile, subscription,
    unit count, tenant count, team members, recent audit activity.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Landlord full detail.}
      404: {description: Not found.}
    """
    _require_admin()
    landlord = _get_landlord_or_404(landlord_id)

    d = landlord.to_dict()
    d["email"]        = landlord.user.email     if landlord.user else None
    d["is_active"]    = landlord.user.is_active if landlord.user else None
    d["subscription"] = landlord.subscription.to_dict() if landlord.subscription else None
    d["unit_count"]   = Unit.query.join(Property).filter(
        Property.landlord_id == landlord.id,
        Property.is_deleted.is_(False),
        Unit.is_deleted.is_(False),
    ).count()
    d["active_tenants"] = Tenant.query.filter_by(
        landlord_id=landlord.id, is_deleted=False
    ).count()
    d["team_members"] = [tm.to_dict() for tm in landlord.team_members]

    # Last 10 audit entries for this landlord
    recent_audit = (
        AuditLog.query
        .filter_by(landlord_id=landlord.id)
        .order_by(AuditLog.created_at.desc())
        .limit(10)
        .all()
    )
    d["recent_audit"] = [a.to_dict() for a in recent_audit]

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# POST /api/admin/landlords/<id>/suspend
# ---------------------------------------------------------------------------
@admin_bp.route("/landlords/<int:landlord_id>/suspend", methods=["POST"])
@jwt_required()
def suspend_landlord(landlord_id):
    """
    Suspend a landlord account after investigation.
    Sets User.is_active=False and Subscription.status=suspended.
    Body: { reason: str }  — mandatory.  Recorded in audit trail.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Account suspended.}
      400: {description: Reason required.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = _get_landlord_or_404(landlord_id)
    data     = request.get_json(silent=True) or {}
    reason   = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "A reason for suspension is required."}), 400

    before = {"is_active": landlord.user.is_active if landlord.user else None,
              "subscription_status": landlord.subscription.status if landlord.subscription else None}

    if landlord.user:
        landlord.user.is_active = False
    if landlord.subscription:
        landlord.subscription.status = SubscriptionStatus.suspended.value

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=landlord.id,
        action="admin_suspend_landlord",
        entity_type="landlord",
        entity_id=landlord.id,
        description=f"ADMIN: Suspended landlord account {landlord.id} ({landlord.company_name}). Reason: {reason}",
        before_data=before,
        after_data={"is_active": False, "subscription_status": SubscriptionStatus.suspended.value},
    )
    db.session.commit()

    return jsonify({"message": f"Account for '{landlord.company_name}' suspended."}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/landlords/<id>/reactivate
# ---------------------------------------------------------------------------
@admin_bp.route("/landlords/<int:landlord_id>/reactivate", methods=["POST"])
@jwt_required()
def reactivate_landlord(landlord_id):
    """
    Reactivate a previously suspended landlord account.
    Restores User.is_active=True and Subscription.status=active.
    Body: { reason: str }  — mandatory.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Account reactivated.}
      400: {description: Reason required.}
    """
    _require_admin()
    landlord = _get_landlord_or_404(landlord_id)
    data     = request.get_json(silent=True) or {}
    reason   = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "A reason for reactivation is required."}), 400

    before = {"is_active": landlord.user.is_active if landlord.user else None,
              "subscription_status": landlord.subscription.status if landlord.subscription else None}

    if landlord.user:
        landlord.user.is_active = True
    if landlord.subscription:
        landlord.subscription.status = SubscriptionStatus.active.value

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=landlord.id,
        action="admin_reactivate_landlord",
        entity_type="landlord",
        entity_id=landlord.id,
        description=f"ADMIN: Reactivated landlord account {landlord.id} ({landlord.company_name}). Reason: {reason}",
        before_data=before,
        after_data={"is_active": True, "subscription_status": SubscriptionStatus.active.value},
    )
    db.session.commit()

    return jsonify({"message": f"Account for '{landlord.company_name}' reactivated."}), 200


# ---------------------------------------------------------------------------
# POST /api/admin/correct-data
# ---------------------------------------------------------------------------
@admin_bp.route("/correct-data", methods=["POST"])
@jwt_required()
def correct_data():
    """
    Admin manual data correction / dispute resolution.
    This endpoint is intentionally flexible — the admin describes what
    they are correcting, and the full before/after is audit-logged.

    Body:
      { landlord_id: int,
        entity_type: str,   -- e.g. 'payment', 'tenant', 'invoice'
        entity_id: int,
        correction: {       -- arbitrary JSON of fields being corrected
            field_name: new_value, ...
        },
        reason: str         -- mandatory human-readable justification
      }

    The route applies the correction to the named entity using SQLAlchemy
    and logs everything.  Only a limited safe set of scalar fields can be
    updated this way to prevent structural damage.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Correction applied and logged.}
      400: {description: Missing fields or unsafe correction.}
      404: {description: Entity not found.}
    """
    _require_admin()
    data        = request.get_json(silent=True) or {}
    landlord_id = data.get("landlord_id")
    entity_type = data.get("entity_type")
    entity_id   = data.get("entity_id")
    correction  = data.get("correction", {})
    reason      = (data.get("reason") or "").strip()

    if not all([landlord_id, entity_type, entity_id, correction, reason]):
        return jsonify({
            "error": "landlord_id, entity_type, entity_id, correction, and reason are all required."
        }), 400

    # Model registry for safe correction targets
    _ENTITY_MAP = {
        "tenant":  (Tenant,  ["first_name","last_name","phone","email","notes","balance"]),
        "payment": (__import__("models", fromlist=["Payment"]).Payment,
                    ["status","notes","amount","payment_date"]),
        "invoice": (__import__("models", fromlist=["Invoice"]).Invoice,
                    ["status","due_date","title","total_amount"]),
    }

    if entity_type not in _ENTITY_MAP:
        return jsonify({"error": f"Corrections on '{entity_type}' are not supported via this endpoint."}), 400

    Model, allowed_fields = _ENTITY_MAP[entity_type]
    entity = db.session.get(Model, entity_id)
    if not entity:
        return jsonify({"error": f"{entity_type.title()} with id {entity_id} not found."}), 404

    before = entity.to_dict()

    applied = {}
    refused = {}
    for field, value in correction.items():
        if field in allowed_fields:
            setattr(entity, field, value)
            applied[field] = value
        else:
            refused[field] = "field not allowed for admin correction"

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=landlord_id,
        action="admin_correct_data",
        entity_type=entity_type,
        entity_id=entity_id,
        description=(
            f"ADMIN DATA CORRECTION on {entity_type} #{entity_id} "
            f"for landlord {landlord_id}. Reason: {reason}"
        ),
        before_data=before,
        after_data=entity.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":  "Correction applied.",
        "applied":  applied,
        "refused":  refused,
        "entity":   entity.to_dict(),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/audit
# ---------------------------------------------------------------------------
@admin_bp.route("/audit", methods=["GET"])
@jwt_required()
def master_audit_log():
    """
    Cross-landlord master audit log — every write action on the platform.
    Filters: ?landlord_id=, ?actor_user_id=, ?entity_type=, ?action=,
             ?start_date=, ?end_date=, ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Paginated master audit log.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)

    query = AuditLog.query

    if v := request.args.get("landlord_id", type=int):
        query = query.filter(AuditLog.landlord_id == v)
    if v := request.args.get("actor_user_id", type=int):
        query = query.filter(AuditLog.actor_user_id == v)
    if v := request.args.get("entity_type"):
        query = query.filter(AuditLog.entity_type == v)
    if v := request.args.get("action"):
        query = query.filter(AuditLog.action.ilike(f"%{v}%"))
    if v := request.args.get("start_date"):
        query = query.filter(AuditLog.created_at >= v)
    if v := request.args.get("end_date"):
        query = query.filter(AuditLog.created_at <= f"{v} 23:59:59")

    paginated = query.order_by(AuditLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "logs":         [log.to_dict() for log in paginated.items],
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/revert/<audit_id>
# ---------------------------------------------------------------------------
@admin_bp.route("/revert/<int:audit_log_id>", methods=["POST"])
@jwt_required()
def revert_action(audit_log_id):
    """
    Revert an inappropriate action by restoring the entity to its
    before_data state recorded in the audit log.

    Body: { reason: str }  — mandatory.

    Behaviour:
      - Loads the target AuditLog entry.
      - Applies before_data back onto the entity (if revertable).
      - Creates a NEW audit_logs row recording this revert action.
        The original audit row is NEVER modified — audit_logs is append-only.
      - Returns the reverted entity state.

    Not all entity types support automatic revert (e.g. invoice generation
    creates many rows and can't be safely auto-reverted).  In those cases
    the admin is instructed to use correct-data instead.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Action reverted and re-logged.}
      400: {description: Revert not possible or reason missing.}
      404: {description: Audit log entry not found.}
    """
    _require_admin()
    data   = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "A reason for the revert is required."}), 400

    original_log = db.session.get(AuditLog, audit_log_id)
    if not original_log:
        return jsonify({"error": "Audit log entry not found."}), 404

    if not original_log.before_data:
        return jsonify({
            "error": "This audit entry has no before_data snapshot. Manual correction required via /correct-data."
        }), 400

    # Supported revert targets
    from models import Payment, Invoice, Tenant, Expense

    _REVERT_MAP = {
        "payment":  Payment,
        "invoice":  Invoice,
        "tenant":   Tenant,
        "expense":  Expense,
    }

    entity_type = original_log.entity_type
    entity_id   = original_log.entity_id
    Model       = _REVERT_MAP.get(entity_type)

    if not Model:
        return jsonify({
            "error": (
                f"Automatic revert is not supported for entity_type '{entity_type}'. "
                f"Use /correct-data for manual correction."
            )
        }), 400

    entity = db.session.get(Model, entity_id)
    if not entity:
        return jsonify({"error": f"{entity_type.title()} #{entity_id} no longer exists."}), 404

    current_state = entity.to_dict()

    # Restore before_data fields that exist on the model
    before_data = original_log.before_data or {}
    for field, value in before_data.items():
        if hasattr(entity, field) and field not in ("id", "created_at", "updated_at"):
            try:
                setattr(entity, field, value)
            except Exception:
                pass

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=original_log.landlord_id,
        action="admin_revert_action",
        entity_type=entity_type,
        entity_id=entity_id,
        description=(
            f"ADMIN REVERT of audit_log #{audit_log_id} "
            f"(original action: '{original_log.action}'). Reason: {reason}"
        ),
        before_data=current_state,
        after_data=entity.to_dict(),
    )
    db.session.commit()

    return jsonify({
        "message":         "Action reverted successfully.",
        "reverted_entity": entity.to_dict(),
        "original_log_id": audit_log_id,
    }), 200


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_landlord_or_404(landlord_id: int) -> Landlord:
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        abort(404, description="Landlord not found.")
    return landlord