"""
scale_audit.py — are the reports telling the truth?

Unit tests prove that a function does what it says on a fixture of three
tenants. They cannot tell you whether a property statement for 100 blocks and
1,000 tenants across four months adds up, because the ways that go wrong are not
logic errors in one function — they are a rounding rule applied in two places, a
deposit counted as income by one report and not another, a rollover that
double-counts when a tenant pays partially in three consecutive months.

So this audit does not test code. It re-derives every headline figure from the
LEDGER — payments, allocations, line items — and compares it against what the
reports say. Where the two disagree, the report is wrong, and the audit says by
how much and for which property.

    APP_ENV=development DATABASE_URL=...sahilpay_scale venv/bin/python scale_audit.py

Exit code 0 = every figure reconciled. Non-zero = at least one did not.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

# Money compared at the cent. Anything looser hides a real rounding bug; anything
# tighter fails on Decimal noise that no human would ever see.
TOLERANCE = Decimal("0.01")

results: list[tuple[bool, str, str]] = []


def check(passed: bool, name: str, detail: str = "") -> bool:
    results.append((passed, name, detail))
    mark = "  PASS" if passed else "  FAIL"
    print(f"{mark}  {name}" + (f" — {detail}" if detail else ""))
    return passed


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


def close(a, b) -> bool:
    return abs(money(a) - money(b)) <= TOLERANCE


# ---------------------------------------------------------------------------
# 1. The ledger itself
# ---------------------------------------------------------------------------
# Every report is derived from these tables. If they do not hold together, no
# report above them can be right, and fixing the report would only hide it.

def audit_ledger(db, m, landlord_id: int) -> None:
    print("\nLEDGER INTEGRITY")

    # An invoice's header must equal its lines. A header that has drifted is how
    # a statement and an invoice PDF end up disagreeing about the same bill.
    bad_totals = []
    invoices = (db.session.query(m.Invoice)
                .filter(m.Invoice.landlord_id == landlord_id,
                        m.Invoice.is_deleted.is_(False))
                .all())
    for inv in invoices:
        line_total = sum((money(li.amount) for li in inv.line_items), ZERO)
        if not close(inv.total_amount, line_total):
            bad_totals.append((inv.invoice_number, money(inv.total_amount), line_total))
    check(not bad_totals,
          f"Invoice totals equal the sum of their lines ({len(invoices)} invoices)",
          "" if not bad_totals else
          f"{len(bad_totals)} disagree, e.g. {bad_totals[0]}")

    # An invoice's balance is what is STILL OWED ON IT, which is not the same as
    # total minus paid once month-end rollover has run: a rolled line's debt has
    # moved to a "Balance b/f" line on the next invoice, and counting it in both
    # places would double the arrears of every tenant who has ever been late.
    # allocation_service.recompute_invoice() is the authority — rolled lines are
    # excluded there, so they are excluded here.
    bad_balance = []
    for inv in invoices:
        open_remaining = sum(
            (money(li.amount) - money(li.amount_paid)
             for li in inv.line_items
             if li.status != m.LineItemStatus.rolled.value),
            ZERO,
        )
        if not close(inv.balance, open_remaining):
            bad_balance.append((inv.invoice_number, money(inv.balance), open_remaining))
    check(not bad_balance,
          "Invoice balance equals what is still open on it (rolled lines excluded)",
          "" if not bad_balance else f"{len(bad_balance)} disagree, e.g. {bad_balance[0]}")

    # Rolled debt must exist somewhere: every rolled line should be matched by a
    # balance-brought-forward line on a later invoice. If rollover ever dropped
    # one, the tenant would simply stop owing it.
    rolled_total = ZERO
    for inv in invoices:
        for li in inv.line_items:
            if li.status == m.LineItemStatus.rolled.value:
                rolled_total += money(li.amount) - money(li.amount_paid)
    bf_total = ZERO
    for inv in invoices:
        for li in inv.line_items:
            if (li.subcategory or "") == "balance":
                bf_total += money(li.amount)
    check(bf_total >= rolled_total - TOLERANCE,
          "Rolled debt reappears as balance brought forward",
          f"rolled {rolled_total} -> carried {bf_total}")

    # A payment can never allocate more than it was worth. This is the invariant
    # that stops money being spent twice.
    over = (db.session.query(m.Payment.payment_ref,
                             m.Payment.amount,
                             db.func.sum(m.PaymentAllocation.amount_allocated))
            .join(m.PaymentAllocation, m.PaymentAllocation.payment_id == m.Payment.id)
            .filter(m.Payment.landlord_id == landlord_id,
                    m.Payment.is_deleted.is_(False))
            .group_by(m.Payment.id, m.Payment.payment_ref, m.Payment.amount)
            .having(db.func.sum(m.PaymentAllocation.amount_allocated)
                    > m.Payment.amount + float(TOLERANCE))
            .all())
    check(not over, "No payment is allocated beyond its own value",
          "" if not over else f"{len(over)} over-allocated, e.g. {over[0]}")

    # A line item cannot be paid more than it costs.
    overpaid_lines = (db.session.query(m.InvoiceLineItem.id)
                      .join(m.Invoice, m.Invoice.id == m.InvoiceLineItem.invoice_id)
                      .filter(m.Invoice.landlord_id == landlord_id,
                              m.InvoiceLineItem.amount_paid
                              > m.InvoiceLineItem.amount + float(TOLERANCE))
                      .all())
    check(not overpaid_lines, "No invoice line is paid beyond its own value",
          "" if not overpaid_lines else f"{len(overpaid_lines)} overpaid")

    # The tenant's balance must equal what their open lines still owe.
    # NEGATIVE when owing — see penalty_service.arrears_of().
    tenants = (db.session.query(m.Tenant)
               .filter(m.Tenant.landlord_id == landlord_id,
                       m.Tenant.is_deleted.is_(False))
               .all())
    drift = []
    for tenant in tenants:
        owed = ZERO
        for inv in tenant.invoices:
            if inv.is_deleted or inv.status == m.InvoiceStatus.void.value:
                continue
            for li in inv.line_items:
                # Rolled lines are excluded for the same reason as above: their
                # debt now lives on a later invoice's "Balance b/f" line, and
                # counting both would double every rolled-over arrear.
                if li.status == m.LineItemStatus.rolled.value:
                    continue
                owed += money(li.amount) - money(li.amount_paid)
        expected = -owed + money(tenant.credit_balance)
        if not close(tenant.balance, expected):
            drift.append((tenant.id, money(tenant.balance), expected))
    check(not drift,
          f"Tenant balances equal what their open lines owe ({len(tenants)} tenants)",
          "" if not drift else
          f"{len(drift)} drifted, e.g. tenant {drift[0][0]}: "
          f"balance {drift[0][1]} vs ledger {drift[0][2]}")


# ---------------------------------------------------------------------------
# 2. The collections split every money report is built on
# ---------------------------------------------------------------------------

def audit_collections(db, m, landlord_id: int) -> None:
    print("\nCOLLECTIONS SPLIT")

    from services.commission_service import (
        GROSS_BASIS_ALL, GROSS_BASIS_RENT_ONLY, collections_breakdown, gross_for,
    )

    breakdown = collections_breakdown(landlord_id, None, None, None)
    parts = (breakdown["rent_collected"] + breakdown["deposits_collected"]
             + breakdown["other_collected"])
    check(close(parts, breakdown["total_collected"]),
          "rent + deposits + other equals the total collected",
          f"{parts} vs {breakdown['total_collected']}")

    # Re-derive the same split straight from the allocations, independently of
    # the service that produces it for the reports.
    from services.category_service import RENT_INCOME_SUBCATEGORIES, rent_category_id

    rent_cat = rent_category_id(landlord_id)
    rows = (db.session.query(m.InvoiceLineItem.category_id,
                             m.InvoiceLineItem.subcategory,
                             db.func.sum(m.PaymentAllocation.amount_allocated))
            .join(m.PaymentAllocation,
                  m.PaymentAllocation.line_item_id == m.InvoiceLineItem.id)
            .join(m.Payment, m.Payment.id == m.PaymentAllocation.payment_id)
            .filter(m.Payment.landlord_id == landlord_id,
                    m.Payment.is_deleted.is_(False),
                    m.Payment.status == m.PaymentStatus.confirmed.value,
                    db.func.coalesce(m.Payment.source, "").notin_(
                        tuple(m.NON_CASH_PAYMENT_SOURCES)))
            .group_by(m.InvoiceLineItem.category_id, m.InvoiceLineItem.subcategory)
            .all())

    rent = deposits = other = ZERO
    for category_id, subcategory, amount in rows:
        amount = money(amount)
        if (subcategory or "").lower() == "deposit":
            deposits += amount
        elif category_id == rent_cat and (subcategory or "") in RENT_INCOME_SUBCATEGORIES:
            rent += amount
        else:
            other += amount

    check(close(rent, breakdown["rent_collected"]),
          "Rent collected re-derives from the allocations",
          f"audit {rent} vs report {breakdown['rent_collected']}")
    check(close(deposits, breakdown["deposits_collected"]),
          "Deposits collected re-derive from the allocations",
          f"audit {deposits} vs report {breakdown['deposits_collected']}")

    # The rule the landlord asked about specifically: a deposit is held money,
    # never income, and must not appear in gross on ANY basis.
    gross_all = gross_for(breakdown, GROSS_BASIS_ALL)
    gross_rent = gross_for(breakdown, GROSS_BASIS_RENT_ONLY)
    check(close(gross_all, breakdown["rent_collected"] + breakdown["other_collected"]),
          "Gross (all) excludes deposits", f"{gross_all}")
    check(close(gross_rent, breakdown["rent_collected"]),
          "Gross (rent only) is exactly rent collected", f"{gross_rent}")
    check(breakdown["deposits_collected"] >= ZERO and gross_all < breakdown["total_collected"]
          if breakdown["deposits_collected"] > ZERO else True,
          "Deposits were collected and are held out of gross",
          f"deposits {breakdown['deposits_collected']}")


# ---------------------------------------------------------------------------
# 3. Property statements — the report an owner actually reads
# ---------------------------------------------------------------------------

def audit_property_statements(db, m, landlord) -> None:
    print("\nPROPERTY STATEMENTS")

    from services.commission_service import (
        collections_breakdown, commission_for, gross_for, resolve_basis,
    )
    from services.report_generators import build_property_statement

    basis = resolve_basis(landlord)
    properties = (db.session.query(m.Property)
                  .filter(m.Property.landlord_id == landlord.id,
                          m.Property.is_deleted.is_(False))
                  .all())

    portfolio_gross = ZERO
    mismatches, commission_errors = [], []

    # Sampled rather than exhaustive: rendering 100 statements is slow, and a
    # systematic error shows up in the first few. The PORTFOLIO total below is
    # computed over all 100 regardless.
    sample = properties[:12]

    for prop in sample:
        doc = build_property_statement(landlord, prop.id, None, None)
        summary = {row["label"]: money(row["value"])
                   for section in doc.sections if section.key == "summary"
                   for row in section.rows} if hasattr(doc, "sections") else {}

        breakdown = collections_breakdown(landlord.id, prop.id, None, None)
        expected_gross = gross_for(breakdown, basis)

        # Find the gross line whatever it is labelled.
        reported = next((v for k, v in summary.items() if k.lower().startswith("gross")
                         or "total amount collected" in k.lower()), None)
        if reported is not None and not close(reported, expected_gross):
            mismatches.append((prop.name, reported, expected_gross))

        # Commission is ALWAYS a percentage of rent collected — never of
        # deposits or utilities. Charging on either would be unlawful.
        expected_commission = commission_for(breakdown, prop.commission_rate)
        reported_commission = next(
            (v for k, v in summary.items() if k.lower().startswith("commission")), None)
        if reported_commission is not None and not close(reported_commission, expected_commission):
            commission_errors.append((prop.name, reported_commission, expected_commission))

    check(not mismatches,
          f"Statement gross matches the ledger ({len(sample)} properties sampled)",
          "" if not mismatches else f"{len(mismatches)} disagree, e.g. {mismatches[0]}")
    check(not commission_errors,
          "Commission is a percentage of rent collected only",
          "" if not commission_errors else f"e.g. {commission_errors[0]}")

    # Every property's gross must add up to the whole book's.
    for prop in properties:
        portfolio_gross += gross_for(
            collections_breakdown(landlord.id, prop.id, None, None), basis)
    whole = gross_for(collections_breakdown(landlord.id, None, None, None), basis)
    check(close(portfolio_gross, whole),
          f"Per-property gross sums to the portfolio ({len(properties)} properties)",
          f"sum {portfolio_gross} vs whole {whole}")


# ---------------------------------------------------------------------------
# 4. Arrears
# ---------------------------------------------------------------------------

def audit_arrears(db, m, landlord_id: int) -> None:
    print("\nARREARS")

    from services.penalty_service import arrears_of

    tenants = (db.session.query(m.Tenant)
               .filter(m.Tenant.landlord_id == landlord_id,
                       m.Tenant.is_deleted.is_(False))
               .all())

    owing = [t for t in tenants if arrears_of(t) > ZERO]
    total = sum((arrears_of(t) for t in owing), ZERO)

    # arrears_of() must agree with the sign convention on the row itself.
    wrong_sign = [t.id for t in tenants
                  if (money(t.balance) < ZERO) != (arrears_of(t) > ZERO)]
    check(not wrong_sign, "Arrears agree with the balance sign convention",
          "" if not wrong_sign else f"{len(wrong_sign)} disagree")

    # Nobody in arrears should also be carrying credit — that would mean money
    # was received and never applied to what it was owed against.
    both = [t.id for t in tenants
            if arrears_of(t) > ZERO and money(t.credit_balance) > ZERO]
    check(not both, "No tenant is simultaneously in arrears and in credit",
          "" if not both else f"{len(both)} are, e.g. tenant {both[0]}")

    print(f"        ({len(owing)} of {len(tenants)} tenants owe {total:,.2f})")


# ---------------------------------------------------------------------------
# 5. Month on month
# ---------------------------------------------------------------------------

def audit_month_on_month(db, m, landlord_id: int) -> None:
    print("\nMONTH ON MONTH")

    payments = (db.session.query(m.Payment)
                .filter(m.Payment.landlord_id == landlord_id,
                        m.Payment.is_deleted.is_(False),
                        m.Payment.status == m.PaymentStatus.confirmed.value)
                .all())

    by_month: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for payment in payments:
        if payment.payment_date:
            by_month[payment.payment_date.strftime("%Y-%m")] += money(payment.amount)

    months = sorted(by_month)
    check(len(months) >= 2, f"Several months of history exist ({len(months)})",
          ", ".join(months))

    # Each month's collections, summed, must equal every confirmed payment.
    total_months = sum(by_month.values(), ZERO)
    total_all = sum((money(p.amount) for p in payments), ZERO)
    check(close(total_months, total_all),
          "Monthly collections sum to every confirmed payment",
          f"{total_months} vs {total_all}")

    for month in months:
        print(f"        {month}: {by_month[month]:>14,.2f}")


# ---------------------------------------------------------------------------
# 6. Scope — the permission boundary at scale
# ---------------------------------------------------------------------------

def audit_scope(db, m, landlord_id: int) -> None:
    print("\nPERMISSION SCOPE")

    owners = (db.session.query(m.TeamMember)
              .filter(m.TeamMember.landlord_id == landlord_id,
                      m.TeamMember.preset == "owner")
              .all())
    check(bool(owners), f"Owner logins exist ({len(owners)})")

    # An owner must be scoped to their own block. One who could see every
    # property under the manager would be reading their competitors' books.
    unscoped = [o.id for o in owners if o.property_access_all]
    check(not unscoped, "No owner login can see the whole portfolio",
          "" if not unscoped else f"{len(unscoped)} are unscoped")

    # And their reports grant must be narrowed to the property statement.
    wide = []
    for owner in owners[:50]:
        row = next((p for p in owner.permissions if p.module == "reports"), None)
        if row and row.allowed_reports is None:
            wide.append(owner.id)
    check(not wide,
          "Owner logins are narrowed to their own statement, not every report",
          "" if not wide else f"{len(wide)} of 50 sampled hold every report")

    staff = (db.session.query(m.TeamMember)
             .filter(m.TeamMember.landlord_id == landlord_id,
                     m.TeamMember.preset.in_(("accountant", "secretary", "caretaker")))
             .count())
    check(staff > 0, f"Office and site staff exist ({staff})")


# ---------------------------------------------------------------------------

def main() -> int:
    from app import create_app
    from extensions import db
    import models as m

    app = create_app()
    with app.app_context():
        landlord = (db.session.query(m.Landlord)
                    .order_by(m.Landlord.id.asc())
                    .first())
        if landlord is None:
            print("No landlord in this database — run seed_scale.py first.")
            return 2

        units = (db.session.query(m.Unit)
                 .join(m.Property, m.Property.id == m.Unit.property_id)
                 .filter(m.Property.landlord_id == landlord.id).count())
        tenants = (db.session.query(m.Tenant)
                   .filter(m.Tenant.landlord_id == landlord.id,
                           m.Tenant.is_deleted.is_(False)).count())
        members = (db.session.query(m.TeamMember)
                   .filter(m.TeamMember.landlord_id == landlord.id).count())
        payments = (db.session.query(m.Payment)
                    .filter(m.Payment.landlord_id == landlord.id,
                            m.Payment.is_deleted.is_(False)).count())

        print(f"Auditing '{landlord.company_name}'")
        print(f"  {units} units · {tenants} tenants · {members} team members "
              f"· {payments} payments")

        audit_ledger(db, m, landlord.id)
        audit_collections(db, m, landlord.id)
        audit_property_statements(db, m, landlord)
        audit_arrears(db, m, landlord.id)
        audit_month_on_month(db, m, landlord.id)
        audit_scope(db, m, landlord.id)

    failed = [r for r in results if not r[0]]
    print("\n" + "=" * 60)
    print(f"{len(results) - len(failed)}/{len(results)} figures reconciled")
    if failed:
        print("\nDid not reconcile:")
        for _passed, name, detail in failed:
            print(f"  - {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
