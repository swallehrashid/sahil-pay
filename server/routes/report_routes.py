"""
routes/report_routes.py — Statements & Insights Reports
Blueprint: report_bp  |  Prefix: /api/reports

All statement endpoints support ?format=pdf|excel and date/property filters.
PDF generation uses WeasyPrint via a centralised export service.
Excel generation uses openpyxl via the same service.

No report data is stored in the DB — generated on demand.
"""

from flask import Blueprint, request, jsonify, Response, g
from flask_jwt_extended import jwt_required

from services.report_access import require_report
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
    scope_to_accessible_properties,
)
from services.export_service import generate_occupancy_report
from services.report_builder import document_to_json, parse_column_selection, render_document
from services.report_generators import (
    build_arrears_report,
    build_deleted_tenants_report,
    build_expenses_report,
    build_grouping_report,
    build_mom_report,
    build_property_statement,
    build_tenant_statement,
    build_yoy_report,
)

report_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def _current_landlord():
    """Resolve the Landlord ORM row for the calling (landlord or team) user."""
    from models import Landlord

    return Landlord.query.filter_by(id=get_current_landlord_id()).first()


# ---------------------------------------------------------------------------
# Scope guards
# ---------------------------------------------------------------------------
# A report is the richest export in the product — a property statement carries
# every tenant's name, phone, balance and the property's whole P&L. So the
# subject of a report has to be checked against the caller's scope BEFORE it is
# built, on two axes:
#
#   1. the landlord axis — the subject must belong to the calling account
#      (the generators already filter on landlord_id, but they answer a missing
#      subject with a "Not found" DOCUMENT at HTTP 200, which is
#      indistinguishable from success to any caller probing for ids);
#   2. the property axis — a team member restricted to certain properties must
#      not pull a statement for a property they cannot open. Under a property
#      manager, that is one owner reading a rival owner's book.
#
# Both answer 404: an object outside your scope should not even confirm it exists.

def _accessible_property_ids():
    return g.get("accessible_property_ids")


def _property_in_scope(property_id: int) -> bool:
    """True when the caller may report on this property."""
    from models import Property

    landlord_id = get_current_landlord_id()
    prop = Property.query.filter_by(
        id=property_id, landlord_id=landlord_id, is_deleted=False
    ).first()
    if prop is None:
        return False
    allowed = _accessible_property_ids()
    return allowed is None or prop.id in allowed


def _tenant_in_scope(tenant_id: int) -> bool:
    """True when the caller may report on this tenant (via their unit's property)."""
    from models import Tenant, Unit

    landlord_id = get_current_landlord_id()
    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord_id).first()
    if tenant is None:
        return False
    allowed = _accessible_property_ids()
    if allowed is None:
        return True
    unit = Unit.query.filter_by(id=tenant.unit_id).first()
    return bool(unit and unit.property_id in allowed)


def _group_in_scope(group_id: int) -> bool:
    """True when the caller may report on this property group."""
    from models import Property, PropertyGroup

    landlord_id = get_current_landlord_id()
    group = PropertyGroup.query.filter_by(id=group_id, landlord_id=landlord_id).first()
    if group is None:
        return False
    allowed = _accessible_property_ids()
    if allowed is None:
        return True
    # A scoped member may only pull a group report when every property in the
    # group is one they can see — a partial group total would still expose the
    # other properties' figures in aggregate.
    group_property_ids = {
        p.id for p in Property.query.filter_by(
            property_group_id=group.id, is_deleted=False
        ).all()
    }
    return bool(group_property_ids) and group_property_ids <= set(allowed)


def _not_found_response(subject: str):
    return jsonify({"error": f"{subject} not found."}), 404


def _include_etims() -> bool:
    """
    Whether this request asked for the eTIMS column (?include_etims=true).

    Defaults to FALSE — absent means "the document exactly as it has always
    been". Even when true the generator still omits the column unless a line
    actually carries a number and its property has statements enabled, so
    ticking the box on an account with nothing recorded changes nothing
    (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §2.2, §3.2).
    """
    return (request.args.get("include_etims") or "").lower() in ("1", "true", "yes", "on")


