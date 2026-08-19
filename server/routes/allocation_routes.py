"""
routes/allocation_routes.py — the payment allocation engine's API
Blueprint: allocation_bp  |  Prefix: /api  (full paths declared per route)

sahilpay_payment_allocation_spec.md §6. Ingestion, the suspense/review queue,
manual allocation, reversals, allocation settings, commission rules, pay-codes
and payouts.

Every write is landlord-scoped through get_current_landlord_id() and, where a
property is involved, through the existing team-member property scoping — a
crafted id for another account's payment is a 404, not a 403 leak of its
existence.
"""

from datetime import date, datetime

from flask import Blueprint, Response, request
from flask_jwt_extended import jwt_required

from extensions import db
from decorators import (
    get_current_landlord_id, require_landlord_or_team, require_permission,
)
from models import (
    AllocationAudit, AllocationMethod, CommissionRule, CommissionScopeType,
    CommissionRateType, InboundPaymentSource, Landlord, OwnerPayout, Payment,
    PaymentStatus, Property, Unit,
)
from services import pay_code_service, payment_resolver, payout_service
from services.audit_service import record_audit
from utils import ApiError, accessible_property_ids, get_jwt_user, success

allocation_bp = Blueprint("allocation", __name__, url_prefix="/api")


def _actor_id():
    try:
        return get_jwt_user().id
    except ApiError:
        return None


def _landlord():
    landlord = db.session.get(Landlord, get_current_landlord_id())
    if landlord is None:
        raise ApiError("Landlord account not found.", status=404)
    return landlord


def _scoped_payment(payment_id: int, landlord_id: int) -> Payment:
    payment = db.session.get(Payment, payment_id)
    if payment is None or payment.is_deleted or payment.landlord_id != landlord_id:
        raise ApiError("Payment not found.", status=404)
    visible = accessible_property_ids()
    if visible is not None and payment.property_id and payment.property_id not in visible:
        raise ApiError("Payment not found.", status=404)
    return payment


def _parse_date(value, fallback=None):
    if not value:
        return fallback
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("Use YYYY-MM-DD for dates.", status=422)


# ===========================================================================
# Allocation settings (§4.4)
# ===========================================================================

@allocation_bp.route("/settings/allocation-method", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def get_allocation_method():
    landlord = _landlord()
    return success({
        "allocation_method": landlord.allocation_method or AllocationMethod.phone.value,
        "tax_withholding_enabled": bool(landlord.tax_withholding_enabled),
        "options": [
            {
                "value": AllocationMethod.unit_code.value,
                "label": "Unit code",
                "description": ("Tenants pay quoting their unit's code, so every "
                                "payment names exactly one unit. Recommended."),
            },
            {
                "value": AllocationMethod.phone.value,
                "label": "Phone number",
                "description": ("Matches what most tenants already do. Unit codes "
                                "still work as a fallback, and a tenant renting "
                                "several units is held for you to split."),
            },
        ],
    })


@allocation_bp.route("/settings/allocation-method", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def set_allocation_method():
    landlord = _landlord()
    data = request.get_json(silent=True) or {}

    method = (data.get("allocation_method") or "").strip()
    if method:
        if method not in (m.value for m in AllocationMethod):
            raise ApiError("Unknown allocation method.", status=422)
        landlord.allocation_method = method
        # Switching to unit-code is useless until every unit HAS one, so top up
        # any that are missing rather than leaving silent gaps.
        if method == AllocationMethod.unit_code.value:
            pay_code_service.backfill_account(landlord.id)

    if "tax_withholding_enabled" in data:
        landlord.tax_withholding_enabled = bool(data["tax_withholding_enabled"])

    db.session.commit()
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="allocation_settings_update", entity_type="settings",
                 entity_id=landlord.id,
                 description=f"Allocation method set to {landlord.allocation_method}.")
    return success({
        "allocation_method": landlord.allocation_method,
        "tax_withholding_enabled": landlord.tax_withholding_enabled,
    }, message="Saved.")


# ===========================================================================
# Unit pay-codes (§4.3)
# ===========================================================================

@allocation_bp.route("/units/<int:unit_id>/pay-code", methods=["PUT"])
@jwt_required()
@require_landlord_or_team()
@require_permission("units", "edit")
def set_pay_code(unit_id: int):
    landlord = _landlord()
    unit = db.session.get(Unit, unit_id)
    if unit is None or unit.is_deleted or unit.landlord_id != landlord.id:
        raise ApiError("Unit not found.", status=404)
    visible = accessible_property_ids()
    if visible is not None and unit.property_id not in visible:
        raise ApiError("Unit not found.", status=404)

    data = request.get_json(silent=True) or {}
    previous = unit.pay_code
    code = pay_code_service.assign(unit, data.get("pay_code"), landlord_id=landlord.id)
    db.session.commit()

    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="unit_pay_code_update", entity_type="unit", entity_id=unit.id,
                 description=f"Pay code {previous or '(none)'} → {code}.")
    return success({"pay_code": code, "previous": previous},
                   message=("Pay code saved. The old code will keep working."
                            if previous else "Pay code saved."))


