"""
routes/invoice_queue_routes.py — charges waiting for an invoice.
Blueprint: invoice_queue_bp  |  Prefix: /api/invoice-queue

    GET    /                     everything waiting, grouped by unit
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
    """Everything waiting to be billed, grouped by unit."""
    landlord_id = get_current_landlord_id()
    unit_ids = _scoped_unit_ids()
    return success({
        **queue.summary_for_landlord(landlord_id, unit_ids=unit_ids),
        "charges": [c.to_dict() for c in
                    queue.pending_for_landlord(landlord_id, unit_ids=unit_ids)],
    })


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
