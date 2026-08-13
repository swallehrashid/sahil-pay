"""
services/payment_resolver.py — the layered payment resolver (spec §4.5).

THE PROBLEM THIS EXISTS TO FIX
------------------------------
A tenant can rent four units across three landlords, all collected by one
property manager on one paybill, and pay for all of them with a single M-Pesa
transaction quoting their phone number. Before this module the pipeline matched
that phone to `.first()` matching tenant row and allocated the whole lump sum
there — silently crediting one lease and leaving three in arrears, with nothing
in the audit trail to say it had guessed.

THE MENTAL MODEL
----------------
Identification and allocation are two different questions, and conflating them
is what caused the bug:

    IDENTIFICATION   which tenant / lease is this payment for?
    ALLOCATION       how is the amount split across that lease's charges?

A phone number is an IDENTITY key, never an allocation key. It answers "which
tenant", never "which of their units".

    LAYER 0  source      which paybill/till → property/owner
    LAYER 1  reference   unit pay-code (exact lease) OR phone (tenant → one
                         lease auto, several = suspense)
    LAYER 2  intra-lease the existing allocation_service waterfall
    LAYER 3  audit       every outcome recorded

THE HARD RULE
-------------
Anything the resolver cannot attribute with CERTAINTY goes to suspense. A
multi-unit tenant's lump sum is never auto-split — the manager is offered an
arrears-first suggestion they can accept in one tap or adjust, and the money
stays in suspense until they do. Nothing is ever silently split.
"""

from __future__ import annotations

import re
from decimal import Decimal

from extensions import db
from models import (
    AllocationAudit, AllocationAuditAction, AllocationMethod, InboundPaymentSource,
    Payment, PaymentStatus, SuspenseReason, Tenant, Unit,
)
from services import pay_code_service

ZERO = Decimal("0.00")


def _D(value) -> Decimal:
    return Decimal(str(value or 0))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def record_allocation_audit(payment, action: str, *, actor_user_id=None,
                            before=None, after=None, reason=None) -> None:
    """Append-only trail. Every path through this module writes one."""
    db.session.add(AllocationAudit(
        landlord_id   = payment.landlord_id,
        payment_id    = payment.id,
        action        = action,
        actor_user_id = actor_user_id,
        before_json   = before,
        after_json    = after,
        reason        = reason,
    ))


def allocation_snapshot(payment) -> list[dict]:
    """
    The payment's current allocations, for the audit before/after fields.

    Queried rather than read off `payment.payment_allocations`: the relationship
    is cached from before apply_allocations() ran, so using it would record an
    empty "after" on every freshly-allocated payment.
    """
    from models import PaymentAllocation

    rows = (
        db.session.query(PaymentAllocation)
        .filter(PaymentAllocation.payment_id == payment.id)
        .all()
    )
    return [
        {
            "line_item_id": a.line_item_id,
            "invoice_id":   a.invoice_id,
            "amount":       str(a.amount_allocated),
        }
        for a in rows
    ]


def _stamp_provenance(payment, method: str, actor_user_id) -> None:
    """
    Tag every allocation with who made it and how.

    Assigned unconditionally: PaymentAllocation.method carries a Python-side
    default of "auto" that SQLAlchemy applies during the flush inside
    apply_allocations(), so a `if method is None` guard would never fire and a
    manual split would be mislabelled as automatic.
    """
    from models import PaymentAllocation

    for allocation in (db.session.query(PaymentAllocation)
                       .filter(PaymentAllocation.payment_id == payment.id).all()):
        allocation.method = method
        allocation.allocated_by = actor_user_id
    db.session.flush()


# ---------------------------------------------------------------------------
# Layer 0 — source
# ---------------------------------------------------------------------------

def match_source(landlord_id: int, shortcode=None, source_name=None):
    """
    Which configured paybill/till this payment arrived through.

    Returns None for the common single-paybill case, which the rest of the
    resolver treats as "no narrowing" rather than as a failure.
    """
    if not shortcode and not source_name:
        return None

    query = db.session.query(InboundPaymentSource).filter(
        InboundPaymentSource.landlord_id == landlord_id,
        InboundPaymentSource.is_active.is_(True),
    )
    if shortcode:
        hit = query.filter(InboundPaymentSource.shortcode == str(shortcode).strip()).first()
        if hit is not None:
            return hit
    if source_name:
        name = str(source_name).strip().lower()
        for source in query.all():
            pattern = (source.match_pattern or "").strip().lower()
            if pattern and pattern in name:
                return source
    return None