@allocation_bp.route("/units/pay-code-available", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
def pay_code_available():
    """Live uniqueness check for the unit form."""
    landlord = _landlord()
    code = pay_code_service.normalise(request.args.get("code"))
    unit_id = request.args.get("unit_id")
    if not code:
        return success({"available": False, "code": None})
    return success({
        "code": code,
        "available": pay_code_service.is_available(
            landlord.id, code,
            exclude_unit_id=int(unit_id) if unit_id and unit_id.isdigit() else None,
        ),
    })


# ===========================================================================
# Payment sources (§4.2)
# ===========================================================================

@allocation_bp.route("/payment-sources", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def list_payment_sources():
    landlord = _landlord()
    sources = (db.session.query(InboundPaymentSource)
               .filter_by(landlord_id=landlord.id)
               .order_by(InboundPaymentSource.label.asc()).all())
    return success([s.to_dict() for s in sources])


@allocation_bp.route("/payment-sources", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def create_payment_source():
    landlord = _landlord()
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    if not label:
        raise ApiError("Give this paybill a name.", status=422,
                       errors={"label": "required"})

    source = InboundPaymentSource(
        landlord_id        = landlord.id,
        label              = label,
        shortcode          = (data.get("shortcode") or "").strip() or None,
        match_pattern      = (data.get("match_pattern") or "").strip() or None,
        mapped_property_id = data.get("mapped_property_id") or None,
        mapped_owner_id    = data.get("mapped_owner_id") or None,
        forwarding_phone   = (data.get("forwarding_phone") or "").strip() or None,
    )
    db.session.add(source)
    db.session.commit()
    return success(source.to_dict(), message="Paybill added.", status=201)


@allocation_bp.route("/payment-sources/<int:source_id>", methods=["PATCH"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def update_payment_source(source_id: int):
    landlord = _landlord()
    source = db.session.get(InboundPaymentSource, source_id)
    if source is None or source.landlord_id != landlord.id:
        raise ApiError("Paybill not found.", status=404)

    data = request.get_json(silent=True) or {}
    for field in ("label", "shortcode", "match_pattern", "forwarding_phone"):
        if field in data:
            setattr(source, field, (data[field] or "").strip() or None)
    if "mapped_property_id" in data:
        source.mapped_property_id = data["mapped_property_id"] or None
    if "mapped_owner_id" in data:
        source.mapped_owner_id = data["mapped_owner_id"] or None
    if "is_active" in data:
        source.is_active = bool(data["is_active"])
    db.session.commit()
    return success(source.to_dict(), message="Saved.")


# ===========================================================================
# Review queue + manual allocation (§4.7)
# ===========================================================================

@allocation_bp.route("/payments/review-queue", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def review_queue():
    """
    Everything waiting on a human: suspense payments plus unparsed inbound
    messages. Both are "money we know about but haven't attributed".
    """
    landlord = _landlord()

    query = db.session.query(Payment).filter(
        Payment.landlord_id == landlord.id,
        Payment.is_deleted.is_(False),
        Payment.status == PaymentStatus.suspense.value,
    )
    visible = accessible_property_ids()
    if visible is not None:
        query = query.filter(db.or_(Payment.property_id.is_(None),
                                    Payment.property_id.in_(visible)))
    payments = query.order_by(Payment.payment_date.desc(), Payment.id.desc()).all()

    from models import CopilotMessage, CopilotParseStatus
    unparsed = (
        db.session.query(CopilotMessage)
        .filter(CopilotMessage.landlord_id == landlord.id,
                CopilotMessage.parse_status == CopilotParseStatus.unparsed.value)
        .order_by(CopilotMessage.id.desc())
        .limit(100).all()
    )

    return success({
        "payments": [{
            **p.to_dict(),
            "tenant_name": (f"{p.tenant.first_name} {p.tenant.last_name}".strip()
                            if p.tenant else None),
        } for p in payments],
        "unparsed_messages": [m.to_dict() for m in unparsed],
        "counts": {"suspense": len(payments), "unparsed": len(unparsed)},
    })


@allocation_bp.route("/payments/<int:payment_id>/suggestion", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def payment_suggestion(payment_id: int):
    """The arrears-first split on offer. A suggestion, never applied on its own."""
    landlord = _landlord()
    payment = _scoped_payment(payment_id, landlord.id)

    if payment.suggested_split_json:
        return success({"suggestion": payment.suggested_split_json})

    phone = payment.reference_text if payment_resolver.looks_like_phone(
        payment.reference_text) else payment.payer_phone
    tenants = payment_resolver.active_leases_for_tenant_phone(landlord.id, phone)
    return success({"suggestion": payment_resolver.suggest_split(payment.amount, tenants)})


@allocation_bp.route("/payments/<int:payment_id>/allocate", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def allocate_payment(payment_id: int):
    """
    Commit a manager's split. `splits` is [{tenant_id, amount}, …].

    This is the ONLY way money leaves suspense, and every row it writes is
    tagged with the actor — nothing is ever silently split.
    """
    landlord = _landlord()
    payment = _scoped_payment(payment_id, landlord.id)
    data = request.get_json(silent=True) or {}

    payment_resolver.allocate_manually(
        payment, landlord, data.get("splits") or [], actor_user_id=_actor_id(),
    )
    db.session.commit()
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="payment_manual_allocate", entity_type="payment",
                 entity_id=payment.id,
                 description=f"Manually allocated {payment.payment_ref}.")
    return success(payment.to_dict(), message="Allocated.")


@allocation_bp.route("/payments/<int:payment_id>/reverse", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def reverse_payment_route(payment_id: int):
    landlord = _landlord()
    payment = _scoped_payment(payment_id, landlord.id)
    reason = (request.get_json(silent=True) or {}).get("reason")

    payment_resolver.reverse_payment(payment, actor_user_id=_actor_id(), reason=reason)
    db.session.commit()
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="payment_reverse", entity_type="payment", entity_id=payment.id,
                 description=f"Reversed {payment.payment_ref}.")
    return success(payment.to_dict(), message="Payment reversed and balances restored.")


@allocation_bp.route("/payments/<int:payment_id>/allocation-audit", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def payment_allocation_audit(payment_id: int):
    landlord = _landlord()
    _scoped_payment(payment_id, landlord.id)
    rows = (db.session.query(AllocationAudit)
            .filter_by(payment_id=payment_id, landlord_id=landlord.id)
            .order_by(AllocationAudit.id.asc()).all())
    return success([r.to_dict() for r in rows])


# ===========================================================================
# Commission rules (§4.8)
# ===========================================================================

@allocation_bp.route("/commission-rules", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def list_commission_rules():
    landlord = _landlord()
    rules = (db.session.query(CommissionRule)
             .filter_by(landlord_id=landlord.id)
             .order_by(CommissionRule.scope_type.asc(), CommissionRule.id.asc()).all())

    # Resolve display names so the UI doesn't need a second round trip.
    out = []
    for rule in rules:
        data = rule.to_dict()
        if rule.scope_type == CommissionScopeType.property.value and rule.scope_id:
            prop = db.session.get(Property, rule.scope_id)
            data["scope_name"] = prop.name if prop else None
        elif rule.scope_type == CommissionScopeType.unit.value and rule.scope_id:
            unit = db.session.get(Unit, rule.scope_id)
            data["scope_name"] = unit.name if unit else None
        else:
            data["scope_name"] = "Whole account"
        out.append(data)
    return success(out)


@allocation_bp.route("/commission-rules", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def create_commission_rule():
    landlord = _landlord()
    data = request.get_json(silent=True) or {}

    scope_type = (data.get("scope_type") or "").strip()
    if scope_type not in (s.value for s in CommissionScopeType):
        raise ApiError("Choose landlord, property or unit.", status=422,
                       errors={"scope_type": "invalid"})
    rate_type = (data.get("rate_type") or CommissionRateType.percentage.value).strip()
    if rate_type not in (r.value for r in CommissionRateType):
        raise ApiError("Choose a percentage or a fixed amount.", status=422)

    try:
        rate_value = float(data.get("rate_value"))
    except (TypeError, ValueError):
        raise ApiError("Enter a rate.", status=422, errors={"rate_value": "required"})
    if rate_value < 0:
        raise ApiError("A rate cannot be negative.", status=422)
    if rate_type == CommissionRateType.percentage.value and rate_value > 100:
        raise ApiError("A percentage cannot exceed 100.", status=422)

    scope_id = data.get("scope_id") or None
    if scope_type == CommissionScopeType.landlord.value:
        scope_id = None
    elif not scope_id:
        raise ApiError("Choose which property or unit this applies to.", status=422)
    elif scope_type == CommissionScopeType.property.value:
        prop = db.session.get(Property, scope_id)
        if prop is None or prop.landlord_id != landlord.id:
            raise ApiError("Property not found.", status=404)
    else:
        unit = db.session.get(Unit, scope_id)
        if unit is None or unit.landlord_id != landlord.id:
            raise ApiError("Unit not found.", status=404)

    existing = db.session.query(CommissionRule).filter_by(
        landlord_id=landlord.id, scope_type=scope_type, scope_id=scope_id).first()
    if existing is not None:
        # Upsert rather than erroring: "set the rate for this block" is one
        # intent whether or not a rule already existed.
        existing.rate_type = rate_type
        existing.rate_value = rate_value
        existing.is_active = True
        existing.notes = data.get("notes")
        db.session.commit()
        return success(existing.to_dict(), message="Commission rule updated.")

    rule = CommissionRule(
        landlord_id=landlord.id, scope_type=scope_type, scope_id=scope_id,
        rate_type=rate_type, rate_value=rate_value, notes=data.get("notes"),
    )
    db.session.add(rule)
    db.session.commit()
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="commission_rule_create", entity_type="settings",
                 entity_id=rule.id,
                 description=f"Commission rule {scope_type}={rate_value}.")
    return success(rule.to_dict(), message="Commission rule saved.", status=201)


@allocation_bp.route("/commission-rules/<int:rule_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def delete_commission_rule(rule_id: int):
    landlord = _landlord()
    rule = db.session.get(CommissionRule, rule_id)
    if rule is None or rule.landlord_id != landlord.id:
        raise ApiError("Rule not found.", status=404)
    db.session.delete(rule)
    db.session.commit()
    return success(message="Commission rule removed.")


# ===========================================================================
# Payouts (§4.10)
# ===========================================================================

@allocation_bp.route("/payouts/preview", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "view")
def preview_payouts_route():
    """
    What each owner is owed for a period.

    Query: ?period_start= &period_end=
           &include=rent,deposit,cat:4   which charge types count as collected
                                         (omit for all; rent is always in)
           &commission_basis=rent|collected
    """
    landlord = _landlord()
    today = date.today()
    start = _parse_date(request.args.get("period_start"), today.replace(day=1))
    end = _parse_date(request.args.get("period_end"), today)

    # getlist first so include=a&include=b works as well as include=a,b.
    raw_include = request.args.getlist("include") or None
    if raw_include and len(raw_include) == 1:
        raw_include = raw_include[0]
    basis = payout_service.normalise_basis(request.args.get("commission_basis"))
    include = payout_service.normalise_include(raw_include)

    return success({
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        # Everything that produced money in the window — the checklist the
        # operator ticks. Independent of `include` on purpose: unticking a box
        # must not make it disappear from the list you unticked it in.
        "available_categories": payout_service.available_categories(
            landlord.id, start, end),
        "included_categories": sorted(include) if include is not None else None,
        "commission_basis": basis,
        "payouts": payout_service.preview_payouts(
            landlord.id, start, end, include=include, commission_basis=basis),
    })


@allocation_bp.route("/payouts/generate", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def generate_payouts_route():
    landlord = _landlord()
    data = request.get_json(silent=True) or {}
    today = date.today()
    start = _parse_date(data.get("period_start"), today.replace(day=1))
    end = _parse_date(data.get("period_end"), today)

    basis = payout_service.normalise_basis(data.get("commission_basis"))
    include = payout_service.normalise_include(data.get("include_categories"))

    payouts = payout_service.generate_payouts(
        landlord.id, start, end,
        property_ids=data.get("property_ids"), created_by_user_id=_actor_id(),
        include=include, commission_basis=basis,
    )
    db.session.commit()
    # The audit line names both choices. A payout run is a money decision, and
    # "generated 3 payouts" does not let anyone reconstruct which one was made.
    included_text = ", ".join(sorted(include)) if include is not None else "every charge type"
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="payouts_generate", entity_type="settings", entity_id=None,
                 description=(f"Generated {len(payouts)} payouts for {start}–{end}; "
                              f"collected = {included_text}; "
                              f"commission charged on "
                              f"{'the total collected' if basis == 'collected' else 'rent only'}."))
    return success([p.to_dict() for p in payouts],
                   message=f"Generated {len(payouts)} "
                           f"{'payout' if len(payouts) == 1 else 'payouts'}.")


@allocation_bp.route("/payouts/<int:payout_id>/mark-paid", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("payments", "edit")
def mark_payout_paid(payout_id: int):
    landlord = _landlord()
    payout = db.session.get(OwnerPayout, payout_id)
    if payout is None or payout.landlord_id != landlord.id:
        raise ApiError("Payout not found.", status=404)

    data = request.get_json(silent=True) or {}
    payout_service.mark_paid(
        payout, method=data.get("method"), reference=data.get("reference"),
        paid_on=_parse_date(data.get("paid_on")),
    )
    db.session.commit()
    record_audit(actor_user_id=_actor_id(), landlord_id=landlord.id,
                 action="payout_mark_paid", entity_type="settings", entity_id=payout.id,
                 description=f"Payout #{payout.id} marked paid.")
    return success(payout.to_dict(), message="Marked paid.")


@allocation_bp.route("/payouts/<int:payout_id>/statement.pdf", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("reports", "view")
def payout_statement(payout_id: int):
    landlord = _landlord()
    payout = db.session.get(OwnerPayout, payout_id)
    if payout is None or payout.landlord_id != landlord.id:
        raise ApiError("Payout not found.", status=404)

    from services.payout_pdf import render_payout_statement_pdf
    pdf = render_payout_statement_pdf(payout)
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="payout-{payout.id}.pdf"',
    })