def _requested_basis():
    """
    The gross basis for this request: ?gross_basis=all|rent_only, falling back to
    the landlord's saved preference inside the generators when absent.

    Passing ?remember=true also persists the choice, so a manager who works on
    the rent-only basis sets it once instead of every time they open a report.
    """
    basis = request.args.get("gross_basis")
    if basis and (request.args.get("remember") or "").lower() in ("1", "true", "yes"):
        from extensions import db
        from services.commission_service import normalise_basis

        landlord = _current_landlord()
        settings = getattr(landlord, "landlord_settings", None) if landlord else None
        if settings is not None:
            settings.report_gross_basis = normalise_basis(basis)
            db.session.commit()
    return basis


def _serve_report(doc, filename: str):
    """
    One response path for every structured report:
      ?format=json (default)  -> preview JSON + column catalog
      ?format=pdf | excel      -> downloadable file honoring ?columns=
    """
    fmt = (request.args.get("format") or "json").lower()
    selection = parse_column_selection(request.args.get("columns"))
    charts_raw = request.args.get("charts")
    chart_keys = [c.strip() for c in charts_raw.split(",") if c.strip()] if charts_raw else None

    if fmt == "json":
        return jsonify(document_to_json(doc, selection)), 200

    file_bytes = render_document(doc, fmt, selection, chart_keys)
    return _fmt_response(file_bytes, fmt, filename), 200


def _fmt_response(file_bytes, fmt: str, filename: str):
    mime = "application/pdf" if fmt == "pdf" else \
           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ext  = "pdf" if fmt == "pdf" else "xlsx"
    return Response(
        file_bytes,
        mimetype=mime,
        headers={"Content-Disposition": f"attachment; filename={filename}.{ext}"},
    )


