"""
routes/invoice_queue_routes.py — charges waiting for an invoice.
Blueprint: invoice_queue_bp  |  Prefix: /api/invoice-queue

    GET    /                     everything waiting, grouped by unit (?status=pending
                                 for charges a caretaker submitted for review)
    POST   /review               approve / reject pending charges (some or all)
    POST   /run-monthly          raise this month's invoices now: rent and/or
                                 approved queued charges, balance b/f included
    GET    /units/<id>           what is waiting for one unit
    POST   /units/<id>/apply     put it on an invoice now
    DELETE /<id>                 cancel one without billing it

Gated on `invoices` rather than `utilities`: what is queued is usually a meter
reading, but what happens here is billing, and the person who reads meters is
deliberately not the person who bills.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import Invoice, InvoiceStatus, QueuedCharge, Unit
from decorators import (
    accessible_property_ids, require_landlord_or_team, require_permission,
    get_current_landlord_id,
)
from services import invoice_queue_service as queue
from services.audit_service import record_audit
from utils import ApiError, success

invoice_queue_bp = Blueprint("invoice_queue", __name__, url_prefix="/api/invoice-queue")


def _scoped_unit_ids():
    """Units the caller may see, or None when unrestricted."""
    allowed = accessible_property_ids()
    if allowed is None:
        return None
    return [
        uid for (uid,) in db.session.query(Unit.id)
        .filter(Unit.property_id.in_(allowed), Unit.is_deleted.is_(False))
    ]


def _unit_or_404(landlord_id: int, unit_id: int) -> Unit:
    from models import Property

    unit = (
        db.session.query(Unit)
        .join(Property, Property.id == Unit.property_id)
        .filter(Unit.id == unit_id, Unit.is_deleted.is_(False),
                Property.landlord_id == landlord_id)
        .first()
    )
    if unit is None:
        raise ApiError("Unit not found.", status=404)

    allowed = accessible_property_ids()
    if allowed is not None and unit.property_id not in allowed:
        raise ApiError("You do not have access to that property.", status=403)
    return unit


@invoice_queue_bp.route("/", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def list_queue():
    """Everything waiting to be billed (approved), or ?status=pending for the
    charges waiting for review. Also says whether the 1st-of-month run is on."""
    from models import Landlord

    landlord_id = get_current_landlord_id()
    unit_ids = _scoped_unit_ids()
    status = QueuedCharge.STATUS_PENDING if request.args.get("status") == "pending" else None
    aut = db.session.get(Landlord, landlord_id).automation_settings
    return success({
        **queue.summary_for_landlord(landlord_id, unit_ids=unit_ids),
        "status": status or QueuedCharge.STATUS_QUEUED,
        "charges": [c.to_dict() for c in
                    queue.pending_for_landlord(landlord_id, unit_ids=unit_ids, status=status)],
        "automation": {
            "auto_invoice_rent": bool(aut and aut.auto_generate_recurring_invoices),
            "auto_invoice_queued": bool(aut and aut.auto_invoice_queued_charges),
        },
    })


@invoice_queue_bp.route("/review", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def review_queue():
    """
    Approve or reject charges waiting for review.
    Body: { action: "approve" | "reject", charge_ids?: [int], all?: bool, note?: str }
    `all` takes every pending charge the caller can see.
    """
    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("approve", "reject"):
        raise ApiError("action must be 'approve' or 'reject'.", status=400)

    unit_ids = _scoped_unit_ids()
    pending = queue.pending_for_landlord(landlord_id, unit_ids=unit_ids,
                                         status=QueuedCharge.STATUS_PENDING)
    if not data.get("all"):
        wanted = {int(x) for x in (data.get("charge_ids") or [])}
        if not wanted:
            raise ApiError("Choose at least one charge, or pass all: true.", status=400)
        pending = [c for c in pending if c.id in wanted]

    actor = int(get_jwt_identity())
    changed = queue.review(pending, approve=(action == "approve"), actor_user_id=actor,
                           note=data.get("note"))
    total = sum(float(c.amount or 0) for c in pending)
    record_audit(
        actor_user_id=actor,
        landlord_id=landlord_id,
        action=f"{action}_queued_charges",
        entity_type="queued_charge",
        entity_id=None,
        description=(f"{changed} queued charge(s) totalling {total:,.2f} "
                     f"{'approved for the next invoice' if action == 'approve' else 'rejected'}."),
    )
    db.session.commit()
    verb = "approved" if action == "approve" else "rejected"
    return success({"changed": changed}, message=f"{changed} charge(s) {verb}.")


@invoice_queue_bp.route("/run-monthly", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def run_monthly_now():
    """
    Raise this month's invoices now, the same way the 1st-of-month run does.
    Body: { include_rent: bool, include_queued: bool, issue_date?: YYYY-MM-DD,
            property_ids?: [int] }
    One invoice per tenant per month: rent (and other fixed monthly charges),
    approved queued charges and any unpaid balance carried forward. A tenant who
    already has this month's invoice gets the approved queued charges added to it.
    """
    from tasks.invoice_tasks import run_monthly_billing_task

    landlord_id = get_current_landlord_id()
    data = request.get_json(silent=True) or {}
    include_rent = bool(data.get("include_rent", True))
    include_queued = bool(data.get("include_queued", True))
    if not (include_rent or include_queued):
        raise ApiError("Choose rent, queued charges, or both.", status=400)

    property_ids = data.get("property_ids") or None
    allowed = accessible_property_ids()
    if allowed is not None:
        property_ids = [p for p in (property_ids or allowed) if p in allowed]
        if not property_ids:
            raise ApiError("You do not have access to those properties.", status=403)

    task = run_monthly_billing_task.delay(
        landlord_id, data.get("issue_date"), property_ids, None, int(get_jwt_identity()),
        include_rent, include_queued,
    )
    tally = task.result if isinstance(task.result, dict) else None
    message = "Monthly invoicing started."
    if tally:
        message = (f"{tally.get('created', 0)} invoice(s) created, "
                   f"{tally.get('updated', 0)} updated with queued charges.")
    return success({"task_id": task.id, "result": tally}, message=message, status=202)


@invoice_queue_bp.route("/units/<int:unit_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def unit_queue(unit_id):
    """
    What is waiting for one unit.

    The invoice form calls this before it saves, so it can say "this unit has
    two charges waiting — include them?" rather than letting somebody raise a
    bill that silently omits the month's water.
    """
    landlord_id = get_current_landlord_id()
    _unit_or_404(landlord_id, unit_id)
    charges = queue.pending_for_unit(unit_id)
    return success({
        "charges": [c.to_dict() for c in charges],
        "count": len(charges),
        "total": float(queue.pending_total_for_unit(unit_id)),
    })


@invoice_queue_bp.route("/units/<int:unit_id>/apply", methods=["POST"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def apply_queue(unit_id):
    """
    Bill what is waiting for a unit, now.

    Body: { invoice_id?: int, charge_ids?: [int] }
      invoice_id  — append to that invoice; omitted, the unit's open invoice is
                    used, and it is an error if there is none. We deliberately
                    do NOT invent an invoice here: "apply to an invoice" and
                    "raise an invoice" are different intentions, and the monthly
                    run already handles the second.
      charge_ids  — a subset; omitted, everything queued for the unit.
    """
    landlord_id = get_current_landlord_id()
    unit = _unit_or_404(landlord_id, unit_id)
    data = request.get_json(silent=True) or {}

    charges = queue.pending_for_unit(unit_id)
    if not charges:
        raise ApiError("Nothing is queued for this unit.", status=422)

    if data.get("charge_ids"):
        wanted = {int(x) for x in data["charge_ids"]}
        charges = [c for c in charges if c.id in wanted]
        if not charges:
            raise ApiError("None of those charges are queued for this unit.", status=422)

    if data.get("invoice_id"):
        invoice = (
            db.session.query(Invoice)
            .filter(Invoice.id == int(data["invoice_id"]),
                    Invoice.landlord_id == landlord_id,
                    Invoice.is_deleted.is_(False))
            .first()
        )
        if invoice is None:
            raise ApiError("Invoice not found.", status=404)
    else:
        invoice = (
            db.session.query(Invoice)
            .filter(Invoice.unit_id == unit_id,
                    Invoice.landlord_id == landlord_id,
                    Invoice.is_deleted.is_(False),
                    Invoice.status.in_([InvoiceStatus.open.value,
                                        InvoiceStatus.partial.value]))
            .order_by(Invoice.issue_date.desc())
            .first()
        )
        if invoice is None:
            raise ApiError(
                "This unit has no open invoice to add these to. Raise an invoice "
                "first, or leave them queued for the next monthly run.",
                status=409, code="no_open_invoice")

    tenant = invoice.tenant
    added = queue.consume_into_invoice(invoice, charges, tenant=tenant)

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="apply_queued_charges",
        entity_type="invoice",
        entity_id=invoice.id,
        description=(f"{len(charges)} queued charge(s) totalling {added} applied to "
                     f"invoice {invoice.invoice_number} for unit {unit.name}."),
    )
    db.session.commit()

    return success({
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "applied": len(charges),
        "amount": float(added),
    }, message=f"{len(charges)} charge(s) added to {invoice.invoice_number}.")


@invoice_queue_bp.route("/<int:charge_id>", methods=["DELETE"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "edit")
def cancel_charge(charge_id):
    """
    Drop a queued charge without billing it — a misread meter, a duplicate.

    Cancelled, not deleted: "why was this never billed?" gets asked months
    later, and a deleted row cannot answer it.
    """
    landlord_id = get_current_landlord_id()
    charge = (
        db.session.query(QueuedCharge)
        .filter(QueuedCharge.id == charge_id,
                QueuedCharge.landlord_id == landlord_id)
        .first()
    )
    if charge is None:
        raise ApiError("Queued charge not found.", status=404)
    if charge.status != QueuedCharge.STATUS_QUEUED:
        raise ApiError("That charge has already been dealt with.", status=409)

    _unit_or_404(landlord_id, charge.unit_id)
    queue.cancel(charge, actor_user_id=int(get_jwt_identity()))

    record_audit(
        actor_user_id=int(get_jwt_identity()),
        landlord_id=landlord_id,
        action="cancel_queued_charge",
        entity_type="queued_charge",
        entity_id=charge.id,
        description=f"Queued charge '{charge.item}' ({charge.amount}) cancelled without billing.",
    )
    db.session.commit()
    return success(message="Charge cancelled.")


# ---------------------------------------------------------------------------
# Generate invoices property by property
# ---------------------------------------------------------------------------
#
# The whole-portfolio run is one button and 1,000 invoices. A property manager
# with a hundred owners wants to do it one block at a time — generate, look at
# what came out, confirm, move on — so that a wrong rent on one building is
# caught before it goes to the next. These two endpoints are the list and the
# per-property preview; generating is the existing run-monthly with
# property_ids=[one id].

def _month_arg():
    from services.line_period import parse_month
    from datetime import date as _date
    month = parse_month(request.args.get("month")) or parse_month(_date.today())
    return month


@invoice_queue_bp.route("/by-property", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def monthly_by_property():
    """Every property with how many of its tenants are invoiced for ?month=YYYY-MM."""
    from datetime import date as _date
    from models import Property, Tenant, InvoiceType

    landlord_id = get_current_landlord_id()
    month = _month_arg()
    nxt = _date(month.year + (month.month // 12), month.month % 12 + 1, 1)
    allowed = accessible_property_ids()

    props = Property.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if allowed is not None:
        props = props.filter(Property.id.in_(allowed))
    props = props.order_by(Property.name).all()
    ids = [p.id for p in props]

    tenants = dict(
        db.session.query(Unit.property_id, db.func.count(Tenant.id))
        .join(Tenant, Tenant.unit_id == Unit.id)
        .filter(Unit.property_id.in_(ids), Unit.is_deleted.is_(False),
                Tenant.is_deleted.is_(False), Tenant.landlord_id == landlord_id)
        .group_by(Unit.property_id).all()
    ) if ids else {}
    invoiced = dict(
        db.session.query(Invoice.property_id, db.func.count(db.distinct(Invoice.tenant_id)))
        .filter(Invoice.landlord_id == landlord_id, Invoice.property_id.in_(ids),
                Invoice.is_deleted.is_(False),
                Invoice.invoice_type == InvoiceType.monthly.value,
                Invoice.issue_date >= month, Invoice.issue_date < nxt)
        .group_by(Invoice.property_id).all()
    ) if ids else {}
    billed = dict(
        db.session.query(Invoice.property_id, db.func.coalesce(db.func.sum(Invoice.total_amount), 0))
        .filter(Invoice.landlord_id == landlord_id, Invoice.property_id.in_(ids),
                Invoice.is_deleted.is_(False),
                Invoice.invoice_type == InvoiceType.monthly.value,
                Invoice.issue_date >= month, Invoice.issue_date < nxt)
        .group_by(Invoice.property_id).all()
    ) if ids else {}

    rows = []
    for p in props:
        t = int(tenants.get(p.id, 0))
        i = int(invoiced.get(p.id, 0))
        rows.append({
            "property_id": p.id, "property_name": p.name, "city": p.city,
            "tenants": t, "invoiced": i, "remaining": max(t - i, 0),
            "invoiced_total": float(billed.get(p.id, 0) or 0),
            "status": "done" if t and i >= t else ("partial" if i else ("empty" if not t else "pending")),
        })
    done = sum(1 for r in rows if r["status"] == "done")
    return success({"month": month.isoformat(), "properties": rows,
                    "summary": {"properties": len(rows), "done": done,
                                "pending": sum(1 for r in rows if r["status"] in ("pending", "partial"))}})


@invoice_queue_bp.route("/by-property/<int:property_id>", methods=["GET"])
@jwt_required()
@require_landlord_or_team()
@require_permission("invoices", "view")
def monthly_property_preview(property_id):
    """Per tenant: what generating ?month= for this property will bill."""
    from models import Landlord, Property, Tenant
    from tasks.invoice_tasks import preview_monthly_for_tenant

    landlord_id = get_current_landlord_id()
    allowed = accessible_property_ids()
    if allowed is not None and property_id not in allowed:
        raise ApiError("Property not found.", status=404)
    prop = Property.query.filter_by(id=property_id, landlord_id=landlord_id, is_deleted=False).first()
    if prop is None:
        raise ApiError("Property not found.", status=404)
    month = _month_arg()
    include_rent = (request.args.get("include_rent", "true").lower() != "false")
    include_queued = (request.args.get("include_queued", "true").lower() != "false")
    landlord = db.session.get(Landlord, landlord_id)

    tenants = (Tenant.query.join(Unit, Unit.id == Tenant.unit_id)
               .filter(Unit.property_id == property_id, Unit.is_deleted.is_(False),
                       Tenant.is_deleted.is_(False), Tenant.landlord_id == landlord_id)
               .order_by(Unit.name).all())
    rows = [preview_monthly_for_tenant(landlord, t, month, include_rent, include_queued)
            for t in tenants]
    to_bill = [r for r in rows if r["status"] == "new"]
    return success({
        "month": month.isoformat(), "property_id": prop.id, "property_name": prop.name,
        "tenants": rows,
        "summary": {
            "tenants": len(rows), "to_invoice": len(to_bill),
            "already_invoiced": sum(1 for r in rows if r["status"] == "already_invoiced"),
            "rent": round(sum(r["rent"] for r in to_bill), 2),
            "queued": round(sum(r["queued"] for r in rows), 2),
            "balance_bf": round(sum(r["balance_bf"] for r in to_bill), 2),
            "total": round(sum(r["total"] for r in rows), 2),
        },
    })