# ---------------------------------------------------------------------------
# Layer 1 — reference
# ---------------------------------------------------------------------------

_PHONE_RE = re.compile(r"^(?:\+?254|0)[17]\d{8}$")


def looks_like_phone(reference) -> bool:
    return bool(_PHONE_RE.match(re.sub(r"[\s\-]", "", str(reference or ""))))


def phone_variants(raw) -> set[str]:
    """
    Every shape a Kenyan number is stored in across this database.

    Tenant.phone is genuinely inconsistent — some rows keep a leading '+',
    some don't, some are 07…, some 2547… — so matching one form only would
    miss real tenants and push good payments into suspense.
    """
    digits = re.sub(r"[\s\-]", "", str(raw or ""))
    if not digits:
        return set()
    variants = {digits}
    if digits.startswith("+"):
        digits = digits[1:]
        variants.add(digits)
    if digits.startswith("0") and len(digits) == 10:
        variants |= {"254" + digits[1:], "+254" + digits[1:]}
    if digits.startswith("254") and len(digits) == 12:
        variants |= {"0" + digits[3:], "+" + digits}
    return variants


def active_leases_for_tenant_phone(landlord_id: int, phone, source=None) -> list:
    """
    Every live tenancy behind one phone number.

    One person renting four units is four Tenant rows sharing a phone — that is
    the schema's design, and it is exactly why a phone cannot pick a lease.
    A matched source narrows to its property first, which resolves many
    multi-lease cases on its own for multi-paybill landlords.
    """
    variants = phone_variants(phone)
    if not variants:
        return []

    query = (
        db.session.query(Tenant)
        .filter(Tenant.landlord_id == landlord_id,
                Tenant.is_deleted.is_(False),
                Tenant.phone.in_(tuple(variants)))
    )
    tenants = query.all()

    if source is not None and source.mapped_property_id:
        narrowed = [
            t for t in tenants
            if t.unit is not None and t.unit.property_id == source.mapped_property_id
        ]
        if narrowed:
            return narrowed
    return tenants


# ---------------------------------------------------------------------------
# Suggested split (assist only — never auto-committed)
# ---------------------------------------------------------------------------

def suggest_split(amount, tenants: list) -> list[dict]:
    """
    An arrears-first distribution across a tenant's leases.

    Deliberately a SUGGESTION. Swalleh's decision (spec §4.5) is that
    multi-unit lump sums are allocated by the manager, only assisted by this —
    the machine has no way to know the tenant meant three months on the shop
    and nothing on the flat.

    Oldest debt first: each lease takes what it is owed, in descending arrears,
    until the money runs out. Anything left over is offered against the largest
    remaining lease as credit.
    """
    remaining = _D(amount)
    rows = []

    # Tenant.balance is owed-negative in this ledger, so a bigger debt is a
    # more negative number — flip it to make "most in arrears" sort naturally.
    ranked = sorted(tenants, key=lambda t: _D(t.balance), reverse=False)

    for tenant in ranked:
        if remaining <= ZERO:
            break
        owed = -_D(tenant.balance)
        if owed <= ZERO:
            continue
        take = min(owed, remaining)
        remaining -= take
        rows.append({
            "tenant_id": tenant.id,
            "unit_id":   tenant.unit_id,
            "unit_name": tenant.unit.name if tenant.unit else None,
            "amount":    str(take.quantize(Decimal("0.01"))),
            "reason":    "arrears",
        })

    if remaining > ZERO and ranked:
        target = ranked[0]
        rows.append({
            "tenant_id": target.id,
            "unit_id":   target.unit_id,
            "unit_name": target.unit.name if target.unit else None,
            "amount":    str(remaining.quantize(Decimal("0.01"))),
            "reason":    "advance",
        })
    return rows


# ---------------------------------------------------------------------------
# Suspense
# ---------------------------------------------------------------------------

