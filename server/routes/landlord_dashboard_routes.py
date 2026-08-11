"""
routes/landlord_dashboard_routes.py — Landlord Dashboard Aggregates
Blueprint: dashboard_bp  |  Prefix: /api/dashboard

Four read-only endpoints that power §4.1 of the spec:
  /summary          — key KPI cards
  /unpaid-tenants   — arrears list
  /performance-graph — 3-series last-month chart
  /quick-actions    — data lookups for the quick-actions panel

All queries are scoped to the authenticated landlord's ID (pulled
from the JWT).  Team members reach these same endpoints; when a member is
restricted to specific properties, @scope_to_accessible_properties puts their
allowed property ids on g and EVERY aggregate below filters by them — a
caretaker who can only see one block must not read the whole portfolio's
arrears, occupancy or tenant phone numbers off the landing page.

Deliberately NOT permission-gated: the dashboard is the landing page every team
member lands on after login, so gating it on a module would leave e.g. a
caretaker staring at a 403. It is scoped instead, and each figure is derived
only from properties the caller may legitimately see.
"""

from datetime import datetime, date, timedelta
from calendar import monthrange

from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt

from extensions import db
from models import (
    Tenant, Invoice, InvoiceLineItem, Payment, Expense, Unit, Property,
    InvoiceStatus, PaymentStatus,
)
from decorators import (
    require_landlord_or_team, get_current_landlord_id, scope_to_accessible_properties,
)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


def _accessible_property_ids():
    """
    The property ids the caller may see, or None for no restriction.
    Set by @scope_to_accessible_properties; None for landlords, admins and
    team members with property_access_all.
    """
    return g.get("accessible_property_ids")


def _scope_tenants(query):
    """Restrict a Tenant query to the caller's accessible properties."""
    ids = _accessible_property_ids()
    if ids is None:
        return query
    return query.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id.in_(ids))

# Charge-category ledger rules (spec §4.5): exclude synthetic credit re-applications
# from "collected", and carried-forward b/f lines from "invoiced" (both re-present
# money/debt already counted). NULL-safe so legacy rows with no source still count.
_NOT_CREDIT = db.func.coalesce(Payment.source, "") != "credit"
_NOT_BF = db.func.coalesce(InvoiceLineItem.subcategory, "") != "balance"


