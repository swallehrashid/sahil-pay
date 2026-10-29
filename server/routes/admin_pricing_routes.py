"""
routes/admin_pricing_routes.py — Platform Pricing & Package Management
Blueprint: admin_pricing_bp  |  Prefix: /api/admin/pricing

Admin creates and manages tiered pricing packages (unit bands).
Landlords subscribe into a package; the admin can also set a per-unit
price override directly on a landlord record, bypassing the package tier.

Package model:
  name          — human label, e.g. "Starter", "Growth", "Enterprise"
  min_units     — lower bound of the unit band (inclusive)
  max_units     — upper bound (null = no cap)
  price_per_unit — nullable Numeric; used if flat_price is null
  flat_price    — nullable Numeric; flat monthly rate regardless of unit count
  is_active     — soft-deactivate rather than hard-delete

Business rule: at least one of price_per_unit / flat_price must be set
(enforced by DB CheckConstraint; also validated here).

Per-unit price override:
  landlord.per_unit_price — when set, supersedes any package calculation.
  landlord.package_id     — can be set alongside the override for reference.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import Package, Landlord, UserRole
from services.audit_service import record_audit

admin_pricing_bp = Blueprint("admin_pricing", __name__, url_prefix="/api/admin/pricing")


def _require_admin():
    """Admin gate — delegates to the ONE shared implementation, which also
    enforces two-factor authentication (decorators.require_system_admin)."""
    from decorators import require_system_admin

    require_system_admin()

def _admin_id() -> int:
    return int(get_jwt_identity())


def _apply_storefront_fields(package, data):
    """Copy the public-storefront fields (featured/badges/copy/order) from the
    request body onto a Package, when present. Shared by create + update."""
    # #17 — a custom package can never be featured/recommended/popular on the
    # public storefront, regardless of what the request tries to set.
    if package.is_custom:
        package.is_featured = False
        package.is_recommended = False
        package.is_popular = False
        return
    if "is_featured" in data:
        package.is_featured = bool(data["is_featured"])
    if "is_recommended" in data:
        package.is_recommended = bool(data["is_recommended"])
    if "is_popular" in data:
        package.is_popular = bool(data["is_popular"])
    if "public_description" in data:
        package.public_description = (data["public_description"] or "").strip() or None
    if "feature_list" in data:
        fl = data["feature_list"]
        if isinstance(fl, str):
            fl = [s.strip() for s in fl.splitlines() if s.strip()]
        package.feature_list = [str(s).strip() for s in (fl or []) if str(s).strip()]
    if "display_order" in data:
        try:
            package.display_order = int(data["display_order"])
        except (TypeError, ValueError):
            package.display_order = 0


# ---------------------------------------------------------------------------
# GET /api/admin/pricing/packages
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages", methods=["GET"])
@jwt_required()
def list_packages():
    """
    List all pricing packages (active and inactive).
    ?active_only=true to filter to is_active=True packages only.
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Package list.}
    """
    _require_admin()

    active_only = request.args.get("active_only", "false").lower() == "true"
    query       = Package.query
    if active_only:
        query = query.filter_by(is_active=True)

    packages = query.order_by(Package.min_units).all()

    return jsonify({
        "packages": [p.to_dict() for p in packages],
        "total":    len(packages),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/pricing/packages
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages", methods=["POST"])
@jwt_required()
def create_package():
    """
    Create a new pricing package (unit band).
    Required: name, min_units, and at least one of price_per_unit / flat_price.
    Optional: max_units (null = no upper cap).

    Business rule: max_units >= min_units (when set).
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      201: {description: Package created.}
      400: {description: Validation error.}
    """
    _require_admin()
    data = request.get_json(silent=True) or {}

    name           = (data.get("name") or "").strip()
    min_units      = data.get("min_units")
    max_units      = data.get("max_units")
    price_per_unit = data.get("price_per_unit")
    flat_price     = data.get("flat_price")

    if not name or min_units is None:
        return jsonify({"error": "name and min_units are required."}), 400
    if price_per_unit is None and flat_price is None:
        return jsonify({"error": "At least one of price_per_unit or flat_price is required."}), 400
    if max_units is not None and int(max_units) < int(min_units):
        return jsonify({"error": "max_units must be >= min_units."}), 400

    package = Package(
        name           = name,
        min_units      = int(min_units),
        max_units      = int(max_units) if max_units is not None else None,
        price_per_unit = Decimal(str(price_per_unit)) if price_per_unit is not None else None,
        flat_price     = Decimal(str(flat_price))     if flat_price     is not None else None,
        is_active      = True,
    )
    _apply_storefront_fields(package, data)
    db.session.add(package)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=None,
        action="admin_create_package",
        entity_type="package",
        entity_id=package.id,
        description=f"ADMIN: Pricing package '{name}' created (units {min_units}–{max_units or '∞'}).",
        after_data=package.to_dict(),
    )
    db.session.commit()

    return jsonify(package.to_dict()), 201


# ---------------------------------------------------------------------------
# PUT /api/admin/pricing/packages/<id>
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages/<int:package_id>", methods=["PUT"])
@jwt_required()
def update_package(package_id):
    """
    Edit a package's band or price.
    Existing landlords on this package are NOT automatically re-priced —
    their Subscription.subscription_cost is recalculated only on next
    billing cycle or when they explicitly pay/switch.
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Package updated.}
      404: {description: Package not found.}
    """
    _require_admin()
    package = _get_pkg_or_404(package_id)
    data    = request.get_json(silent=True) or {}
    before  = package.to_dict()

    if "name" in data:
        package.name = data["name"]
    if "min_units" in data:
        package.min_units = int(data["min_units"])
    if "max_units" in data:
        package.max_units = int(data["max_units"]) if data["max_units"] is not None else None
    if "price_per_unit" in data:
        package.price_per_unit = (
            Decimal(str(data["price_per_unit"])) if data["price_per_unit"] is not None else None
        )
    if "flat_price" in data:
        package.flat_price = (
            Decimal(str(data["flat_price"])) if data["flat_price"] is not None else None
        )

    _apply_storefront_fields(package, data)

    # Enforce: at least one price field must remain set
    if package.price_per_unit is None and package.flat_price is None:
        return jsonify({"error": "At least one of price_per_unit or flat_price must be set."}), 400
    if package.max_units is not None and package.max_units < package.min_units:
        return jsonify({"error": "max_units must be >= min_units."}), 400

    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=None,
        action="admin_update_package",
        entity_type="package",
        entity_id=package.id,
        description=f"ADMIN: Pricing package '{package.name}' updated.",
        before_data=before,
        after_data=package.to_dict(),
    )
    db.session.commit()

    return jsonify(package.to_dict()), 200


# ---------------------------------------------------------------------------
# DELETE /api/admin/pricing/packages/<id>  (soft-deactivate)
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages/<int:package_id>", methods=["DELETE"])
@jwt_required()
def deactivate_package(package_id):
    """
    Deactivate a package (is_active=False).
    Landlords already on this package keep it; new landlords cannot choose it.
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Package deactivated.}
      404: {description: Package not found.}
    """
    _require_admin()
    package = _get_pkg_or_404(package_id)

    package.is_active = False
    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=None,
        action="admin_deactivate_package",
        entity_type="package",
        entity_id=package.id,
        description=f"ADMIN: Pricing package '{package.name}' deactivated.",
        before_data={"is_active": True},
        after_data={"is_active": False},
    )
    db.session.commit()

    return jsonify({"message": f"Package '{package.name}' deactivated."}), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/pricing/landlords/<id>/fixed-price
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/landlords/<int:landlord_id>/fixed-price", methods=["PUT"])
@jwt_required()
def set_fixed_monthly_price(landlord_id):
    """
    Set a negotiated FLAT monthly fee for one landlord.

    Body:
      { fixed_monthly_price: number | null,   -- null clears it
        reason: str }                         -- mandatory

    This overrides per-unit pricing entirely: the landlord pays this amount
    every month regardless of how many units they add or remove. Because the
    figure is agreed verbally and is already a discount, billing-cycle
    discounts (quarterly 10%, annual 15%) do NOT stack on top of it.

    Setting it moves the landlord into the Custom package. It takes effect on
    the NEXT billing cycle — an already-issued amount_due is left alone.
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Fixed price updated.}
      400: {description: Validation error.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    data   = request.get_json(silent=True) or {}
    raw    = data.get("fixed_monthly_price")
    reason = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "A reason is required for a fixed-price override."}), 400

    if raw is not None:
        try:
            value = Decimal(str(raw))
        except (TypeError, ValueError, ArithmeticError):
            return jsonify({"error": "fixed_monthly_price must be a number."}), 400
        if value < 0:
            return jsonify({"error": "fixed_monthly_price cannot be negative."}), 400
    else:
        value = None

    before = {
        "fixed_monthly_price": str(landlord.fixed_monthly_price) if landlord.fixed_monthly_price else None,
        "package_id": landlord.package_id,
    }

    landlord.fixed_monthly_price = value
    db.session.flush()

    # Refresh the derived figures. next_billing_date and any in-flight
    # amount_due are deliberately left untouched, so the change lands on the
    # next cycle rather than re-pricing a period the landlord already paid for.
    from services.billing_service import recompute_subscription
    subscription = recompute_subscription(landlord)
    db.session.commit()

    after = {
        "fixed_monthly_price": str(landlord.fixed_monthly_price) if landlord.fixed_monthly_price else None,
        "package_id": landlord.package_id,
    }

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord.id,
        action="admin_set_fixed_monthly_price",
        entity_type="landlord",
        entity_id=landlord.id,
        description=(
            f"ADMIN: Fixed monthly price for '{landlord.company_name}' set to "
            f"{value if value is not None else 'None (cleared)'}. "
            f"Effective next billing cycle. Reason: {reason}"
        ),
        before_data=before,
        after_data=after,
    )
    db.session.commit()

    return jsonify({
        "message": "Fixed monthly price updated. It takes effect on the next billing cycle.",
        "landlord": landlord.to_dict(),
        "subscription": subscription.to_dict() if subscription else None,
    }), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/pricing/landlords/<id>/per-unit-price
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/landlords/<int:landlord_id>/per-unit-price", methods=["PUT"])
@jwt_required()
def set_per_unit_price(landlord_id):
    """
    Override the per-unit price for a specific landlord, bypassing the
    package tier calculation.  Useful for enterprise/custom negotiations.

    Body:
      { per_unit_price: number | null,   -- null clears the override
        reason: str }                    -- mandatory

    When per_unit_price is set to null, the landlord falls back to their
    assigned package's pricing on the next billing cycle.
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Per-unit price set.}
      400: {description: Validation error.}
      404: {description: Landlord not found.}
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    data          = request.get_json(silent=True) or {}
    per_unit_price = data.get("per_unit_price")
    reason        = (data.get("reason") or "").strip()

    if not reason:
        return jsonify({"error": "A reason is required for per-unit price overrides."}), 400

    before = {"per_unit_price": str(landlord.per_unit_price) if landlord.per_unit_price else None}

    landlord.per_unit_price = (
        Decimal(str(per_unit_price)) if per_unit_price is not None else None
    )
    db.session.commit()

    after = {"per_unit_price": str(landlord.per_unit_price) if landlord.per_unit_price else None}

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord.id,
        action="admin_set_per_unit_price",
        entity_type="landlord",
        entity_id=landlord.id,
        description=(
            f"ADMIN: Per-unit price for '{landlord.company_name}' set to "
            f"{per_unit_price or 'None (cleared)'}. Reason: {reason}"
        ),
        before_data=before,
        after_data=after,
    )
    db.session.commit()

    return jsonify({
        "message":       "Per-unit price updated.",
        "landlord_id":   landlord.id,
        "per_unit_price": str(landlord.per_unit_price) if landlord.per_unit_price else None,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/pricing/landlords/<id>/billing  — full billing detail (#16)
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/landlords/<int:landlord_id>/billing", methods=["GET"])
@jwt_required()
def get_landlord_billing(landlord_id):
    """
    #16 — the billing detail an admin sees when opening a landlord under a package:
    billing cycle, amount due, subscription status, next billing date, whether the
    trial is active and when it ends, plus the negotiated per-unit price (custom).
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404
    sub = landlord.subscription
    pkg = landlord.package
    return jsonify({
        "landlord_id":       landlord.id,
        "company_name":      landlord.company_name,
        "package":           pkg.to_dict() if pkg else None,
        "is_custom_package": bool(pkg and pkg.is_custom),
        "per_unit_price":    str(landlord.per_unit_price) if landlord.per_unit_price is not None else None,
        "is_on_trial":       landlord.is_on_trial,
        "trial_ends_at":     landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
        "subscription":      sub.to_dict() if sub else None,
        "access":            _access_state(landlord),
    }), 200