def to_suspense(payment, reason: str, *, suggestion=None, notify_landlord=True):
    """
    Park a payment for human review.

    The money is REAL — it is in the paybill — but it is not attributed, so the
    payment must not be `confirmed`: a confirmed payment feeds statements,
    commission and payouts, and an unattributed one would corrupt all three.
    """
    payment.status = PaymentStatus.suspense.value
    payment.suspense_reason = reason
    payment.suggested_split_json = suggestion
    db.session.flush()

    record_allocation_audit(
        payment, AllocationAuditAction.suspense.value,
        after={"reason": reason, "suggestion": suggestion},
        reason=f"Held for review: {reason}.",
    )

    if notify_landlord:
        _notify_suspense(payment, reason)
    return payment


_SUSPENSE_COPY = {
    SuspenseReason.multi_lease.value:
        "pays for more than one unit — choose how to split it",
    SuspenseReason.unknown_reference.value:
        "could not be matched to a tenant",
    SuspenseReason.code_no_active_lease.value:
        "quoted a unit code with no active tenant",
    SuspenseReason.ambiguous_phone.value:
        "could not be matched to a single tenant",
    SuspenseReason.no_source_match.value:
        "arrived through an unrecognised paybill",
    SuspenseReason.reversal_pending.value:
        "was reversed at M-Pesa and needs review",
}


def _notify_suspense(payment, reason: str) -> None:
    from flask import current_app

    from models import Landlord
    from services.notification_service import notify

    landlord = db.session.get(Landlord, payment.landlord_id)
    if landlord is None or not landlord.user_id:
        return
    try:
        notify(
            recipient_user_id=landlord.user_id,
            category="payment_received",
            title="Payment needs review",
            body=(f"KES {_D(payment.amount):,.2f} "
                  f"{_SUSPENSE_COPY.get(reason, 'needs review')}."),
            landlord_id=landlord.id,
            link=f"/landlord/payments?tab=review&payment={payment.id}",
            entity_type="payment", entity_id=payment.id,
        )
    except Exception:
        # A notification failure must never strand the payment itself.
        current_app.logger.exception("[resolver] suspense notification failed for %s",
                                     payment.id)


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def resolve(payment, landlord, *, shortcode=None, source_name=None,
            auto_allocate: bool = True):
    """
    Route one parsed payment to a lease, or to suspense.

    `payment` must already exist with amount, landlord_id and reference_text
    set. Returns the payment. FLUSHES but never commits — the caller owns the
    transaction, matching the rest of the services layer.
    """
    # ---- Layer 0 — which paybill --------------------------------------
    source = match_source(landlord.id, shortcode, source_name)
    if source is not None:
        payment.source_id = source.id

    reference = (payment.reference_text or "").strip()
    method = getattr(landlord, "allocation_method", None) or AllocationMethod.phone.value

    # ---- Layer 1 — what the reference names ---------------------------
    # A pay-code is tried FIRST in both modes: in phone mode it is documented
    # as a fallback reference, so a tenant who quotes their unit code gets the
    # deterministic path even on an account that hasn't switched over.
    unit = pay_code_service.resolve_unit(landlord.id, reference) if reference else None

    if unit is not None:
        tenant = _active_tenant_for_unit(unit)
        if tenant is None:
            return to_suspense(payment, SuspenseReason.code_no_active_lease.value)
        return _allocate_to_tenant(payment, tenant, landlord,
                                   auto_allocate=auto_allocate, method="auto")

    if method == AllocationMethod.unit_code.value and reference and not looks_like_phone(reference):
        # Unit-code mode with a reference that is neither a code nor a phone:
        # guessing here is exactly what this engine exists to stop.
        return to_suspense(payment, SuspenseReason.unknown_reference.value)

    # ---- Phone path ----------------------------------------------------
    # The typed reference wins over the payer's number: M-Pesa masks the payer
    # phone on forwarded confirmations, but the account reference always
    # survives intact.
    candidate_phone = reference if looks_like_phone(reference) else payment.payer_phone
    if not candidate_phone:
        return to_suspense(payment, SuspenseReason.unknown_reference.value)

    tenants = active_leases_for_tenant_phone(landlord.id, candidate_phone, source)

    if not tenants:
        return to_suspense(payment, SuspenseReason.unknown_reference.value)

    if len(tenants) == 1:
        return _allocate_to_tenant(payment, tenants[0], landlord,
                                   auto_allocate=auto_allocate, method="auto")

    # THE CORE CASE: one person, several units, one lump sum. Hold it.
    return to_suspense(
        payment, SuspenseReason.multi_lease.value,
        suggestion=suggest_split(payment.amount, tenants),
    )


