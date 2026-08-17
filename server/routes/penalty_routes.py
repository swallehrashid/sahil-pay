"""
routes/penalty_routes.py — late-payment penalties
Blueprint: penalty_bp  |  Prefix: /api

  GET    /properties/<id>/penalty-policy    read one property's rules
  PUT    /properties/<id>/penalty-policy    create/replace them
  GET    /penalties/preview                 dry run — who would be charged today
  POST   /penalties/run                     apply now, without waiting for 02:30
  POST   /penalties/charge                  raise one penalty by hand
  GET    /reports/penalties                 the penalties report

Permission module: `invoices`. A penalty IS an invoice against a tenant, so
whoever may raise invoices may raise penalties — and nobody else. Configuring
the POLICY additionally requires `properties` edit, because switching automatic
fines on for a block is a property-level decision with financial consequences
for every tenant in it.

Everything here is property-scoped: a team member restricted to one block can
neither read nor change another block's penalty rules, and their report only
covers their own properties.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import (
    PenaltyCharge, PenaltySource, Property, Tenant, Unit,
)
from decorators import (
    require_landlord_or_team, require_permission, get_current_landlord_id,
)
from utils import success, ApiError, accessible_property_ids
from services import penalty_service as penalties
from services.report_access import require_report
from services.audit_service import record_audit

penalty_bp = Blueprint("penalties", __name__, url_prefix="/api")


def _actor_id():
    identity = get_jwt_identity()
    try:
        return int(identity)
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _decimal(value, field):
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ApiError(f"{field} must be a number.", status=422,
                       errors={field: "not_a_number"})
    if parsed < 0:
        raise ApiError(f"{field} cannot be negative.", status=422,
                       errors={field: "negative"})
    return parsed


def _property_or_404(landlord_id: int, property_id: int) -> Property:
    """
    Fetch within the account AND within the caller's property scope.

    Scope is resolved here rather than trusted from a decorator, so a team
    member restricted to one block cannot reach another block's penalty rules
    by guessing an id.
    """
    prop = (
        db.session.query(Property)
        .filter(Property.id == property_id,
                Property.landlord_id == landlord_id,
                Property.is_deleted.is_(False))
        .first()
    )
    if prop is None:
        raise ApiError("Property not found.", status=404)

    allowed = accessible_property_ids()
    if allowed is not None and prop.id not in allowed:
        raise ApiError("Property not found.", status=404)
    return prop


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@penalty_bp.route("/properties/<int:property_id>/penalty-policy", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "view")
def get_penalty_policy(property_id: int):
    """This property's penalty rules, or the off-by-default shape when unset."""
    landlord_id = get_current_landlord_id()
    prop = _property_or_404(landlord_id, property_id)

    policy = penalties.policy_for(prop.id)
    if policy is None:
        return success({
            "property_id": prop.id, "property_name": prop.name,
            "is_enabled": False, "mode": "fixed",
            "trigger_type": "day_of_month", "trigger_day": None,
            "grace_days": None, "fixed_amount": None, "percentage_rate": None,
            "min_balance": None, "max_penalty": None, "tiers": [],
        })

    data = policy.to_dict()
    data["property_name"] = prop.name
    return success(data)


