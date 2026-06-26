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
from services.export_service import (
    generate_tenant_statement,
    generate_property_statement,
    generate_arrears_report,
    generate_expenses_report,
    generate_mom_report,
    generate_yoy_report,
    generate_grouping_report,
    generate_deleted_tenants_report,
    generate_occupancy_report,
)

report_bp = Blueprint("reports", __name__, url_prefix="/api/reports")


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
    Tenant statement: transaction date, item, money due, money paid, running balance.
    ?format=pdf|excel, ?start_date=, ?end_date=
    ---
    tags: [Reports]
    """
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    start_date  = request.args.get("start_date")
    end_date    = request.args.get("end_date")

    file_bytes = generate_tenant_statement(landlord_id, tenant_id, fmt, start_date, end_date)
    return _fmt_response(file_bytes, fmt, f"tenant_statement_{tenant_id}"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/property/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/property/<int:property_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def property_statement(property_id):
    """Property-level income/expense statement. ?format=, ?start_date=, ?end_date="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_property_statement(
        landlord_id, property_id, fmt,
        request.args.get("start_date"),
        request.args.get("end_date"),
    )
    return _fmt_response(file_bytes, fmt, f"property_statement_{property_id}"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/arrears
# ---------------------------------------------------------------------------
@report_bp.route("/statements/arrears", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def arrears_report():
    """All tenants with a negative balance. ?format=, ?property_id=, ?as_of_date="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_arrears_report(
        landlord_id, fmt,
        request.args.get("property_id", type=int),
        request.args.get("as_of_date"),
    )
    return _fmt_response(file_bytes, fmt, "arrears_report"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/expenses
# ---------------------------------------------------------------------------
@report_bp.route("/statements/expenses", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def expenses_report():
    """Expenses report. ?format=, ?property_id=, ?start_date=, ?end_date="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_expenses_report(
        landlord_id, fmt,
        request.args.get("property_id", type=int),
        request.args.get("start_date"),
        request.args.get("end_date"),
    )
    return _fmt_response(file_bytes, fmt, "expenses_report"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/month-on-month
# ---------------------------------------------------------------------------
@report_bp.route("/statements/month-on-month", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def mom_report():
    """Month-on-month comparative. ?format=, ?property_id=, ?year="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_mom_report(
        landlord_id, fmt,
        request.args.get("property_id", type=int),
        request.args.get("year", type=int),
    )
    return _fmt_response(file_bytes, fmt, "month_on_month_report"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/year-on-year
# ---------------------------------------------------------------------------
@report_bp.route("/statements/year-on-year", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def yoy_report():
    """Year-on-year comparative. ?format=, ?property_id="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_yoy_report(
        landlord_id, fmt,
        request.args.get("property_id", type=int),
    )
    return _fmt_response(file_bytes, fmt, "year_on_year_report"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/grouping/<id>
# ---------------------------------------------------------------------------
@report_bp.route("/statements/grouping/<int:group_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("properties", "view")
def grouping_report(group_id):
    """Property-grouping report. ?format=, ?start_date=, ?end_date="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_grouping_report(
        landlord_id, group_id, fmt,
        request.args.get("start_date"),
        request.args.get("end_date"),
    )
    return _fmt_response(file_bytes, fmt, f"grouping_report_{group_id}"), 200


# ---------------------------------------------------------------------------
# GET /api/reports/statements/deleted-tenants
# ---------------------------------------------------------------------------
@report_bp.route("/statements/deleted-tenants", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("tenants", "view")
def deleted_tenants_report():
    """Report of all soft-deleted tenants. ?format=, ?property_id="""
    landlord_id = get_current_landlord_id()
    fmt         = request.args.get("format", "pdf")
    file_bytes  = generate_deleted_tenants_report(
        landlord_id, fmt,
        request.args.get("property_id", type=int),
    )
    return _fmt_response(file_bytes, fmt, "deleted_tenants_report"), 200


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
    from models import Property, Unit
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

    report_data = []
    for u in units:
        report_data.append({
            "unit_id":       u.id,
            "unit_name":     u.name,
            "property_name": u.property.name if u.property else None,
            "is_occupied":   u.is_occupied,
            "rent_amount":   float(u.rent_amount),
        })

    if fmt in ("pdf", "excel"):
        file_bytes = generate_occupancy_report(landlord_id, fmt, prop_filter)
        return _fmt_response(file_bytes, fmt, "occupancy_report"), 200

    return jsonify({"units": report_data, "total": len(report_data)}), 200