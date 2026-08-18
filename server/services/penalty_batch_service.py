"""
services/penalty_batch_service.py — charging a penalty to many tenants at once,
on purpose, right now.

The existing engine (services/penalty_service.py) is AUTOMATIC: each property
carries a policy, and a nightly run charges whoever it matches. That is the
right shape for a standing rule and the wrong shape for a decision — "everyone
in Riverside who is more than ten days late gets 500 this month" is a judgement
somebody makes on a Tuesday, not a policy they want running forever.

So this module is the manual counterpart:

    candidates()  who WOULD be charged, given some filters — changing nothing
    run()         charge the ones actually chosen

The filters compose (property, how much is owed, how late, and finally a
hand-picked list), because the real question is usually a combination: "Riverside
and Kileleshwa, owing over 5,000, more than a week late — except Mrs Otieno,
she's arranged something."

WHERE THE CHARGE LANDS is the caller's choice:

    new       raise a penalty invoice of its own
    existing  append a line to the tenant's open invoice, so they get one bill
              rather than two in the same month

Neither is right in general. A manager sending one statement a month wants the
line appended; one who bills penalties separately so they can be waived
independently wants its own invoice.

Nothing here re-implements what the automatic engine already knows: the amount
rules, the once-per-month guard and the ledger effect all come from
penalty_service, so a manual charge and an automatic one are the same object
afterwards and reconcile together.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def candidates(landlord_id: int, *, property_ids=None, min_balance=None,
               max_balance=None, min_days_overdue=None,
               allowed_property_ids=None) -> list[dict]:
    """
    Tenants who match the filters, with the figures the decision needs.

    Read-only, and deliberately returns everyone who matches rather than a
    count: a manager is about to charge real money to real people, and the list
    is the thing they check before doing it.

    `allowed_property_ids` is the caller's own property scope (None = no
    restriction) — a block-scoped team member must not be able to fine another
    block's tenants by passing its id.
    """
    from extensions import db
    from models import Invoice, InvoiceStatus, Property, Tenant, Unit
    from services.penalty_service import arrears_of, charged_this_month

    today = date.today()

    query = (
        db.session.query(Tenant, Unit, Property)
        .join(Unit, Unit.id == Tenant.unit_id)
        .join(Property, Property.id == Unit.property_id)
        .filter(Tenant.landlord_id == landlord_id,
                Tenant.is_deleted.is_(False),
                Property.is_deleted.is_(False))
    )

    if property_ids:
        query = query.filter(Property.id.in_(property_ids))
    if allowed_property_ids is not None:
        query = query.filter(Property.id.in_(allowed_property_ids))

    rows = []
    for tenant, unit, prop in query.all():
        arrears = arrears_of(tenant)
        # Someone who owes nothing is not late, whatever the date says.
        if arrears <= ZERO:
            continue
        if min_balance is not None and arrears < _money(min_balance):
            continue
        if max_balance is not None and arrears > _money(max_balance):
            continue

        # How late: measured from the oldest unpaid invoice's due date, not from
        # the newest. A tenant three months behind is three months late, and
        # dating them from last week's invoice would let the worst debtors slip
        # under a "more than 10 days" filter.
        oldest_due = (
            db.session.query(db.func.min(Invoice.due_date))
            .filter(Invoice.tenant_id == tenant.id,
                    Invoice.is_deleted.is_(False),
                    Invoice.status.in_([InvoiceStatus.open.value,
                                        InvoiceStatus.partial.value]))
            .scalar()
        )
        days_overdue = (today - oldest_due).days if oldest_due else 0
        if min_days_overdue is not None and days_overdue < int(min_days_overdue):
            continue

        open_invoice = (
            db.session.query(Invoice)
            .filter(Invoice.tenant_id == tenant.id,
                    Invoice.is_deleted.is_(False),
                    Invoice.status.in_([InvoiceStatus.open.value,
                                        InvoiceStatus.partial.value]))
            .order_by(Invoice.issue_date.desc())
            .first()
        )

        rows.append({
            "tenant_id":     tenant.id,
            "tenant_name":   f"{tenant.first_name} {tenant.last_name}".strip(),
            "unit_name":     unit.name,
            "property_id":   prop.id,
            "property_name": prop.name,
            "arrears":       float(arrears),
            "days_overdue":  days_overdue,
            "open_invoice_id":     open_invoice.id if open_invoice else None,
            "open_invoice_number": open_invoice.invoice_number if open_invoice else None,
            # Surfaced rather than silently filtered: a manager who sees
            # "already charged this month" understands why the number is lower
            # than they expected, where a shorter list just looks wrong.
            "already_charged_this_month": charged_this_month(tenant.id, today.year, today.month),
        })

    rows.sort(key=lambda r: (-r["days_overdue"], -r["arrears"]))
    return rows


def amount_for_row(row: dict, *, flat=None, percentage=None) -> Decimal:
    """
    What this tenant is charged: a flat sum, or a percentage of what they owe.

    A percentage is the fairer instrument on a mixed book — 5% of 2,000 and 5%
    of 200,000 are proportionate where a flat 1,000 is punitive on one and
    trivial on the other.
    """
    if percentage not in (None, ""):
        return _money(Decimal(str(row["arrears"])) * Decimal(str(percentage)) / Decimal("100"))
    return _money(flat)


def run(landlord, tenant_ids: list[int], *, flat=None, percentage=None,
        target: str = "new", note: str | None = None,
        skip_already_charged: bool = True,
        actor_user_id: int | None = None) -> dict:
    """
    Charge the chosen tenants. Returns a per-tenant result, not just a count.

    `target`:
        "new"      a penalty invoice of its own
        "existing" appended to their open invoice, falling back to a new one
                   when they have none — a tenant with nothing open still has
                   to be billed somehow.

    Errors are collected per tenant rather than raised: one tenant with no unit
    must not abandon a run half-finished, which would leave a manager unsure who
    had been charged.
    """
    from extensions import db
    from models import PenaltySource, Tenant
    from services.audit_service import record_audit
    from services.penalty_service import (
        arrears_of, charge_tenant, charged_this_month, policy_for,
    )

    today = date.today()
    charged, skipped = [], []

    for tenant_id in tenant_ids:
        tenant = db.session.get(Tenant, tenant_id)
        if tenant is None or tenant.landlord_id != landlord.id or tenant.is_deleted:
            skipped.append({"tenant_id": tenant_id, "reason": "not found on this account"})
            continue

        arrears = arrears_of(tenant)
        if arrears <= ZERO:
            skipped.append({"tenant_id": tenant_id, "tenant_name": _name(tenant),
                            "reason": "owes nothing"})
            continue

        # The automatic engine's once-a-month guard. A manual run defaults to
        # respecting it: charging twice in one month because a run was repeated
        # is the mistake this prevents, and it is expensive to unpick.
        # ANY source, not just automatic — the mistake being guarded against is
        # somebody running the same manual batch twice.
        if skip_already_charged and charged_this_month(tenant.id, today.year, today.month):
            skipped.append({"tenant_id": tenant_id, "tenant_name": _name(tenant),
                            "reason": "already penalised this month"})
            continue

        amount = amount_for_row(
            {"arrears": float(arrears)}, flat=flat, percentage=percentage)
        if amount <= ZERO:
            skipped.append({"tenant_id": tenant_id, "tenant_name": _name(tenant),
                            "reason": "amount works out at zero"})
            continue

        unit = tenant.unit
        if unit is None or unit.property is None:
            skipped.append({"tenant_id": tenant_id, "tenant_name": _name(tenant),
                            "reason": "no unit on this tenancy"})
            continue

        if target == "existing":
            charge = _charge_onto_open_invoice(
                landlord, tenant, amount, today=today, note=note,
                actor_user_id=actor_user_id)
        else:
            charge = charge_tenant(
                tenant, policy_for(unit.property_id), amount, today=today,
                source=PenaltySource.manual.value, actor_user_id=actor_user_id,
                note=note)

        if charge is None:
            skipped.append({"tenant_id": tenant_id, "tenant_name": _name(tenant),
                            "reason": "could not be charged"})
            continue

        charged.append({
            "tenant_id":   tenant.id,
            "tenant_name": _name(tenant),
            "amount":      float(amount),
            "invoice_id":  charge.invoice_id,
        })

    db.session.commit()

    record_audit(
        actor_user_id=actor_user_id,
        landlord_id=landlord.id,
        action="batch_penalty_run",
        entity_type="penalty",
        entity_id=None,
        description=(
            f"Manual penalty run: {len(charged)} charged, {len(skipped)} skipped "
            f"({'percentage ' + str(percentage) + '%' if percentage else 'flat ' + str(flat)}, "
            f"onto {'existing invoices' if target == 'existing' else 'new invoices'})."
        ),
        after_data={"charged": charged, "skipped": skipped},
    )
    db.session.commit()

    return {
        "charged": charged,
        "skipped": skipped,
        "total_charged": float(sum(Decimal(str(c["amount"])) for c in charged)) if charged else 0.0,
    }


def _name(tenant) -> str:
    return f"{tenant.first_name} {tenant.last_name}".strip()


def _charge_onto_open_invoice(landlord, tenant, amount: Decimal, *, today: date,
                              note: str | None, actor_user_id: int | None):
    """
    Append the penalty to the tenant's open invoice instead of raising one.

    Falls back to a normal penalty invoice when nothing is open — a tenant with
    no current bill still has to be charged somehow, and silently skipping them
    would make the run's totals wrong.

    The PenaltyCharge row is written either way, so the penalties report and the
    once-a-month guard see manual charges exactly as they see automatic ones.
    """
    from extensions import db
    from models import (
        Invoice, InvoiceLineItem, InvoiceStatus, PenaltyCharge, PenaltySource,
    )
    from services.penalty_service import (
        _penalty_category_id, arrears_of, charge_tenant, policy_for,
    )

    invoice = (
        db.session.query(Invoice)
        .filter(Invoice.tenant_id == tenant.id,
                Invoice.landlord_id == landlord.id,
                Invoice.is_deleted.is_(False),
                Invoice.status.in_([InvoiceStatus.open.value,
                                    InvoiceStatus.partial.value]))
        .order_by(Invoice.issue_date.desc())
        .first()
    )
    if invoice is None:
        return charge_tenant(
            tenant, policy_for(tenant.unit.property_id), amount, today=today,
            source=PenaltySource.manual.value, actor_user_id=actor_user_id,
            note=note)

    basis = arrears_of(tenant)
    db.session.add(InvoiceLineItem(
        invoice_id=invoice.id,
        item="Late payment penalty",
        description=note or f"Penalty applied {today:%d %b %Y}",
        quantity=Decimal("1"),
        unit_price=amount,
        amount=amount,
        # The Penalty category is what keeps this out of the commissionable rent
        # bucket and what makes the penalties report able to see it at all.
        category_id=_penalty_category_id(landlord.id),
        subcategory="current",
    ))

    invoice.total_amount = (invoice.total_amount or ZERO) + amount
    invoice.balance = invoice.total_amount - (invoice.amount_paid or ZERO)
    # Charges make the balance MORE negative — see penalty_service.arrears_of()
    # for the sign convention.
    tenant.balance = (tenant.balance or ZERO) - amount

    titles = [p.strip() for p in (invoice.title or "").split(",") if p.strip()]
    if "Penalty" not in titles:
        titles.append("Penalty")
        invoice.title = ", ".join(titles)

    charge = PenaltyCharge(
        landlord_id   = landlord.id,
        property_id   = tenant.unit.property_id,
        unit_id       = tenant.unit_id,
        tenant_id     = tenant.id,
        invoice_id    = invoice.id,
        policy_id     = None,          # a manual charge follows no policy
        period_year   = today.year,
        period_month  = today.month,
        source        = PenaltySource.manual.value,
        basis_balance = basis,
        amount        = amount,
        note          = note,
        applied_by    = actor_user_id,
    )
    db.session.add(charge)
    db.session.flush()
    return charge
