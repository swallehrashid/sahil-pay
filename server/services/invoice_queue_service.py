"""
services/invoice_queue_service.py — charges waiting for an invoice to exist.

The timing problem this solves is entirely ordinary and entirely unsolved by
"create an invoice now": a caretaker reads meters on the 28th, and the bill goes
out on the 1st. On the 28th there is nothing to attach the charge to. Raising a
one-line utility invoice sends the tenant a second bill they did not expect;
holding the paper until the 1st is how readings get lost.

So a charge can be queued against the UNIT, and the next invoice for that unit
takes it. Three rules make that safe:

  ONCE.      A queued charge moves queued -> consumed with the id of the invoice
             that took it. Re-running the monthly billing cannot bill the same
             reading twice, which matters because the monthly run is explicitly
             designed to be re-runnable.

  THE UNIT.  Not the tenant. Water was used by the meter. A tenant who leaves on
             the 30th should not be billed for a reading against a unit they
             have vacated — but the NEXT tenant should not silently inherit it
             either, so the occupant at queue time is recorded and surfaced when
             it is consumed.

  VISIBLY.   Consuming a queued charge writes a normal invoice line with its own
             description. On the tenant's statement it reads exactly like any
             other charge, because as far as they are concerned it is one.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

ZERO = Decimal("0.00")

# What a caller may ask for when billing something that has no invoice yet.
TARGET_NEW = "new"            # raise an invoice of its own, now
TARGET_EXISTING = "existing"  # append to the open invoice, if there is one
TARGET_QUEUE = "queue"        # hold it for the next invoice this unit gets
VALID_TARGETS = (TARGET_NEW, TARGET_EXISTING, TARGET_QUEUE)


def queue_charge(landlord_id: int, unit, *, item: str, amount,
                 category_id: int | None = None, subcategory: str | None = "current",
                 description: str | None = None,
                 utility_reading_id: int | None = None,
                 actor_user_id: int | None = None):
    """
    Hold a charge against *unit* until its next invoice.

    Flushes but does not commit — the caller owns the transaction, matching
    every other service here.
    """
    from extensions import db
    from models import QueuedCharge

    amount = Decimal(str(amount or 0))
    if amount <= ZERO:
        return None

    occupant = None
    tenants = [t for t in (unit.tenants or []) if not t.is_deleted]
    if tenants:
        occupant = tenants[0]

    row = QueuedCharge(
        landlord_id=landlord_id,
        unit_id=unit.id,
        occupant_at_queue_id=occupant.id if occupant else None,
        category_id=category_id,
        subcategory=subcategory or "current",
        item=item,
        description=description,
        amount=amount,
        utility_reading_id=utility_reading_id,
        status=QueuedCharge.STATUS_QUEUED,
        created_by_user_id=actor_user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def pending_for_unit(unit_id: int) -> list:
    from extensions import db
    from models import QueuedCharge

    return (
        db.session.query(QueuedCharge)
        .filter(QueuedCharge.unit_id == unit_id,
                QueuedCharge.status == QueuedCharge.STATUS_QUEUED)
        .order_by(QueuedCharge.created_at.asc())
        .all()
    )


def pending_total_for_unit(unit_id: int) -> Decimal:
    return sum((Decimal(str(c.amount)) for c in pending_for_unit(unit_id)), ZERO)


def pending_for_landlord(landlord_id: int, *, unit_ids=None) -> list:
    """Everything waiting across the account — the queue screen's data."""
    from extensions import db
    from models import QueuedCharge

    query = (
        db.session.query(QueuedCharge)
        .filter(QueuedCharge.landlord_id == landlord_id,
                QueuedCharge.status == QueuedCharge.STATUS_QUEUED)
    )
    if unit_ids is not None:
        query = query.filter(QueuedCharge.unit_id.in_(unit_ids))
    return query.order_by(QueuedCharge.unit_id, QueuedCharge.created_at).all()


def consume_into_invoice(invoice, charges, *, tenant=None) -> Decimal:
    """
    Move *charges* onto *invoice* as real line items. Returns the total added.

    The invoice header and the tenant's balance are both updated here so a
    caller cannot half-apply a queued charge — the line, the total and the
    ledger move together or not at all.

    Charges already consumed are skipped rather than raising: two runs racing
    for the same queue should produce one bill, not an error.
    """
    from extensions import db
    from models import InvoiceLineItem, LineItemStatus, QueuedCharge

    added = ZERO
    now = datetime.utcnow()

    for charge in charges:
        if charge.status != QueuedCharge.STATUS_QUEUED:
            continue

        amount = Decimal(str(charge.amount or 0))
        if amount <= ZERO:
            continue

        db.session.add(InvoiceLineItem(
            invoice_id=invoice.id,
            item=charge.item,
            description=charge.description,
            quantity=Decimal("1"),
            unit_price=amount,
            amount=amount,
            category_id=charge.category_id,
            subcategory=charge.subcategory or "current",
            utility_reading_id=charge.utility_reading_id,
            amount_paid=ZERO,
            status=LineItemStatus.open.value,
        ))

        charge.status = QueuedCharge.STATUS_CONSUMED
        charge.consumed_by_invoice_id = invoice.id
        charge.consumed_at = now
        added += amount

    if added > ZERO:
        invoice.total_amount = Decimal(str(invoice.total_amount or 0)) + added
        invoice.balance = invoice.total_amount - Decimal(str(invoice.amount_paid or 0))
        # New debt makes the balance MORE negative — see
        # penalty_service.arrears_of() for the sign convention.
        if tenant is not None:
            tenant.balance = Decimal(str(tenant.balance or 0)) - added

    db.session.flush()
    return added


def consume_for_unit(invoice, unit_id: int, *, tenant=None) -> Decimal:
    """
    Take everything queued for a unit onto this invoice.

    Called by the monthly billing run, which is the whole point of the queue:
    the caretaker's 28th-of-the-month reading lands on the 1st-of-the-month bill
    without anybody re-keying it.
    """
    return consume_into_invoice(invoice, pending_for_unit(unit_id), tenant=tenant)


def cancel(charge, *, actor_user_id: int | None = None) -> None:
    """
    Drop a queued charge without billing it — a misread meter, a duplicate.

    Cancelled rather than deleted: "why was this never billed?" is a question
    somebody asks three months later, and a deleted row cannot answer it.
    """
    from extensions import db
    from models import QueuedCharge

    charge.status = QueuedCharge.STATUS_CANCELLED
    charge.consumed_at = datetime.utcnow()
    db.session.flush()


def summary_for_landlord(landlord_id: int, *, unit_ids=None) -> dict:
    """Counts and totals for the queue screen and the dashboard nudge."""
    charges = pending_for_landlord(landlord_id, unit_ids=unit_ids)
    by_unit: dict[int, dict] = {}
    for charge in charges:
        bucket = by_unit.setdefault(charge.unit_id, {
            "unit_id": charge.unit_id,
            "unit_name": charge.unit.name if charge.unit else None,
            "count": 0,
            "total": ZERO,
        })
        bucket["count"] += 1
        bucket["total"] += Decimal(str(charge.amount or 0))

    return {
        "count": len(charges),
        "total": float(sum((Decimal(str(c.amount)) for c in charges), ZERO)),
        "units": [
            {**b, "total": float(b["total"])}
            for b in sorted(by_unit.values(), key=lambda x: x["unit_name"] or "")
        ],
    }