@penalty_bp.route("/properties/<int:property_id>/penalty-policy", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "edit")
def put_penalty_policy(property_id: int):
    """
    Create or replace the rules.

    Gated on `penalties` edit. It was previously `properties` edit, which meant
    anyone trusted to rename a block or fix its address could also change what
    its tenants get fined — two very different levels of trust sharing one
    checkbox.
    """
    landlord_id = get_current_landlord_id()
    prop = _property_or_404(landlord_id, property_id)
    body = request.get_json(silent=True) or {}

    payload = {
        "is_enabled":      bool(body.get("is_enabled", False)),
        "mode":            body.get("mode"),
        "trigger_type":    body.get("trigger_type"),
        "trigger_day":     body.get("trigger_day"),
        "grace_days":      body.get("grace_days"),
        "fixed_amount":    _decimal(body.get("fixed_amount"), "fixed_amount"),
        "percentage_rate": _decimal(body.get("percentage_rate"), "percentage_rate"),
        "min_balance":     _decimal(body.get("min_balance"), "min_balance"),
        "max_penalty":     _decimal(body.get("max_penalty"), "max_penalty"),
    }
    if "tiers" in body:
        payload["tiers"] = [{
            "min_balance": _decimal(t.get("min_balance"), "tier.min_balance") or 0,
            "max_balance": _decimal(t.get("max_balance"), "tier.max_balance"),
            "amount_type": t.get("amount_type") or "fixed",
            "amount":      _decimal(t.get("amount"), "tier.amount") or 0,
        } for t in (body.get("tiers") or [])]

    before = policy.to_dict() if (policy := penalties.policy_for(prop.id)) else None
    saved = penalties.save_policy(prop, payload)

    record_audit(
        _actor_id(), landlord_id, "set_penalty_policy", "property", prop.id,
        f"Penalty policy for {prop.name} "
        + ("enabled." if saved.is_enabled else "saved (off)."),
        before_data=before, after_data=saved.to_dict(),
    )
    db.session.commit()
    return success(saved.to_dict(), message="Penalty rules saved.")


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

@penalty_bp.route("/penalties/preview", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "view")
def preview_penalties():
    """
    Who would be charged if the run happened on ?date= (default today), without
    writing anything. Nobody should have to discover what an automatic fine
    does by watching it land on real tenants.
    """
    landlord_id = get_current_landlord_id()
    on = _parse_date(request.args.get("date")) or date.today()

    summary = penalties.run_for_landlord(landlord_id, today=on, dry_run=True)
    summary["properties"] = _scope_summaries(summary["properties"])
    return success(summary)


@penalty_bp.route("/penalties/run", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "edit")
def run_penalties():
    """Apply now rather than waiting for the nightly job."""
    landlord_id = get_current_landlord_id()
    body = request.get_json(silent=True) or {}
    on = _parse_date(body.get("date")) or date.today()

    summary = penalties.run_for_landlord(landlord_id, today=on,
                                         actor_user_id=_actor_id())
    if summary["charged"]:
        record_audit(
            _actor_id(), landlord_id, "run_penalties", "landlord", landlord_id,
            f"{summary['charged']} penalty invoice(s) raised, "
            f"total {summary['total']}.",
        )
    db.session.commit()
    return success(summary, message=f"{summary['charged']} penalty charge(s) raised.")