# ---------------------------------------------------------------------------
# GET /api/dashboard/summary
# ---------------------------------------------------------------------------
@dashboard_bp.route("/summary", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@scope_to_accessible_properties
def get_summary():
    """
    Returns the four KPI cards shown at the top of the landlord dashboard:
      - total_arrears      : sum of negative tenant balances
      - total_advances     : sum of positive tenant balances (overpaid)
      - occupancy_percent  : (occupied units / total active units) * 100
      - payments_this_month / invoices_this_month  (payments-vs-invoices widget)
    ---
    tags: [Dashboard]
    security:
      - Bearer: []
    responses:
      200:
        description: Dashboard KPI summary.
    """
    landlord_id  = get_current_landlord_id()
    property_ids = _accessible_property_ids()

    # ── Active tenants grouped by balance sign ────────────────────────────────
    tenants = _scope_tenants(
        Tenant.query.filter(
            Tenant.landlord_id == landlord_id,
            Tenant.is_deleted.is_(False),
        )
    ).all()
    total_arrears  = sum(abs(float(t.balance)) for t in tenants if t.balance < 0)
    total_advances = sum(float(t.balance)       for t in tenants if t.balance > 0)

    # ── Occupancy ─────────────────────────────────────────────────────────────
    unit_query = (
        db.session.query(
            db.func.count(Unit.id).label("total"),
            db.func.sum(db.cast(Unit.is_occupied, db.Integer)).label("occupied"),
        )
        .join(Property, Property.id == Unit.property_id)
        .filter(
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
            Unit.is_deleted.is_(False),
        )
    )
    if property_ids is not None:
        unit_query = unit_query.filter(Property.id.in_(property_ids))
    unit_totals = unit_query.first()
    total_units    = unit_totals.total    or 0
    occupied_units = unit_totals.occupied or 0
    occupancy_pct  = round((occupied_units / total_units * 100), 1) if total_units else 0.0

    # ── Payments vs Invoices this month ───────────────────────────────────────
    today        = date.today()
    month_start  = date(today.year, today.month, 1)

    payments_q = (
        db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
        .filter(
            Payment.landlord_id == landlord_id,
            Payment.is_deleted.is_(False),
            Payment.status == PaymentStatus.confirmed.value,
            Payment.payment_date >= month_start,
            _NOT_CREDIT,
        )
    )
    invoices_q = (
        db.session.query(db.func.coalesce(db.func.sum(InvoiceLineItem.amount), 0))
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(
            Invoice.landlord_id == landlord_id,
            Invoice.is_deleted.is_(False),
            Invoice.issue_date >= month_start,
            _NOT_BF,
        )
    )
    if property_ids is not None:
        payments_q = payments_q.filter(Payment.property_id.in_(property_ids))
        invoices_q = invoices_q.filter(Invoice.property_id.in_(property_ids))

    payments_this_month = payments_q.scalar()
    invoices_this_month = invoices_q.scalar()

    return jsonify({
        "total_arrears":          round(float(total_arrears), 2),
        "total_advances":         round(float(total_advances), 2),
        "total_units":            total_units,
        "occupied_units":         occupied_units,
        "occupancy_percent":      occupancy_pct,
        "payments_this_month":    round(float(payments_this_month), 2),
        "invoices_this_month":    round(float(invoices_this_month), 2),
        "active_tenants":         len(tenants),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/dashboard/unpaid-tenants
# ---------------------------------------------------------------------------
@dashboard_bp.route("/unpaid-tenants", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@scope_to_accessible_properties
def get_unpaid_tenants():
    """
    Returns a list of tenants with a negative balance (arrears).
    Sorted by balance ascending (most overdue first).
    Supports ?page and ?per_page for pagination.
    ---
    tags: [Dashboard]
    security:
      - Bearer: []
    parameters:
      - name: page
        in: query
        type: integer
      - name: per_page
        in: query
        type: integer
    responses:
      200:
        description: Paginated arrears list.
    """
    landlord_id = get_current_landlord_id()
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    from sqlalchemy.orm import joinedload

    per_page = min(per_page, 100)

    query = _scope_tenants(
        Tenant.query.filter(
            Tenant.landlord_id == landlord_id,
            Tenant.is_deleted.is_(False),
            Tenant.balance < 0,
        )
    ).options(
        # unit + property are read for every row below — without this the list
        # costs 2 extra queries per tenant.
        joinedload(Tenant.unit).joinedload(Unit.property)
    ).order_by(Tenant.balance.asc())

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for t in paginated.items:
        d = t.to_dict()
        # Attach unit + property name for quick display
        unit = t.unit
        d["unit_name"]     = unit.name       if unit else None
        d["property_name"] = unit.property.name if (unit and unit.property) else None
        items.append(d)

    return jsonify({
        "tenants":      items,
        "total":        paginated.total,
        "pages":        paginated.pages,
        "current_page": paginated.page,
    }), 200


# ---------------------------------------------------------------------------
# GET /api/dashboard/performance-graph
# ---------------------------------------------------------------------------
@dashboard_bp.route("/performance-graph", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@scope_to_accessible_properties
def get_performance_graph():
    """
    Returns three daily-bucketed data series for the last calendar month:
      - payments   : sum of confirmed payment amounts per day
      - invoices   : sum of invoice total_amounts per day
      - expenses   : sum of expense amounts per day

    The frontend renders these as three lines on a single chart.
    Query param ?months=N (default 1) lets the client fetch more history.
    ---
    tags: [Dashboard]
    security:
      - Bearer: []
    parameters:
      - name: months
        in: query
        type: integer
        default: 1
    responses:
      200:
        description: Three data series bucketed by day.
    """
    landlord_id  = get_current_landlord_id()
    property_ids = _accessible_property_ids()
    months       = min(request.args.get("months", 1, type=int), 12)

    today     = date.today()
    # Start = first day of (months) months ago
    year      = today.year
    month     = today.month - months
    while month <= 0:
        month += 12
        year  -= 1
    start_date = date(year, month, 1)

    # Daily sums — Payments (exclude synthetic credit re-applications)
    payments_q = (
        db.session.query(
            Payment.payment_date.label("day"),
            db.func.coalesce(db.func.sum(Payment.amount), 0).label("total"),
        )
        .filter(
            Payment.landlord_id == landlord_id,
            Payment.is_deleted.is_(False),
            Payment.status == PaymentStatus.confirmed.value,
            Payment.payment_date >= start_date,
            _NOT_CREDIT,
        )
    )

    # Daily sums — Invoices (exclude carried-forward b/f lines)
    invoices_q = (
        db.session.query(
            Invoice.issue_date.label("day"),
            db.func.coalesce(db.func.sum(InvoiceLineItem.amount), 0).label("total"),
        )
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(
            Invoice.landlord_id == landlord_id,
            Invoice.is_deleted.is_(False),
            Invoice.issue_date >= start_date,
            _NOT_BF,
        )
    )

    # Daily sums — Expenses
    expenses_q = (
        db.session.query(
            Expense.expense_date.label("day"),
            db.func.coalesce(db.func.sum(Expense.amount), 0).label("total"),
        )
        .filter(
            Expense.landlord_id == landlord_id,
            Expense.is_deleted.is_(False),
            Expense.expense_date >= start_date,
        )
    )

    if property_ids is not None:
        payments_q = payments_q.filter(Payment.property_id.in_(property_ids))
        invoices_q = invoices_q.filter(Invoice.property_id.in_(property_ids))
        expenses_q = expenses_q.filter(Expense.property_id.in_(property_ids))

    payments_rows = payments_q.group_by(Payment.payment_date).all()
    invoice_rows  = invoices_q.group_by(Invoice.issue_date).all()
    expense_rows  = expenses_q.group_by(Expense.expense_date).all()

    def rows_to_dict(rows):
        return {str(r.day): float(r.total) for r in rows}

    return jsonify({
        "start_date": str(start_date),
        "end_date":   str(today),
        "payments":   rows_to_dict(payments_rows),
        "invoices":   rows_to_dict(invoice_rows),
        "expenses":   rows_to_dict(expense_rows),
    }), 200


# ---------------------------------------------------------------------------
# GET /api/dashboard/quick-actions
# ---------------------------------------------------------------------------
@dashboard_bp.route("/quick-actions", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@scope_to_accessible_properties
def get_quick_actions():
    """
    Lightweight data lookups that power the 'Quick Actions' tab.
    Returns property and unit lists (id + name only) for dropdown
    selectors in the quick-action forms, plus live vacancy count.
    ---
    tags: [Dashboard]
    security:
      - Bearer: []
    responses:
      200:
        description: Selectors and counts for quick-action forms.
    """
    landlord_id  = get_current_landlord_id()
    property_ids = _accessible_property_ids()

    props_q = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if property_ids is not None:
        props_q = props_q.filter(Property.id.in_(property_ids))
    properties = props_q.order_by(Property.name).all()
    property_list = [{"id": p.id, "name": p.name} for p in properties]

    # Vacant units — for "add tenant" shortcut
    vacancy_q = (
        db.session.query(db.func.count(Unit.id))
        .join(Property, Property.id == Unit.property_id)
        .filter(
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
            Unit.is_deleted.is_(False),
            Unit.is_occupied.is_(False),
        )
    )
    if property_ids is not None:
        vacancy_q = vacancy_q.filter(Property.id.in_(property_ids))
    vacancies = vacancy_q.scalar()

    return jsonify({
        "properties":     property_list,
        "vacant_units":   vacancies or 0,
    }), 200