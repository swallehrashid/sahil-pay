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

from decimal import Decimal

from flask import Blueprint, request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from extensions import db
from models import Package, Landlord, UserRole
from services.audit_service import record_audit

admin_pricing_bp = Blueprint("admin_pricing", __name__, url_prefix="/api/admin/pricing")


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != UserRole.system_admin.value:
        abort(403, description="System Admin access required.")


def _admin_id() -> int:
    return int(get_jwt_identity())


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