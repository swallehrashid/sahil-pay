"""
5-month full-engine simulation harness (diagnostic, non-destructive to seed data).

Creates a dedicated simulation landlord ("SIM 5-Month Ltd") with a realistic tenant
mix, then advances the clock 5 months, running the REAL billing/rollover/credit/
allocation engine each month and asserting money invariants after every cycle.

Covers scenario-catalogue sections A3 (billing), A4 (payments), A5 (invoices),
A6 (utilities), F7 (money invariants). HTTP-level portal/auth checks run separately
in sim_http_checks.py.

Run:  venv/bin/python simulate_5months.py
Exit code 0 = all invariants held; non-zero = a failure (printed).
"""
import sys
from decimal import Decimal
from datetime import date

from app import create_app
from extensions import db
import models as m
from utils import gen_reference, hash_password
from services.category_service import seed_default_categories
from services.allocation_service import (
    auto_allocate, apply_allocations, normalize_manual_allocations,
    outstanding_line_items,
)
from tasks.invoice_tasks import _run_monthly_billing_for_tenant

SIM_EMAIL = "sim5month@sahilpay.test"
FAILURES = []
CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"   ✓ {label}")
    else:
        print(f"   ✗ FAIL: {label}")
        FAILURES.append(label)


def _first_of(y, mo):
    return date(y, mo, 1)


def cleanup_existing():
    """Remove any prior sim landlord so the run is repeatable."""
    u = m.User.query.filter_by(email=SIM_EMAIL).first()
    if not u:
        return
    ll = m.Landlord.query.filter_by(user_id=u.id).first()
    if ll:
        tenant_ids = [t.id for t in m.Tenant.query.filter_by(landlord_id=ll.id).all()]
        inv_ids = [i.id for i in m.Invoice.query.filter_by(landlord_id=ll.id).all()]
        li_ids = [li.id for li in m.InvoiceLineItem.query.filter(m.InvoiceLineItem.invoice_id.in_(inv_ids)).all()] if inv_ids else []
        if li_ids:
            m.PaymentAllocation.query.filter(m.PaymentAllocation.line_item_id.in_(li_ids)).delete(synchronize_session=False)
        m.PaymentAllocation.query.filter(m.PaymentAllocation.invoice_id.in_(inv_ids)).delete(synchronize_session=False) if inv_ids else None
        m.BalanceRollover.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.CreditLedger.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.Payment.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        if inv_ids:
            m.InvoiceLineItem.query.filter(m.InvoiceLineItem.invoice_id.in_(inv_ids)).delete(synchronize_session=False)
        m.Invoice.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.Tenant.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.Unit.query.filter(m.Unit.property_id.in_([p.id for p in m.Property.query.filter_by(landlord_id=ll.id).all()])).delete(synchronize_session=False)
        m.Property.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.ChargeCategory.query.filter_by(landlord_id=ll.id).delete(synchronize_session=False)
        m.Landlord.query.filter_by(id=ll.id).delete(synchronize_session=False)
    m.User.query.filter_by(email=SIM_EMAIL).delete(synchronize_session=False)
    db.session.commit()


def build_landlord():
    user = m.User(email=SIM_EMAIL, password_hash=hash_password("Sim@12345"),
                  role=m.UserRole.landlord.value, is_active=True, is_verified=True)
    db.session.add(user)
    db.session.flush()
    ll = m.Landlord(user_id=user.id, company_name="SIM 5-Month Ltd",
                    abbreviated_name="SIM5", company_address="1 Sim Road, Nairobi")
    db.session.add(ll)
    db.session.flush()
    seed_default_categories(ll.id)
    db.session.flush()
    cats = {c.name: c for c in m.ChargeCategory.query.filter_by(landlord_id=ll.id).all()}
    prop = m.Property(landlord_id=ll.id, name="Sim Court", city="Nairobi",
                      street_name="Sim Ave", number_of_units=5)
    db.session.add(prop)
    db.session.flush()
    units = {}
    for i in range(1, 6):
        u = m.Unit(property_id=prop.id, name=f"S{i}", rent_amount=Decimal("12000"),
                   is_occupied=True)
        db.session.add(u)
        units[f"S{i}"] = u
    db.session.flush()
    return ll, prop, units, cats


def make_tenant(ll, unit, fn, phone, acct):
    t = m.Tenant(landlord_id=ll.id, unit_id=unit.id,
                 first_name=fn, last_name="Sim", phone=phone,
                 email=f"{fn.lower()}@sim.test", account_number=acct,
                 balance=Decimal("0"), credit_balance=Decimal("0"))
    db.session.add(t)
    db.session.flush()
    return t


def bill(ll, tenant, month):
    _run_monthly_billing_for_tenant(ll, tenant, month, month, None)
    db.session.flush()


def pay(ll, prop, tenant, amount, when, mode="auto", manual=None):
    p = m.Payment(payment_ref=gen_reference("PMT"), landlord_id=ll.id, tenant_id=tenant.id,
                  unit_id=tenant.unit_id, property_id=prop.id if prop else None, amount=Decimal(str(amount)),
                  payment_date=when, status=m.PaymentStatus.confirmed.value,
                  source=(m.PaymentSource.manual.value if mode == "manual" else m.PaymentSource.mpesa.value),
                  payment_method=("Manual" if mode == "manual" else "M-Pesa"))
    db.session.add(p)
    db.session.flush()
    rows = (normalize_manual_allocations(manual, tenant, ll, ref_date=when)
            if mode == "manual" else auto_allocate(tenant, p.amount, ll, ref_date=when))
    apply_allocations(p, tenant, rows, ll.id)
    db.session.flush()
    return p


