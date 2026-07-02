"""
routes/report_routes.py — Statements & Insights Reports
Blueprint: report_bp  |  Prefix: /api/reports

All statement endpoints support ?format=pdf|excel and date/property filters.
PDF generation uses WeasyPrint via a centralised export service.
Excel generation uses openpyxl via the same service.

No report data is stored in the DB — generated on demand.
"""

from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required

from decorators import require_landlord_or_team, require_permission, get_current_landlord_id
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
# GET /api/reports/statements/tenant/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/tenant/<int:tenant_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def tenant_statement(tenant_id):
    """
    Tenant statement: transaction date, item, description, money due, money paid,
    running balance. ?format=json|pdf|excel (json=preview), ?start_date=, ?end_date=,
    ?columns=date,item,paid,...
    ---
    tags: [Reports]
    """
    doc = build_tenant_statement(
        _current_landlord(), tenant_id,
        request.args.get("start_date"), request.args.get("end_date"),
    )
    return _serve_report(doc, f"tenant_statement_{tenant_id}")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/property/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/property/<int:property_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def property_statement(property_id):
    """
    Property statement — 4 sections (tenants, expenses, occupancy, summary) with
    net-income roll-up using the per-property tax rate.
    ?format=json|pdf|excel, ?start_date=, ?end_date=, ?columns=tenants.rent,...
    """
    doc = build_property_statement(
        _current_landlord(), property_id,
        request.args.get("start_date"), request.args.get("end_date"),
    )
    return _serve_report(doc, f"property_statement_{property_id}")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/arrears
# ---------------------------------------------------------------------------
@report_bp.route("/statements/arrears", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def arrears_report():
    """Tenants in arrears (unit, name, phone, arrears b/f, current bills, total, days).
    ?format=json|pdf|excel, ?property_id=, ?as_of_date=, ?columns="""
    doc = build_arrears_report(
        _current_landlord(),
        request.args.get("property_id", type=int),
        request.args.get("as_of_date"),
    )
    return _serve_report(doc, "arrears_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/expenses
# ---------------------------------------------------------------------------
@report_bp.route("/statements/expenses", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def expenses_report():
    """Expenses report (date, property, unit, category, description, amount).
    ?format=json|pdf|excel, ?property_id=, ?start_date=, ?end_date=, ?columns="""
    doc = build_expenses_report(
        _current_landlord(),
        request.args.get("property_id", type=int),
        request.args.get("start_date"),
        request.args.get("end_date"),
    )
    return _serve_report(doc, "expenses_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/month-on-month
# ---------------------------------------------------------------------------
@report_bp.route("/statements/month-on-month", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def mom_report():
    """Month-on-month comparative (occupancy, rent, water, bills, paid, %, expense
    per month) with per-metric graphs. ?format=json|pdf|excel, ?property_id=,
    ?year=, ?columns=, ?charts="""
    doc = build_mom_report(
        _current_landlord(),
        request.args.get("property_id", type=int),
        request.args.get("year", type=int),
    )
    return _serve_report(doc, "month_on_month_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/year-on-year
# ---------------------------------------------------------------------------
@report_bp.route("/statements/year-on-year", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def yoy_report():
    """Year-on-year comparative (same metrics as MoM, bucketed by year) with graphs.
    ?format=json|pdf|excel, ?property_id=, ?columns=, ?charts="""
    doc = build_yoy_report(
        _current_landlord(),
        request.args.get("property_id", type=int),
    )
    return _serve_report(doc, "year_on_year_report")


# ---------------------------------------------------------------------------
# GET /api/reports/statements/grouping/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/grouping/<int:group_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def grouping_report(group_id):
    """Property-grouping report — every property in the group compared across the
    comparative metrics, with a group total. ?format=json|pdf|excel, ?start_date=,
    ?end_date=, ?columns=, ?charts="""
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
@require_permission("tenants", "view")
def deleted_tenants_report():
    """Archived (soft-deleted) tenants — unit, name, phone, move-in/out, deleted-on,
    balance, deposits, notes. ?format=json|pdf|excel, ?property_id=, ?columns="""
    doc = build_deleted_tenants_report(
        _current_landlord(),
        request.args.get("property_id", type=int),
    )
    return _serve_report(doc, "deleted_tenants_report")


# ---------------------------------------------------------------------------
# GET /api/reports/insights
# ---------------------------------------------------------------------------
@report_bp.route("/insights", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
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

    prop_query = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if prop_filter:
        prop_query = prop_query.filter(Property.id == prop_filter)

    result = []
    for prop in prop_query.all():
        tenants = (
            Tenant.query
            .join(Unit, Unit.id == Tenant.unit_id)
            .filter(Unit.property_id == prop.id, Tenant.is_deleted.is_(False))
            .all()
        )
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
@require_permission("properties", "view")
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