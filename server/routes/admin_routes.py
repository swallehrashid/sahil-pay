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
from decimal import Decimal

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import (
    User, Landlord, TeamMember, Tenant, Unit, Property,
    AuditLog, Subscription, SubscriptionStatus, UserRole,
    Package, TeamMemberPermission, TeamMemberPropertyAccess,
    Payment, Invoice,
)
from services.audit_service import record_audit

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _require_admin():
    """Admin gate — delegates to the ONE shared implementation, which also
    enforces two-factor authentication (decorators.require_system_admin)."""
    from decorators import require_system_admin

    require_system_admin()

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

    # Demo shadow landlords (DEMO_MODE_SPEC.md §3.4) are internal scaffolding
    # for the landlord "try demo mode" feature — never surfaced in admin
    # platform views/counts.
    query = Landlord.query.filter(Landlord.is_demo.is_(False))
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

    _real_landlord_ids = db.session.query(Landlord.id).filter(Landlord.is_demo.is_(False))
    platform_totals = {
        "total_landlords":      Landlord.query.filter(Landlord.is_demo.is_(False)).count(),
        "total_properties":     Property.query.filter(
                                     Property.is_deleted.is_(False),
                                     Property.landlord_id.in_(_real_landlord_ids),
                                 ).count(),
        "total_units":          Unit.query.join(Property).filter(
                                     Unit.is_deleted.is_(False),
                                     Property.is_deleted.is_(False),
                                     Property.landlord_id.in_(_real_landlord_ids),
                                 ).count(),
        "total_active_tenants": Tenant.query.filter(
                                     Tenant.is_deleted.is_(False),
                                     Tenant.landlord_id.in_(_real_landlord_ids),
                                 ).count(),
        "total_team_members":   TeamMember.query.filter(
                                     TeamMember.landlord_id.in_(_real_landlord_ids),
                                 ).count(),
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

    query = Landlord.query.join(User, User.id == Landlord.user_id).filter(Landlord.is_demo.is_(False))
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
# PATCH /api/admin/landlords/<id>/subscription  — override billing figures
# ---------------------------------------------------------------------------
@admin_bp.route("/landlords/<int:landlord_id>/subscription", methods=["PATCH"])
@jwt_required()
def override_subscription(landlord_id):
    """
    Admin override of a landlord's billing. The figures are auto-calculated
    (unit count → package tier → per-unit cost; next billing date from the
    registration date), but the admin can override the next billing date, the
    amount due, and the unit count here.
    Body (any subset): { next_billing_date: 'YYYY-MM-DD', amount_due: number,
                         unit_count: int, status: str }
    ---
    tags: [Admin]
    """
    _require_admin()
    landlord = _get_landlord_or_404(landlord_id)
    data     = request.get_json(silent=True) or {}

    from services.billing_service import recompute_subscription
    from utils import parse_date

    # Start from the auto-calculated baseline, then apply the admin's overrides.
    sub = recompute_subscription(landlord)
    before = sub.to_dict()

    if "next_billing_date" in data and data["next_billing_date"]:
        d = parse_date(data["next_billing_date"])
        if not d:
            return jsonify({"error": "next_billing_date must be YYYY-MM-DD."}), 400
        sub.next_billing_date = d
    if "amount_due" in data and data["amount_due"] is not None:
        sub.amount_due = Decimal(str(data["amount_due"]))
    if "unit_count" in data and data["unit_count"] is not None:
        sub.unit_count = int(data["unit_count"])
    if "status" in data and data["status"]:
        sub.status = data["status"]

    db.session.commit()

    record_audit(
        actor_user_id=_admin_actor_id(),
        landlord_id=landlord.id,
        action="admin_override_subscription",
        entity_type="subscription",
        entity_id=sub.id,
        description=f"ADMIN: Overrode billing for landlord {landlord.id} ({landlord.company_name}).",
        before_data=before,
        after_data=sub.to_dict(),
    )
    db.session.commit()

    return jsonify({"message": "Subscription updated.", "subscription": sub.to_dict()}), 200


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

    # Demo-mode rows are NOT platform activity. Demo data lives in the real
    # database under a hidden shadow landlord (DEMO_MODE_SPEC.md §2), so every
    # click a landlord makes while practising writes a real audit row — with
    # "platform" as the performer for the engine-driven billing the demo seed
    # runs. Left unfiltered, opening the master log after any demo session shows
    # invoices nobody issued, which reads exactly like a breach. The rows stay
    # written (they are useful for debugging) but never surface here.
    #
    # ?include_demo=true is the deliberate escape hatch for support.
    if (request.args.get("include_demo") or "").lower() not in ("1", "true", "yes"):
        demo_landlord_ids = db.session.query(Landlord.id).filter(Landlord.is_demo.is_(True))
        query = query.filter(
            db.or_(
                AuditLog.landlord_id.is_(None),
                AuditLog.landlord_id.notin_(demo_landlord_ids),
            )
        )

    if v := request.args.get("landlord_id", type=int):
        query = query.filter(AuditLog.landlord_id == v)
    if v := request.args.get("actor_user_id", type=int):
        query = query.filter(AuditLog.actor_user_id == v)
    # Filter by the actor's role (landlord / property_manager / team_member /
    # tenant / system_admin) — lets the admin scope the trail to "what tenants
    # did" or "what team members did", not just a single named user.
    if v := request.args.get("actor_role"):
        query = query.join(User, User.id == AuditLog.actor_user_id)\
                     .filter(User.role == v)
    if v := request.args.get("entity_type"):
        query = query.filter(AuditLog.entity_type == v)
    if v := request.args.get("action"):
        query = query.filter(AuditLog.action.ilike(f"%{v}%"))
    # Client-support-only view: utils.audit() prefixes every support-session action's
    # description with "[Client support session — landlord #<id>]" (older rows use the
    # legacy "[Impersonating landlord #<id>]" prefix — match both).
    if request.args.get("impersonated") == "true":
        query = query.filter(
            db.or_(
                AuditLog.description.ilike("%[Client support session%"),
                AuditLog.description.ilike("%[Impersonating%"),
            )
        )
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


# ===========================================================================
# DRILL-DOWNS — clickable dashboard entities
#
# Every admin dashboard stat card and entity is clickable and resolves to
# one of these read-only directory endpoints.  They join across landlord
# boundaries (admin sees the whole platform) and denormalise the context a
# human needs to understand a row without a second click: who owns it, which
# property/unit it belongs to, who occupies it, what plan funds it.
# ===========================================================================

def _current_occupant(unit_id: int):
    """The active (non-deleted, not moved-out) tenant on a unit, or None."""
    return (
        Tenant.query
        .filter_by(unit_id=unit_id, is_deleted=False)
        .filter(Tenant.move_out_date.is_(None))
        .order_by(Tenant.created_at.desc())
        .first()
    )


def _landlord_label(landlord: Landlord) -> dict:
    """Compact landlord identity block reused across every drill-down."""
    return {
        "landlord_id":   landlord.id if landlord else None,
        "company_name":  landlord.company_name if landlord else None,
        "landlord_email": (landlord.user.email if landlord and landlord.user else None),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/units      — every unit on the platform, with occupant
# ---------------------------------------------------------------------------
@admin_bp.route("/units", methods=["GET"])
@jwt_required()
def list_units():
    """
    Platform-wide unit directory.  One row per unit with its property,
    owning landlord, occupancy state and current occupant.
    Filters: ?search= (unit/property name), ?occupied= (true|false),
             ?landlord_id=, ?property_id=, ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Unit directory.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search   = request.args.get("search", "").strip()

    query = (
        Unit.query
        .join(Property, Property.id == Unit.property_id)
        .join(Landlord, Landlord.id == Property.landlord_id)
        .filter(Unit.is_deleted.is_(False), Property.is_deleted.is_(False))
    )

    if search:
        query = query.filter(
            db.or_(
                Unit.name.ilike(f"%{search}%"),
                Property.name.ilike(f"%{search}%"),
            )
        )
    if (occ := request.args.get("occupied")) in ("true", "false"):
        query = query.filter(Unit.is_occupied.is_(occ == "true"))
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(Property.landlord_id == v)
    if v := request.args.get("property_id", type=int):
        query = query.filter(Unit.property_id == v)

    paginated = query.order_by(Property.name, Unit.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for unit in paginated.items:
        d = unit.to_dict()
        d["property_name"] = unit.property.name if unit.property else None
        d["city"]          = unit.property.city if unit.property else None
        d.update(_landlord_label(unit.property.landlord if unit.property else None))
        occupant = _current_occupant(unit.id) if unit.is_occupied else None
        d["occupant"] = (
            {
                "id":      occupant.id,
                "name":    f"{occupant.first_name} {occupant.last_name}".strip(),
                "phone":   occupant.phone,
                "balance": _serialise_num(occupant.balance),
            }
            if occupant else None
        )
        items.append(d)

    return jsonify({
        "units":        items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/units/<id> — full unit detail
# ---------------------------------------------------------------------------
@admin_bp.route("/units/<int:unit_id>", methods=["GET"])
@jwt_required()
def get_unit(unit_id):
    """
    Full detail on a single unit: unit fields, its property, owning
    landlord, the current occupant and their balance, and recent activity.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Unit detail.}
      404: {description: Not found.}
    """
    _require_admin()
    unit = db.session.get(Unit, unit_id)
    if not unit or unit.is_deleted:
        abort(404, description="Unit not found.")

    d = unit.to_dict()
    d["property"] = unit.property.to_dict() if unit.property else None
    landlord = unit.property.landlord if unit.property else None
    d.update(_landlord_label(landlord))

    occupant = _current_occupant(unit.id)
    d["occupant"] = occupant.to_dict() if occupant else None

    # Everyone who has ever occupied this unit (history + current)
    past = (
        Tenant.query.filter_by(unit_id=unit.id)
        .order_by(Tenant.created_at.desc()).all()
    )
    d["tenants_all"] = [
        {
            "id":            t.id,
            "name":          f"{t.first_name} {t.last_name}".strip(),
            "phone":         t.phone,
            "is_deleted":    t.is_deleted,
            "move_in_date":  _serialise_date(t.move_in_date),
            "move_out_date": _serialise_date(t.move_out_date),
        }
        for t in past
    ]

    # Recent payments on this unit
    recent_payments = (
        Payment.query.filter_by(unit_id=unit.id, is_deleted=False)
        .order_by(Payment.created_at.desc()).limit(10).all()
    )
    d["recent_payments"] = [p.to_dict() for p in recent_payments]

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# GET /api/admin/tenants    — every active tenant on the platform
# ---------------------------------------------------------------------------
@admin_bp.route("/tenants", methods=["GET"])
@jwt_required()
def list_tenants():
    """
    Platform-wide tenant directory.  One row per tenant with unit,
    property, owning landlord and outstanding balance.
    Filters: ?search= (name/phone/email), ?landlord_id=,
             ?include_deleted= (true), ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant directory.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search   = request.args.get("search", "").strip()

    query = (
        Tenant.query
        .join(Landlord, Landlord.id == Tenant.landlord_id)
    )
    if request.args.get("include_deleted") != "true":
        query = query.filter(Tenant.is_deleted.is_(False))
    if search:
        query = query.filter(
            db.or_(
                Tenant.first_name.ilike(f"%{search}%"),
                Tenant.last_name.ilike(f"%{search}%"),
                Tenant.phone.ilike(f"%{search}%"),
                Tenant.email.ilike(f"%{search}%"),
            )
        )
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(Tenant.landlord_id == v)

    paginated = query.order_by(Tenant.first_name, Tenant.last_name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for t in paginated.items:
        d = t.to_dict()
        d["name"]          = f"{t.first_name} {t.last_name}".strip()
        d["unit_name"]     = t.unit.name if t.unit else None
        d["property_name"] = t.unit.property.name if t.unit and t.unit.property else None
        d.update(_landlord_label(t.landlord))
        items.append(d)

    return jsonify({
        "tenants":      items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/tenants/<id> — full tenant detail
# ---------------------------------------------------------------------------
@admin_bp.route("/tenants/<int:tenant_id>", methods=["GET"])
@jwt_required()
def get_tenant(tenant_id):
    """
    Full tenant profile: personal + lease + deposit fields, unit,
    property, owning landlord, recent payments and open invoices.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Tenant detail.}
      404: {description: Not found.}
    """
    _require_admin()
    t = db.session.get(Tenant, tenant_id)
    if not t:
        abort(404, description="Tenant not found.")

    d = t.to_dict()
    d["name"]     = f"{t.first_name} {t.last_name}".strip()
    d["unit"]     = t.unit.to_dict() if t.unit else None
    d["property"] = t.unit.property.to_dict() if t.unit and t.unit.property else None
    d.update(_landlord_label(t.landlord))

    recent_payments = (
        Payment.query.filter_by(tenant_id=t.id, is_deleted=False)
        .order_by(Payment.created_at.desc()).limit(10).all()
    )
    d["recent_payments"] = [p.to_dict() for p in recent_payments]

    open_invoices = (
        Invoice.query.filter_by(tenant_id=t.id, is_deleted=False)
        .order_by(Invoice.created_at.desc()).limit(10).all()
    )
    d["recent_invoices"] = [i.to_dict() for i in open_invoices]

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# GET /api/admin/team-members — every sub-account on the platform
# ---------------------------------------------------------------------------
@admin_bp.route("/team-members", methods=["GET"])
@jwt_required()
def list_team_members():
    """
    Platform-wide team-member directory.  One row per sub-account with the
    landlord they belong to, their role, active state and a permission count.
    Filters: ?search= (name/email), ?landlord_id=, ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Team-member directory.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search   = request.args.get("search", "").strip()

    query = (
        TeamMember.query
        .join(User, User.id == TeamMember.user_id)
        .join(Landlord, Landlord.id == TeamMember.landlord_id)
    )
    if search:
        query = query.filter(
            db.or_(
                TeamMember.username.ilike(f"%{search}%"),
                TeamMember.first_name.ilike(f"%{search}%"),
                TeamMember.last_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
            )
        )
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(TeamMember.landlord_id == v)

    paginated = query.order_by(TeamMember.username).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for tm in paginated.items:
        d = tm.to_dict()
        d["email"] = tm.user.email if tm.user else None
        d.update(_landlord_label(tm.landlord))
        granted = [p for p in tm.permissions if p.can_view or p.can_edit]
        d["permission_count"] = len(granted)
        d["modules"] = sorted({p.module for p in granted})
        items.append(d)

    return jsonify({
        "team_members": items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/team-members/<id> — full detail incl. permissions & activity
# ---------------------------------------------------------------------------
@admin_bp.route("/team-members/<int:team_member_id>", methods=["GET"])
@jwt_required()
def get_team_member(team_member_id):
    """
    Full team-member detail: profile, the landlord they belong to, every
    per-module permission (view/edit — what they can do), the properties
    they are scoped to, and their recent activity from the audit trail
    (what they have been doing).
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Team-member detail.}
      404: {description: Not found.}
    """
    _require_admin()
    tm = db.session.get(TeamMember, team_member_id)
    if not tm:
        abort(404, description="Team member not found.")

    d = tm.to_dict()
    d["email"] = tm.user.email if tm.user else None
    d["landlord"] = _landlord_label(tm.landlord)

    # What they can do — every module permission
    d["permissions"] = [
        {"module": p.module, "can_view": p.can_view, "can_edit": p.can_edit}
        for p in sorted(tm.permissions, key=lambda p: p.module)
    ]

    # Which properties they are scoped to (unless property_access_all)
    if tm.property_access_all:
        d["property_access"] = "all"
    else:
        access = (
            db.session.query(Property)
            .join(TeamMemberPropertyAccess,
                  TeamMemberPropertyAccess.property_id == Property.id)
            .filter(TeamMemberPropertyAccess.team_member_id == tm.id)
            .all()
        )
        d["property_access"] = [
            {"id": p.id, "name": p.name, "city": p.city} for p in access
        ]

    # What they have been doing — recent audit activity as the actor
    recent = (
        AuditLog.query
        .filter_by(actor_user_id=tm.user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(25)
        .all()
    )
    d["recent_activity"] = [a.to_dict() for a in recent]

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# GET /api/admin/properties — every property/company on the platform
# ---------------------------------------------------------------------------
@admin_bp.route("/properties", methods=["GET"])
@jwt_required()
def list_properties():
    """
    Platform-wide property directory.  One row per property with owning
    landlord, unit/occupancy counts, the landlord's package and
    subscription amount, and trial state.
    Filters: ?search= (property/company name), ?landlord_id=,
             ?page=, ?per_page=
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Property directory.}
    """
    _require_admin()

    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search   = request.args.get("search", "").strip()

    query = (
        Property.query
        .join(Landlord, Landlord.id == Property.landlord_id)
        .filter(Property.is_deleted.is_(False))
    )
    if search:
        query = query.filter(
            db.or_(
                Property.name.ilike(f"%{search}%"),
                Landlord.company_name.ilike(f"%{search}%"),
            )
        )
    if v := request.args.get("landlord_id", type=int):
        query = query.filter(Property.landlord_id == v)

    paginated = query.order_by(Property.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for prop in paginated.items:
        d = prop.to_dict()
        landlord = prop.landlord
        d.update(_landlord_label(landlord))
        total = Unit.query.filter_by(property_id=prop.id, is_deleted=False).count()
        occupied = Unit.query.filter_by(
            property_id=prop.id, is_deleted=False, is_occupied=True
        ).count()
        d["unit_count"]     = total
        d["occupied_units"] = occupied
        d["vacant_units"]   = total - occupied
        d.update(_landlord_plan_block(landlord))
        items.append(d)

    return jsonify({
        "properties":   items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/properties/<id> — full property detail with units
# ---------------------------------------------------------------------------
@admin_bp.route("/properties/<int:property_id>", methods=["GET"])
@jwt_required()
def get_property(property_id):
    """
    Full property detail: all property fields, owning landlord, the plan/
    trial funding it, occupancy summary, and every unit with its occupant.
    ---
    tags: [Admin]
    security:
      - Bearer: []
    responses:
      200: {description: Property detail.}
      404: {description: Not found.}
    """
    _require_admin()
    prop = db.session.get(Property, property_id)
    if not prop or prop.is_deleted:
        abort(404, description="Property not found.")

    d = prop.to_dict()
    landlord = prop.landlord
    d["landlord"] = _landlord_label(landlord)
    d.update(_landlord_plan_block(landlord))

    units = (
        Unit.query.filter_by(property_id=prop.id, is_deleted=False)
        .order_by(Unit.name).all()
    )
    unit_rows = []
    for u in units:
        occupant = _current_occupant(u.id) if u.is_occupied else None
        unit_rows.append({
            "id":          u.id,
            "name":        u.name,
            "rent_amount": _serialise_num(u.rent_amount),
            "is_occupied": u.is_occupied,
            "occupant":    (
                {
                    "id":      occupant.id,
                    "name":    f"{occupant.first_name} {occupant.last_name}".strip(),
                    "phone":   occupant.phone,
                    "balance": _serialise_num(occupant.balance),
                } if occupant else None
            ),
        })
    d["units"]          = unit_rows
    d["unit_count"]     = len(unit_rows)
    d["occupied_units"] = sum(1 for u in unit_rows if u["is_occupied"])
    d["vacant_units"]   = d["unit_count"] - d["occupied_units"]

    return jsonify(d), 200


# ---------------------------------------------------------------------------
# Drill-down helpers
# ---------------------------------------------------------------------------
def _landlord_plan_block(landlord: Landlord) -> dict:
    """Package / subscription-cost / trial funding block for a landlord."""
    if not landlord:
        return {"package": None, "subscription_cost": None,
                "is_on_trial": None, "trial_ends_at": None}
    package = landlord.package
    sub = landlord.subscription
    return {
        "package": (
            {"id": package.id, "name": package.name,
             "price_per_unit": _serialise_num(package.price_per_unit),
             "flat_price": _serialise_num(package.flat_price)}
            if package else None
        ),
        "subscription_cost": _serialise_num(sub.subscription_cost) if sub else None,
        "subscription_status": sub.status if sub else None,
        "is_on_trial":         landlord.is_on_trial,
        "trial_ends_at":       _serialise_dt(landlord.trial_ends_at),
    }


def _serialise_num(v):
    return float(v) if v is not None else None


def _serialise_date(v):
    return v.isoformat() if v is not None else None


def _serialise_dt(v):
    return v.isoformat() if v is not None else None