def _active_tenant_for_unit(unit):
    """The unit's current occupant, if it has one."""
    return (
        db.session.query(Tenant)
        .filter(Tenant.unit_id == unit.id,
                Tenant.is_deleted.is_(False),
                Tenant.move_out_date.is_(None))
        .order_by(Tenant.id.desc())
        .first()
    )


def _allocate_to_tenant(payment, tenant, landlord, *, auto_allocate=True,
                        method="auto", actor_user_id=None):
    """
    Attach the payment to a lease and run the intra-lease waterfall (layer 2).

    The waterfall itself is the existing allocation_service — category/
    subcategory priority, oldest first, surplus to credit — which already does
    exactly what the spec asks for and is covered by its own tests.
    """
    from services.allocation_service import apply_allocations, auto_allocate as build_rows

    payment.tenant_id = tenant.id
    payment.unit_id = tenant.unit_id
    payment.property_id = tenant.unit.property_id if tenant.unit else None
    payment.suspense_reason = None
    payment.suggested_split_json = None

    if not auto_allocate:
        # The account wants to eyeball every payment before it lands. Pending is
        # not suspense: the tenant IS known, so nothing needs resolving — it
        # just needs a human's confirmation.
        payment.status = PaymentStatus.pending.value
        db.session.flush()
        return payment

    payment.status = PaymentStatus.confirmed.value
    db.session.flush()

    before = allocation_snapshot(payment)
    rows = build_rows(tenant, _D(payment.amount), landlord, ref_date=payment.payment_date)
    apply_allocations(payment, tenant, rows, landlord.id)

    _stamp_provenance(payment, method, actor_user_id)

    record_allocation_audit(
        payment, AllocationAuditAction.allocate.value,
        actor_user_id=actor_user_id, before=before,
        after=allocation_snapshot(payment),
        reason=f"Resolved to {tenant.first_name} {tenant.last_name}".strip(),
    )
    return payment


# ---------------------------------------------------------------------------
# Manual allocation (out of the review queue)
# ---------------------------------------------------------------------------

def allocate_manually(payment, landlord, splits: list[dict], *, actor_user_id=None):
    """
    Commit a manager's chosen split for a suspense payment (spec §4.7).

    `splits` is [{tenant_id, amount}, …]. The amounts must not exceed the
    payment — over-allocating would invent money — and every row is audited
    with the actor, because this is a human overriding the machine.
    """
    from utils import ApiError

    if not splits:
        raise ApiError("Choose at least one unit to allocate to.", status=422)

    total = sum(_D(s.get("amount")) for s in splits)
    if total <= ZERO:
        raise ApiError("Allocate an amount greater than zero.", status=422)
    if total > _D(payment.amount):
        raise ApiError(
            f"That splits KES {total:,.2f} but the payment is only "
            f"KES {_D(payment.amount):,.2f}.",
            status=422, errors={"splits": "exceeds_payment"},
        )

    before = allocation_snapshot(payment)
    tenants = {
        t.id: t for t in db.session.query(Tenant).filter(
            Tenant.id.in_([s["tenant_id"] for s in splits]),
            Tenant.landlord_id == landlord.id,
        ).all()
    }

    from services.allocation_service import apply_allocations, auto_allocate as build_rows

    # A split across leases becomes one CHILD payment per lease: a Payment row
    # carries a single tenant_id/unit_id, and the statements, receipts and
    # commission base all read those. Forcing one row to mean four leases would
    # break every downstream report.
    first_tenant = None
    for index, split in enumerate(splits):
        tenant = tenants.get(split["tenant_id"])
        if tenant is None:
            raise ApiError("One of those tenants isn't on this account.", status=422)
        amount = _D(split["amount"])
        if amount <= ZERO:
            continue

        if index == 0:
            first_tenant = tenant
            target = payment
            target.amount = amount
        else:
            target = Payment(
                payment_ref     = f"{payment.payment_ref}-{index + 1}",
                landlord_id     = payment.landlord_id,
                amount          = amount,
                payment_date    = payment.payment_date,
                source          = payment.source,
                payment_method  = payment.payment_method,
                mpesa_reference = payment.mpesa_reference,
                reference_text  = payment.reference_text,
                payer_phone     = payment.payer_phone,
                source_id       = payment.source_id,
                notes           = f"Split from {payment.payment_ref} by manual allocation.",
            )
            db.session.add(target)
            db.session.flush()

        target.tenant_id = tenant.id
        target.unit_id = tenant.unit_id
        target.property_id = tenant.unit.property_id if tenant.unit else None
        target.status = PaymentStatus.confirmed.value
        target.suspense_reason = None
        target.suggested_split_json = None
        db.session.flush()

        rows = build_rows(tenant, amount, landlord, ref_date=target.payment_date)
        apply_allocations(target, tenant, rows, landlord.id)
        _stamp_provenance(target, "manual", actor_user_id)

        if target is not payment:
            record_allocation_audit(
                target, AllocationAuditAction.allocate.value,
                actor_user_id=actor_user_id, after=allocation_snapshot(target),
                reason=f"Manual split from {payment.payment_ref}.",
            )

    record_allocation_audit(
        payment, AllocationAuditAction.allocate.value,
        actor_user_id=actor_user_id, before=before,
        after=allocation_snapshot(payment),
        reason=(f"Manually allocated across {len(splits)} "
                f"{'unit' if len(splits) == 1 else 'units'}."),
    )
    return payment