# ---------------------------------------------------------------------------
# PUT /api/admin/pricing/landlords/<id>/billing  — admin edits billing (#16)
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/landlords/<int:landlord_id>/billing", methods=["PUT"])
@jwt_required()
def update_landlord_billing(landlord_id):
    """
    #16 — the admin states this landlord's billing reality, and it STANDS.

    Every field is optional; whatever is sent is applied. Nothing here is
    "suggested to" the billing engine — an explicit edit pins the value so the
    nightly roll-forward and the status settler cannot quietly undo it:

      * setting `status` to something new pins it (admin_status_locked)
      * moving `next_billing_date` forward clears the overdue clock, so the
        account does NOT re-lock a few days later
      * `admin_override_mode` 'open'/'closed' forces the portal open or shut
        regardless of balance, status or trial
      * `admin_billing_frozen` stops auto-charges and auto-date-advancement

    Body (all optional): { amount_due, next_billing_date (YYYY-MM-DD), status,
      billing_cycle, is_on_trial, trial_ends_at, balance_due_since,
      access_override_until, access_override_reason,
      admin_override_mode: 'open'|'closed'|'system', admin_status_locked: bool,
      admin_billing_frozen: bool, admin_override_reason: str }

    Bad input is answered with a precise 400/422 — never a 500. Every parse and
    every enum is checked before anything is written.
    """
    from datetime import datetime, date as _date, timedelta
    from models import SubscriptionStatus
    from services.billing_service import normalize_cycle, valid_cycles

    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    from services.billing_service import recompute_subscription
    sub = landlord.subscription or recompute_subscription(landlord)
    data = request.get_json(silent=True) or {}

    def _snapshot():
        return {
            "amount_due": str(sub.amount_due) if sub else None,
            "next_billing_date": str(sub.next_billing_date) if sub and sub.next_billing_date else None,
            "balance_due_since": str(sub.balance_due_since) if sub and sub.balance_due_since else None,
            "status": sub.status if sub else None,
            "billing_cycle": sub.billing_cycle if sub else None,
            "is_on_trial": landlord.is_on_trial,
            "trial_ends_at": landlord.trial_ends_at.isoformat() if landlord.trial_ends_at else None,
            "access_override_until": str(sub.access_override_until) if sub and sub.access_override_until else None,
            "admin_override_mode": getattr(sub, "admin_override_mode", None),
            "admin_status_locked": getattr(sub, "admin_status_locked", False),
            "admin_billing_frozen": getattr(sub, "admin_billing_frozen", False),
        }

    before = _snapshot()

    # ── Parsing helpers that REPORT instead of exploding ─────────────────────
    # A date typed as 05/11/2026 used to raise straight out of the request and
    # surface as "An unexpected error occurred. Our team has been notified."
    errors: dict[str, str] = {}

    def _date_field(key):
        """(ok, value) — value is None when the field clears the date."""
        raw = data.get(key)
        if raw in (None, ""):
            return True, None
        text = str(raw).strip().replace("Z", "")
        for parse in (lambda v: datetime.fromisoformat(v).date(),
                      lambda v: _date.fromisoformat(v[:10])):
            try:
                return True, parse(text)
            except (ValueError, TypeError):
                continue
        errors[key] = "Use the date format YYYY-MM-DD."
        return False, None

    def _money_field(key):
        raw = data.get(key)
        if raw is None or raw == "":
            return True, None
        try:
            return True, Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            errors[key] = "Enter a number."
            return False, None

    # ── Validate everything up front; write nothing until it all passes ──────
    _, amount_due = _money_field("amount_due")
    nbd_given = "next_billing_date" in data
    _, next_billing_date = _date_field("next_billing_date")
    bds_given = "balance_due_since" in data
    _, balance_due_since = _date_field("balance_due_since")
    trial_given = "trial_ends_at" in data
    _, trial_ends_at = _date_field("trial_ends_at")
    override_given = "access_override_until" in data
    _, access_override_until = _date_field("access_override_until")

    new_status = None
    if data.get("status"):
        new_status = str(data["status"]).strip().lower()
        valid_statuses = [e.value for e in SubscriptionStatus]
        if new_status not in valid_statuses:
            errors["status"] = f"Must be one of: {', '.join(valid_statuses)}."

    new_cycle = None
    if data.get("billing_cycle"):
        raw_cycle = str(data["billing_cycle"]).strip().lower()
        new_cycle = normalize_cycle(raw_cycle, default="")
        if not new_cycle:
            errors["billing_cycle"] = f"Must be one of: {', '.join(valid_cycles())}."

    mode_given = "admin_override_mode" in data
    new_mode = None
    if mode_given:
        raw_mode = data.get("admin_override_mode")
        raw_mode = (str(raw_mode).strip().lower() if raw_mode not in (None, "") else "system")
        if raw_mode in ("system", "none", "auto"):
            new_mode = None
        elif raw_mode in ("open", "closed"):
            new_mode = raw_mode
        else:
            errors["admin_override_mode"] = "Must be 'open', 'closed' or 'system'."

    # Forcing an account open or shut is a commercial decision — it is recorded
    # with a reason so the audit trail explains it later.
    reason = (data.get("admin_override_reason") or "").strip()
    if mode_given and new_mode in ("open", "closed") and not reason \
            and not getattr(sub, "admin_override_reason", None):
        errors["admin_override_reason"] = "Give a reason — it is kept on the audit trail."

    if override_given and access_override_until and not (data.get("access_override_reason") or "").strip():
        errors["access_override_reason"] = "Give a reason for the exemption — it is shown on the audit trail."

    if errors:
        return jsonify({"error": "Some values could not be saved — see the fields below.",
                        "errors": errors}), 422

    # ── Apply ────────────────────────────────────────────────────────────────
    today = _date.today()
    status_pinned_now = False

    if amount_due is not None:
        sub.amount_due = amount_due
    if nbd_given and next_billing_date is not None:
        moved_forward = (sub.next_billing_date is None or next_billing_date > sub.next_billing_date)
        sub.next_billing_date = next_billing_date
        # THE EXTENSION ACTUALLY EXTENDS. The overdue clock used to be re-armed
        # to today on every save, so an account "opened" by pushing the due date
        # locked itself again once the grace days elapsed. Pushing the date out
        # clears the clock: nothing is overdue until the new date passes.
        if moved_forward and next_billing_date > today:
            sub.balance_due_since = None
    if bds_given:
        sub.balance_due_since = balance_due_since
    if new_status:
        # Sending a status at all is an explicit statement of what it should be,
        # so it is pinned — whether or not it differs from the current value.
        # "When I put it on, it's on." Hand control back with
        # admin_status_locked: false.
        status_pinned_now = True
        sub.status = new_status
    if new_cycle:
        sub.billing_cycle = new_cycle
    if "is_on_trial" in data:
        landlord.is_on_trial = bool(data["is_on_trial"])
        # Turning the trial on with no end date in sight would otherwise read as
        # "not on trial" everywhere (the checks require a date), so fall back to
        # the configured global trial length and say so in the response.
        if landlord.is_on_trial and not trial_ends_at and landlord.trial_ends_at is None:
            from services.trial_service import apply_global_trial
            apply_global_trial(landlord)
    if trial_given:
        landlord.trial_ends_at = (datetime.combine(trial_ends_at, datetime.min.time())
                                  if trial_ends_at else None)

    if override_given:
        sub.access_override_until = access_override_until
        ovr_reason = (data.get("access_override_reason") or "").strip()
        sub.access_override_reason = ovr_reason[:255] if access_override_until else None
        sub.access_override_by = _admin_id() if access_override_until else None

    if mode_given:
        sub.admin_override_mode = new_mode
    if "admin_status_locked" in data:
        sub.admin_status_locked = bool(data["admin_status_locked"])
    elif status_pinned_now:
        # They changed the status by hand — hold it there. Without this the
        # settler rewrote it on the next page load.
        sub.admin_status_locked = True
    if "admin_billing_frozen" in data:
        sub.admin_billing_frozen = bool(data["admin_billing_frozen"])

    if reason:
        sub.admin_override_reason = reason[:255]
    if mode_given or status_pinned_now or "admin_status_locked" in data \
            or "admin_billing_frozen" in data:
        sub.admin_override_by = _admin_id()
        sub.admin_override_at = datetime.utcnow()

    # Only let the settler run when the admin did NOT state a status itself —
    # otherwise it would immediately overwrite what they just chose.
    if amount_due is not None and not new_status and not sub.admin_status_locked:
        from services.billing_service import _settle_status
        _settle_status(sub, today)

    db.session.commit()
    after = _snapshot()
    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord.id,
        action="admin_update_landlord_billing",
        entity_type="subscription",
        entity_id=sub.id if sub else None,
        description=(f"ADMIN: billing overrides applied to '{landlord.company_name}'"
                     + (f" — {reason}" if reason else ".")),
        before_data=before,
        after_data=after,
    )
    db.session.commit()
    return jsonify({
        "message": "Billing updated. Your settings are pinned and will not be changed by the system.",
        "subscription": sub.to_dict() if sub else None,
        "access": _access_state(landlord),
    }), 200