# ---------------------------------------------------------------------------
# GET /api/reports/payments  — the charge-category Payments Report (§5.5)
# ---------------------------------------------------------------------------
@report_bp.route("/payments", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@require_report("payments")
def payments_report():
    """
    Consolidated per-category / per-tenant payments report.
    Query: ?category_id=<id|all>&date_from=&date_to=&property_id=
    """
    from utils import parse_date
    from services.payment_report_service import build_payments_report, build_payments_report_document

    landlord_id = get_current_landlord_id()
    category_id = request.args.get("category_id", "all")
    date_from = parse_date(request.args.get("date_from"))
    date_to = parse_date(request.args.get("date_to"))
    property_id = request.args.get("property_id", type=int)

    fmt = (request.args.get("format") or "json").lower()
    if fmt in ("pdf", "excel"):
        # Export through the shared report_builder pipeline (letterhead + signature).
        doc = build_payments_report_document(
            _current_landlord(), category_id=category_id,
            date_from=date_from, date_to=date_to, property_id=property_id,
        )
        selection = parse_column_selection(request.args.get("columns"))
        file_bytes = render_document(doc, fmt, selection, None)
        return _fmt_response(file_bytes, fmt, "payments-report"), 200

    data = build_payments_report(
        landlord_id, category_id=category_id,
        date_from=date_from, date_to=date_to, property_id=property_id,
    )
    return jsonify(data), 200


# ---------------------------------------------------------------------------
# GET /api/reports/line-items/<id>/rollover-trail  — balance provenance (§4.4)
# ---------------------------------------------------------------------------
@report_bp.route("/line-items/<int:line_id>/rollover-trail", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
def line_item_rollover_trail(line_id):
    """The origin-month breakdown of a balance line ('5,000 from May + 10,000 from June')."""
    from services.payment_report_service import rollover_trail

    landlord_id = get_current_landlord_id()
    trail = rollover_trail(line_id, landlord_id)
    if trail.get("error") == "not_found":
        return jsonify({"error": "Line item not found."}), 404
    return jsonify(trail), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/tenant/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/tenant/<int:tenant_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("tenant")
def tenant_statement(tenant_id):
    """
    Tenant statement: transaction date, item, description, money due, money paid,
    running balance. ?format=json|pdf|excel (json=preview), ?start_date=, ?end_date=,
    ?columns=date,item,paid,...
    ---
    tags: [Reports]
    """
    if not _tenant_in_scope(tenant_id):
        return _not_found_response("Tenant")

    doc = build_tenant_statement(
        _current_landlord(), tenant_id,
        request.args.get("start_date"), request.args.get("end_date"),
        include_etims=_include_etims(),
    )
    return _serve_report(doc, f"tenant_statement_{tenant_id}")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/property/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/property/<int:property_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("property")
def property_statement(property_id):
    """
    Property statement — 4 sections (tenants, expenses, occupancy, summary) with
    net-income roll-up using the per-property tax rate.
    ?format=json|pdf|excel, ?start_date=, ?end_date=, ?columns=tenants.rent,...
    """
    if not _property_in_scope(property_id):
        return _not_found_response("Property")

    doc = build_property_statement(
        _current_landlord(), property_id,
        request.args.get("start_date"), request.args.get("end_date"),
        gross_basis=_requested_basis(),
        include_etims=_include_etims(),
    )
    return _serve_report(doc, f"property_statement_{property_id}")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/arrears
# ---------------------------------------------------------------------------
@report_bp.route("/statements/arrears", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("arrears")
def arrears_report():
    """Tenants in arrears (unit, name, phone, arrears b/f, current bills, total, days).
    ?format=json|pdf|excel, ?property_id=, ?as_of_date=, ?columns="""
    requested = request.args.get("property_id", type=int)
    if requested and not _property_in_scope(requested):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    doc = build_arrears_report(
        _current_landlord(),
        requested,
        request.args.get("as_of_date"),
        allowed_property_ids=allowed,
    )
    return _serve_report(doc, "arrears_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/expenses
# ---------------------------------------------------------------------------
@report_bp.route("/statements/expenses", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("expenses")
def expenses_report():
    """Expenses report (date, property, unit, category, description, amount).
    ?format=json|pdf|excel, ?property_id=, ?start_date=, ?end_date=, ?columns="""
    requested = request.args.get("property_id", type=int)
    if requested and not _property_in_scope(requested):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    doc = build_expenses_report(
        _current_landlord(),
        requested,
        request.args.get("start_date"),
        request.args.get("end_date"),
        allowed_property_ids=allowed,
    )
    return _serve_report(doc, "expenses_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/month-on-month
# ---------------------------------------------------------------------------
@report_bp.route("/statements/month-on-month", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("mom")
def mom_report():
    """Month-on-month comparative (occupancy, rent, water, bills, paid, %, expense
    per month) with per-metric graphs. ?format=json|pdf|excel, ?property_id=,
    ?year=, ?columns=, ?charts="""
    requested = request.args.get("property_id", type=int)
    if requested and not _property_in_scope(requested):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    doc = build_mom_report(
        _current_landlord(),
        requested,
        request.args.get("year", type=int),
        allowed_property_ids=allowed,
        gross_basis=_requested_basis(),
    )
    return _serve_report(doc, "month_on_month_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/year-on-year
# ---------------------------------------------------------------------------
@report_bp.route("/statements/year-on-year", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("yoy")
def yoy_report():
    """Year-on-year comparative (same metrics as MoM, bucketed by year) with graphs.
    ?format=json|pdf|excel, ?property_id=, ?columns=, ?charts="""
    requested = request.args.get("property_id", type=int)
    if requested and not _property_in_scope(requested):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    doc = build_yoy_report(
        _current_landlord(),
        requested,
        allowed_property_ids=allowed,
        gross_basis=_requested_basis(),
    )
    return _serve_report(doc, "year_on_year_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/grouping/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/grouping/<int:group_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("grouping")
def grouping_report(group_id):
    """Property-grouping report — every property in the group compared across the
    comparative metrics, with a group total. ?format=json|pdf|excel, ?start_date=,
    ?end_date=, ?columns=, ?charts="""
    if not _group_in_scope(group_id):
        return _not_found_response("Property group")

    doc = build_grouping_report(
        _current_landlord(), group_id,
        request.args.get("start_date"),
        request.args.get("end_date"),
    )
    return _serve_report(doc, f"grouping_report_{group_id}")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/deleted-tenants
# ---------------------------------------------------------------------------
@report_bp.route("/statements/deleted-tenants", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
@require_report("deleted")
def deleted_tenants_report():
    """Archived (soft-deleted) tenants — unit, name, phone, move-in/out, deleted-on,
    balance, deposits, notes. ?format=json|pdf|excel, ?property_id=, ?columns="""
    requested = request.args.get("property_id", type=int)
    if requested and not _property_in_scope(requested):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    doc = build_deleted_tenants_report(
        _current_landlord(),
        requested,
        allowed_property_ids=allowed,
    )
    return _serve_report(doc, "deleted_tenants_report")


# ---------------------------------------------------------------------------
# GET /api/reports/insights
# ---------------------------------------------------------------------------
@report_bp.route("/insights", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
@scope_to_accessible_properties
def insights():
    """
    Per-property breakdown: tenants with arrears / advances / zero balance.
    Returns JSON (no download). ?property_id= for single-property drill-down.
    ---
    tags: [Reports]
    security:
      - Bearer: []
    responses:
      200: {description: Insights data.}
    """
    from models import Property, Tenant, Unit
    from extensions import db

    landlord_id = get_current_landlord_id()
    prop_filter = request.args.get("property_id", type=int)

    if prop_filter and not _property_in_scope(prop_filter):
        return _not_found_response("Property")
    allowed = _accessible_property_ids()

    prop_query = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if prop_filter:
        prop_query = prop_query.filter(Property.id == prop_filter)
    if allowed is not None:
        prop_query = prop_query.filter(Property.id.in_(allowed))

    properties = prop_query.all()

    # One query for every tenant in scope, bucketed by property in Python —
    # querying per property cost 100 round-trips on a 100-property estate.
    tenants_by_property = {p.id: [] for p in properties}
    if properties:
        rows = (
            db.session.query(Tenant, Unit.property_id)
            .join(Unit, Unit.id == Tenant.unit_id)
            .filter(
                Unit.property_id.in_(list(tenants_by_property.keys())),
                Tenant.is_deleted.is_(False),
            )
            .all()
        )
        for tenant, property_id in rows:
            tenants_by_property[property_id].append(tenant)

    result = []
    for prop in properties:
        tenants = tenants_by_property.get(prop.id, [])
        result.append({
            "property_id":   prop.id,
            "property_name": prop.name,
            "arrears": [
                {"tenant_id": t.id, "name": f"{t.first_name} {t.last_name}",
                 "balance": float(t.balance), "phone": t.phone}
                for t in tenants if t.balance < 0
            ],
            "advances": [
                {"tenant_id": t.id, "name": f"{t.first_name} {t.last_name}",
                 "balance": float(t.balance)}
                for t in tenants if t.balance > 0
            ],
            "zero_balance": [
                {"tenant_id": t.id, "name": f"{t.first_name} {t.last_name}"}
                for t in tenants if t.balance == 0
            ],
        })

    return jsonify({"insights": result}), 200


# ---------------------------------------------------------------------------
# GET /api/reports/insights/occupancy
# ---------------------------------------------------------------------------
@report_bp.route("/insights/occupancy", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
def occupancy_insights():
    """
    Occupancy dashboard with lost-rent estimate.
    ?property_id=, ?format=pdf|excel (optional download)
    Returns JSON by default; includes days_unoccupied and estimated_rent_lost.
    ---
    tags: [Reports]
    """
    from datetime import date as _date
    from models import Property, Unit, TenantUnitHistory
    from extensions import db

    landlord_id = get_current_landlord_id()
    prop_filter = request.args.get("property_id", type=int)
    fmt         = request.args.get("format")

    query = Unit.query.join(Property).filter(
        Property.landlord_id == landlord_id,
        Property.is_deleted.is_(False),
        Unit.is_deleted.is_(False),
    )
    if prop_filter:
        query = query.filter(Property.id == prop_filter)

    units = query.all()
    today = _date.today()

    report_data = []
    for u in units:
        days_unoccupied = 0
        estimated_lost_rent = 0.0
        if not u.is_occupied:
            last_move_out = (
                db.session.query(TenantUnitHistory.moved_out_at)
                .filter(TenantUnitHistory.unit_id == u.id, TenantUnitHistory.moved_out_at.isnot(None))
                .order_by(TenantUnitHistory.moved_out_at.desc())
                .limit(1)
                .scalar()
            )
            vacant_since = last_move_out or (u.created_at.date() if u.created_at else today)
            days_unoccupied = max((today - vacant_since).days, 0)
            estimated_lost_rent = round((days_unoccupied / 30.0) * float(u.rent_amount), 2)

        report_data.append({
            "unit_id":             u.id,
            "unit_name":           u.name,
            "property_name":       u.property.name if u.property else None,
            "is_occupied":         u.is_occupied,
            "rent_amount":         float(u.rent_amount),
            "days_unoccupied":     days_unoccupied,
            "estimated_lost_rent": estimated_lost_rent,
        })

    if fmt in ("pdf", "excel"):
        file_bytes = generate_occupancy_report(landlord_id, fmt, prop_filter)
        return _fmt_response(file_bytes, fmt, "occupancy_report"), 200

    return jsonify({"units": report_data, "total": len(report_data)}), 200