@penalty_bp.route("/penalties/charge", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "edit")
def charge_one():
    """
    Raise a single penalty by hand — a second notice, or a block that has no
    automatic policy. Recorded as source='manual' so it sits outside the
    once-per-month index and is distinguishable in the report.
    """
    landlord_id = get_current_landlord_id()
    body = request.get_json(silent=True) or {}

    tenant_id = body.get("tenant_id")
    amount = _decimal(body.get("amount"), "amount")
    if not tenant_id or not amount or amount <= 0:
        raise ApiError("A tenant and a positive amount are required.", status=422)

    tenant = (
        db.session.query(Tenant)
        .filter(Tenant.id == tenant_id,
                Tenant.landlord_id == landlord_id,
                Tenant.is_deleted.is_(False))
        .first()
    )
    if tenant is None:
        raise ApiError("Tenant not found.", status=404)

    unit = tenant.unit
    if unit is None or unit.property is None:
        raise ApiError("This tenant has no unit.", status=422)
    _property_or_404(landlord_id, unit.property_id)      # scope check

    charge = penalties.charge_tenant(
        tenant, penalties.policy_for(unit.property_id), amount,
        today=_parse_date(body.get("date")) or date.today(),
        source=PenaltySource.manual.value,
        actor_user_id=_actor_id(),
        note=(body.get("note") or "").strip()[:255] or None,
    )
    if charge is None:
        raise ApiError("Nothing to charge.", status=422)

    record_audit(
        _actor_id(), landlord_id, "charge_penalty", "tenant", tenant.id,
        f"Manual penalty of {amount} raised against "
        f"{tenant.first_name} {tenant.last_name}.",
        after_data=charge.to_dict(),
    )
    db.session.commit()
    return success(charge.to_dict(), message="Penalty raised.", status=201)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@penalty_bp.route("/reports/penalties", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("penalties", "view")
@require_report("penalties")
def penalties_report():
    """
    Every penalty raised, filterable the way the other money reports are.

    Filters: ?start_date= &end_date= &property_id= &source= &min_amount=
             &max_amount= &tenant_id=
    """
    landlord_id = get_current_landlord_id()

    query = (
        db.session.query(PenaltyCharge)
        .filter(PenaltyCharge.landlord_id == landlord_id)
    )

    allowed = accessible_property_ids()
    if allowed is not None:
        # A scoped team member's report covers only their own blocks, even
        # when they ask for "all".
        query = query.filter(PenaltyCharge.property_id.in_(allowed or {0}))

    if pid := request.args.get("property_id"):
        prop = _property_or_404(landlord_id, int(pid))
        query = query.filter(PenaltyCharge.property_id == prop.id)

    if tid := request.args.get("tenant_id"):
        query = query.filter(PenaltyCharge.tenant_id == int(tid))

    if source := request.args.get("source"):
        if source not in {s.value for s in PenaltySource}:
            raise ApiError("Unknown source filter.", status=422)
        query = query.filter(PenaltyCharge.source == source)

    if start := _parse_date(request.args.get("start_date")):
        query = query.filter(PenaltyCharge.created_at >= start)
    if end := _parse_date(request.args.get("end_date")):
        # Inclusive of the end day.
        query = query.filter(
            PenaltyCharge.created_at < datetime.combine(end, datetime.max.time())
        )

    if lo := _decimal(request.args.get("min_amount"), "min_amount"):
        query = query.filter(PenaltyCharge.amount >= lo)
    if hi := _decimal(request.args.get("max_amount"), "max_amount"):
        query = query.filter(PenaltyCharge.amount <= hi)

    rows = query.order_by(PenaltyCharge.created_at.desc()).limit(2000).all()

    # Resolve names in bulk rather than per row — this report is read across a
    # thousand-unit estate.
    property_names = dict(
        db.session.query(Property.id, Property.name)
        .filter(Property.landlord_id == landlord_id).all()
    )
    tenant_rows = (
        db.session.query(Tenant.id, Tenant.first_name, Tenant.last_name,
                         Tenant.account_number)
        .filter(Tenant.landlord_id == landlord_id).all()
    )
    tenants = {t[0]: {"name": f"{t[1]} {t[2]}".strip(), "account_number": t[3]}
               for t in tenant_rows}
    unit_names = dict(db.session.query(Unit.id, Unit.name).all())

    items, total = [], Decimal("0.00")
    for row in rows:
        total += Decimal(str(row.amount))
        tenant = tenants.get(row.tenant_id, {})
        items.append({
            **row.to_dict(),
            "property_name":  property_names.get(row.property_id),
            "unit_name":      unit_names.get(row.unit_id),
            "tenant_name":    tenant.get("name"),
            "account_number": tenant.get("account_number"),
        })

    return success({
        "items": items,
        "count": len(items),
        "total": float(total),
        # Stated explicitly because it is the question every property manager
        # asks about this report, and the answer is a legal one.
        "note": "Penalties are not commissionable and are excluded from the "
                "commission base.",
    })


def _scope_summaries(summaries: list[dict]) -> list[dict]:
    """Drop properties the caller may not see from a preview summary."""
    allowed = accessible_property_ids()
    if allowed is None:
        return summaries
    return [s for s in summaries if s.get("property_id") in allowed]