# ---------------------------------------------------------------------------
# Reversals
# ---------------------------------------------------------------------------

def reverse_payment(payment, *, actor_user_id=None, reason=None):
    """
    Undo a payment's allocations (spec §4.11).

    Restores each line item's paid amount and its invoice's totals, claws back
    any credit the overflow created, and flags the payment. Never nets silently
    against a future payment — a reversal is a visible event the manager has to
    see, because the tenant's balance just moved without them doing anything.
    """
    from models import CreditLedger, Invoice, InvoiceLineItem, InvoiceStatus, LineItemStatus

    before = allocation_snapshot(payment)

    for allocation in list(payment.payment_allocations or []):
        amount = _D(allocation.amount_allocated)
        line = db.session.get(InvoiceLineItem, allocation.line_item_id) \
            if allocation.line_item_id else None
        if line is not None:
            line.amount_paid = max(ZERO, _D(line.amount_paid) - amount)
            line.status = (LineItemStatus.paid.value
                           if line.amount_paid >= _D(line.amount)
                           else LineItemStatus.open.value)
        invoice = db.session.get(Invoice, allocation.invoice_id)
        if invoice is not None:
            invoice.amount_paid = max(ZERO, _D(invoice.amount_paid) - amount)
            invoice.balance = _D(invoice.total_amount) - _D(invoice.amount_paid)
            invoice.status = (
                InvoiceStatus.paid.value if invoice.balance <= ZERO
                else InvoiceStatus.partial.value if _D(invoice.amount_paid) > ZERO
                else InvoiceStatus.open.value
            )
        db.session.delete(allocation)

    tenant = payment.tenant
    if tenant is not None:
        # Any surplus this payment parked as credit goes back out with it.
        credits = db.session.query(CreditLedger).filter(
            CreditLedger.payment_id == payment.id
        ).all()
        for row in credits:
            tenant.credit_balance = _D(tenant.credit_balance) - _D(row.amount)
            db.session.delete(row)
        tenant.balance = _D(tenant.balance) + _D(payment.amount)

    payment.status = PaymentStatus.reversed.value
    db.session.flush()

    record_allocation_audit(
        payment, AllocationAuditAction.reverse.value,
        actor_user_id=actor_user_id, before=before, after=[],
        reason=reason or "Payment reversed.",
    )
    return payment


def handle_reversal_sms(landlord_id: int, mpesa_code: str, *, reason=None):
    """
    An M-Pesa reversal message names the ORIGINAL transaction code. Find that
    payment and reverse it; if we never recorded it, there is nothing to undo.
    """
    payment = (
        db.session.query(Payment)
        .filter(Payment.landlord_id == landlord_id,
                Payment.mpesa_reference == mpesa_code,
                Payment.is_deleted.is_(False))
        .first()
    )
    if payment is None:
        return None
    return reverse_payment(payment, reason=reason or f"M-Pesa reversal of {mpesa_code}.")