# ---------------------------------------------------------------------------
# POST /api/admin/pricing/landlords/<id>/custom  — add landlord to Custom (#17)
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/landlords/<int:landlord_id>/custom", methods=["POST"])
@jwt_required()
def add_landlord_to_custom(landlord_id):
    """
    #17 — move a landlord into the Custom package and set their negotiated per-unit
    price. Body: { per_unit_price: number, reason?: str }. The Custom package is the
    single is_custom=True package; per-unit price is stored on the landlord record.
    """
    _require_admin()
    landlord = db.session.get(Landlord, landlord_id)
    if not landlord:
        return jsonify({"error": "Landlord not found."}), 404

    custom_pkg = Package.query.filter_by(is_custom=True, is_active=True).first()
    if not custom_pkg:
        return jsonify({"error": "No Custom package exists."}), 404

    data = request.get_json(silent=True) or {}
    price = data.get("per_unit_price")
    if price is None:
        return jsonify({"error": "per_unit_price is required."}), 400

    landlord.package_id = custom_pkg.id
    landlord.per_unit_price = Decimal(str(price))

    # Refresh the derived subscription figures for the new custom price.
    from services.billing_service import recompute_subscription
    recompute_subscription(landlord)
    db.session.commit()

    record_audit(
        actor_user_id=_admin_id(),
        landlord_id=landlord.id,
        action="admin_add_landlord_to_custom",
        entity_type="landlord",
        entity_id=landlord.id,
        description=f"ADMIN: '{landlord.company_name}' added to Custom package at KES {price}/unit. {data.get('reason', '')}".strip(),
    )
    db.session.commit()
    return jsonify({
        "message": "Landlord added to the Custom package.",
        "landlord_id": landlord.id,
        "per_unit_price": str(landlord.per_unit_price),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/admin/pricing/packages/<id>/analytics
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages/<int:package_id>/analytics", methods=["GET"])
@jwt_required()
def package_analytics_view(package_id):
    """
    Per-package performance: subscriber count, active/inactive split,
    all-time and period revenue, an estimated MRR, a monthly series for
    charting, and the subscriber roster with what each landlord pays.
    Filters: ?start_date=, ?end_date=, ?months= (default 6)
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Package analytics.}
      404: {description: Package not found.}
    """
    _require_admin()
    from services.pricing_analytics_service import package_analytics

    months = request.args.get("months", 6, type=int)
    data = package_analytics(
        package_id,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        months=max(1, min(months, 24)),
    )
    if data is None:
        abort(404, description="Package not found.")
    return jsonify(data), 200


# ---------------------------------------------------------------------------
# GET /api/admin/pricing/packages/<id>/report
# ---------------------------------------------------------------------------
@admin_pricing_bp.route("/packages/<int:package_id>/report", methods=["GET"])
@jwt_required()
def package_report_view(package_id):
    """
    Download a per-package performance report as PDF or Excel.
    ?format=pdf|excel (default pdf), ?start_date=, ?end_date=
    ---
    tags: [Admin — Pricing]
    security:
      - Bearer: []
    responses:
      200: {description: Report file (PDF/Excel).}
      404: {description: Package not found.}
    """
    _require_admin()
    from services.pricing_analytics_service import package_report
    from flask import Response

    fmt = request.args.get("format", "pdf").lower()
    fmt = "excel" if fmt in ("excel", "xlsx") else "pdf"

    file_bytes = package_report(
        package_id, fmt,
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
    )
    if file_bytes is None:
        abort(404, description="Package not found.")

    pkg = _get_pkg_or_404(package_id)
    safe_name = "".join(c if c.isalnum() else "_" for c in pkg.name) or "package"
    mime = "application/pdf" if fmt == "pdf" else \
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ext = "pdf" if fmt == "pdf" else "xlsx"
    return Response(
        file_bytes,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename=package_report_{safe_name}.{ext}"},
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _get_pkg_or_404(package_id: int) -> Package:
    pkg = db.session.get(Package, package_id)
    if not pkg:
        abort(404, description="Package not found.")
    return pkg

def _access_state(landlord):
    from services.billing_service import access_state
    return access_state(landlord)