def invariants(ll, tenants, label):
    print(f"\n-- Invariants after {label} --")
    for t in tenants:
        db.session.refresh(t)
        outstanding = sum((li.remaining for li in outstanding_line_items(t)), Decimal("0"))
        # Money invariant F7: outstanding open (non-deposit... deposits ARE owed too) == -balance.
        # tenant.balance is negative when they owe. Deposits count as owed but never roll.
        check(outstanding == -t.balance,
              f"{t.first_name}: outstanding {outstanding} == -balance {-t.balance}")
        # Credit invariant: credit_balance == sum(credit_ledger)
        ledger_sum = db.session.query(db.func.coalesce(db.func.sum(m.CreditLedger.amount), 0)) \
            .filter_by(tenant_id=t.id).scalar() or Decimal("0")
        check(Decimal(str(ledger_sum)) == t.credit_balance,
              f"{t.first_name}: credit_balance {t.credit_balance} == ledger {ledger_sum}")
    # No deposit line ever rolled
    rolled_deposits = m.InvoiceLineItem.query.filter_by(
        subcategory=m.SubCategory.deposit.value, status=m.LineItemStatus.rolled.value
    ).join(m.Invoice).filter(m.Invoice.landlord_id == ll.id).count()
    check(rolled_deposits == 0, "no deposit line ever rolled")


def run():
    app = create_app()
    with app.app_context():
        print("=== SIM: cleanup any prior run ===")
        cleanup_existing()
        print("=== SIM: build landlord/property/units ===")
        ll, prop, units, cats = build_landlord()

        # Tenant mix mirrors real-world payer archetypes:
        alice = make_tenant(ll, units["S1"], "Alice", "0799000001", "SIM-A")  # always pays full
        ben   = make_tenant(ll, units["S2"], "Ben",   "0799000002", "SIM-B")  # chronic partial
        carol = make_tenant(ll, units["S3"], "Carol", "0799000003", "SIM-C")  # overpayer
        dan   = make_tenant(ll, units["S4"], "Dan",   "0799000004", "SIM-D")  # stops paying month 3
        eve   = make_tenant(ll, units["S5"], "Eve",   "0799000005", "SIM-E")  # pays late (catches up m5)
        tenants = [alice, ben, carol, dan, eve]
        db.session.commit()

        months = [_first_of(2026, mo) for mo in (8, 9, 10, 11, 12)]  # Aug..Dec 2026
        rent = Decimal("12000")

        for idx, mo in enumerate(months, 1):
            print(f"\n=== MONTH {idx}  ({mo.isoformat()}) ===")
            for t in tenants:
                bill(ll, t, mo)

            # Alice: full every month
            outstanding_a = sum((li.remaining for li in outstanding_line_items(alice)), Decimal("0"))
            pay(ll, prop, alice, outstanding_a, mo, mode="auto")

            # Ben: pays only 5000 each month -> chronic arrears, rollover accumulates
            pay(ll, prop, ben, Decimal("5000"), mo, mode="auto")

            # Carol: overpays by 3000 in month 1 only; credit auto-consumed later
            if idx == 1:
                out_c = sum((li.remaining for li in outstanding_line_items(carol)), Decimal("0"))
                pay(ll, prop, carol, out_c + Decimal("3000"), mo, mode="auto")
            else:
                out_c = sum((li.remaining for li in outstanding_line_items(carol)), Decimal("0"))
                if out_c > 0:
                    pay(ll, prop, carol, out_c, mo, mode="auto")

            # Dan: pays months 1-2 full, then STOPS (months 3-5 nothing) -> deep arrears
            if idx <= 2:
                out_d = sum((li.remaining for li in outstanding_line_items(dan)), Decimal("0"))
                pay(ll, prop, dan, out_d, mo, mode="auto")

            # Eve: pays nothing months 1-4, then clears everything in month 5
            if idx == 5:
                out_e = sum((li.remaining for li in outstanding_line_items(eve)), Decimal("0"))
                pay(ll, prop, eve, out_e, mo, mode="auto")

            db.session.commit()
            invariants(ll, tenants, f"month {idx}")

        # Final assertions on archetype outcomes
        print("\n=== FINAL outcome checks ===")
        db.session.refresh(alice); db.session.refresh(dan); db.session.refresh(eve)
        check(alice.balance == 0, f"Alice fully settled (balance {alice.balance})")
        check(dan.balance < 0, f"Dan in arrears after stopping (balance {dan.balance})")
        check(eve.balance == 0, f"Eve caught up in month 5 (balance {eve.balance})")

        # Rollover provenance: Ben should have BalanceRollover rows spanning multiple origin months
        ben_rolls = m.BalanceRollover.query.filter_by(tenant_id=ben.id).count()
        check(ben_rolls > 0, f"Ben has rollover provenance rows ({ben_rolls})")

        # Idempotency: re-run month 5 billing -> no new invoice (skip guard)
        inv_before = m.Invoice.query.filter_by(landlord_id=ll.id).count()
        bill(ll, alice, months[-1])
        db.session.commit()
        inv_after = m.Invoice.query.filter_by(landlord_id=ll.id).count()
        check(inv_after == inv_before, f"idempotent re-bill (invoices {inv_before} -> {inv_after})")

        print(f"\n=== SIM COMPLETE: {CHECKS} checks, {len(FAILURES)} failures ===")
        for f in FAILURES:
            print(f"   FAILED: {f}")
        return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
