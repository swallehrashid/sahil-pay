"""
routes/public_routes.py — Unauthenticated marketing-site data
Blueprint: public_bp  |  Prefix: /api/public

Phase 2: the public pricing page renders the packages the admin has chosen to
feature (Package.is_featured), badged with the admin's recommended/popular
flags and ordered by display_order. No auth — this is the storefront.
"""

from flask import Blueprint, jsonify

from models import Package

public_bp = Blueprint("public", __name__, url_prefix="/api/public")


@public_bp.route("/packages", methods=["GET"])
def public_packages():
    """
    Active + featured pricing packages for the marketing site, ordered by
    display_order then price. Returns the marketing view only (no internal fields).
    ---
    tags: [Public]
    responses:
      200: {description: Featured public packages.}
    """
    packages = (
        Package.query
        # #17 — custom packages are private (per-landlord negotiated deals) and must
        # never surface on the marketing site, even if a flag were toggled.
        .filter(Package.is_active.is_(True), Package.is_featured.is_(True), Package.is_custom.is_(False))
        .order_by(Package.display_order.asc(), Package.min_units.asc())
        .all()
    )
    return jsonify({"packages": [p.to_public_dict() for p in packages]}), 200


@public_bp.route("/affiliate-program", methods=["GET"])
def public_affiliate_program():
    """
    Whether the affiliate program is currently accepting signups, plus the
    default commission rate/months so the marketing copy never drifts from
    what the admin has actually configured (AFFILIATE_PROGRAM_SPEC.md §11.1).
    ---
    tags: [Public]
    responses:
      200: {description: Affiliate program public info.}
    """
    from services.affiliate_service import get_program_config

    cfg = get_program_config()
    return jsonify({
        "is_active":               cfg.is_program_active,
        "default_commission_rate": str(cfg.default_commission_rate),
        "default_commission_months": cfg.default_commission_months,
    }), 200
