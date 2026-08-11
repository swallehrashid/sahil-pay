"""
SahilPay — services/report_generators.py
=========================================
Report *builders*: each returns a `ReportDocument` (see report_builder.py).
The route layer decides whether to serialise it to JSON (preview), PDF, or
Excel. Keeping the query logic here and the rendering in report_builder means a
new report is "just a query", and every report automatically gets preview,
column-editing, letterhead and both download formats for free.

Money/ledger convention (matches the rest of the platform):
    tenant.balance < 0  => arrears (owed)      |  > 0 => advance/credit
    running balance = Σ(paid) − Σ(due)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from services.report_builder import (
    Column,
    ReportDocument,
    Section,
    build_meta,
    DATE,
    MONEY,
    NUMBER,
    PERCENT,
    TEXT,
)
from utils import parse_date

ZERO = Decimal("0.00")

# Charge-category restructure (spec §4.5). Two ledger rules keep reports from
# double-counting once balances roll and credit is re-applied:
#   • a "balance" line is a carried-forward re-presentation of debt already counted
#     in its origin month — it must NOT count again as a new charge.
#   • a "credit"-sourced payment is a re-application of money already received — it
#     must NOT count again as cash collected.
_BALANCE_SUB = "balance"                     # models.SubCategory.balance
_DEPOSIT_SUB = "deposit"                      # models.SubCategory.deposit
_NON_CASH_SOURCES = frozenset({"credit"})    # models.NON_CASH_PAYMENT_SOURCES


def _invoice_charge(inv) -> Decimal:
    """An invoice's real new charge for reports — excludes carried-forward b/f lines."""
    lines = inv.line_items or []
    if not lines:
        return inv.total_amount or ZERO
    return sum(((li.amount or ZERO) for li in lines if li.subcategory != _BALANCE_SUB), ZERO)


def _is_cash_payment(p) -> bool:
    """True unless the payment is a synthetic credit re-application (not new cash)."""
    return (p.source or "") not in _NON_CASH_SOURCES


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _period_label(start_date: str | None, end_date: str | None) -> str | None:
    s, e = parse_date(start_date), parse_date(end_date)
    if s and e:
        return f"{s.isoformat()} to {e.isoformat()}"
    if s:
        return f"From {s.isoformat()}"
    if e:
        return f"Up to {e.isoformat()}"
    return "All time"


def _in_range(d, start, end) -> bool:
    if d is None:
        return False
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _classify_line_item(item_name: str | None) -> str:
    """Bucket a free-text invoice line-item name into a report column."""
    n = (item_name or "").lower()
    if "rent" in n:
        return "rent"
    if "water" in n:
        return "water"
    if "garbage" in n or "refuse" in n or "trash" in n:
        return "garbage"
    if "service" in n:
        return "service_charge"
    if "security" in n or "guard" in n:
        return "security"
    if "penalt" in n or "late" in n or "fine" in n:
        return "penalties"
    if "deposit" in n:
        return "deposit"
    if "electric" in n or "power" in n:
        return "electricity"
    return "other"


def _effective_tax_rate(unit, prop, landlord) -> Decimal:
    """Tax rate cascade: unit → property → landlord default."""
    if unit is not None and unit.tax_rate is not None:
        return Decimal(str(unit.tax_rate))
    if prop is not None and getattr(prop, "tax_rate", None) is not None:
        return Decimal(str(prop.tax_rate))
    return Decimal(str(getattr(landlord, "default_tax_rate", 0) or 0))


def _not_found(report_key: str, title: str, landlord, message: str) -> ReportDocument:
    meta = build_meta(landlord, report_title=title)
    section = Section("error", "Not found", [Column("message", "Message", TEXT)], [{"message": message}])
    return ReportDocument(report_key, title, meta, [section])


# ===========================================================================
# 1. Tenant Statement
# ===========================================================================


def build_tenant_statement(landlord, tenant_id: int, start_date: str | None, end_date: str | None,
                           include_etims: bool = False) -> ReportDocument:
    from models import Invoice, Payment, Tenant

    tenant = Tenant.query.filter_by(id=tenant_id, landlord_id=landlord.id).first()
    if tenant is None:
        return _not_found("tenant_statement", "Tenant Statement", landlord, "Tenant not found.")

    start, end = parse_date(start_date), parse_date(end_date)

    # #13 — a single chronological ledger: every invoice (charge) and every confirmed
    # payment (credit) as one dated event, ordered by (effective date, created_at, id)
    # so same-day events keep the true order they were recorded in. The running balance
    # is recomputed after each event, in the #10 sign convention (owed = positive,
    # advance/credit = negative).
    invoices = Invoice.query.filter_by(tenant_id=tenant_id).filter_by(is_deleted=False).all()
    payments = [p for p in Payment.query.filter_by(tenant_id=tenant_id).all()
                if not p.is_deleted and (p.status or "") == "confirmed" and _is_cash_payment(p)]

    # sort key uses created_at (falls back to a huge sentinel so undated sorts last)
    def _key(d, created, oid):
        return (d or date.max, created or datetime.max, oid or 0)

    # (sortkey, date, item, description, due, paid)
    events: list[tuple] = []
    for inv in invoices:
        raw_lines = inv.line_items or []
        if raw_lines:
            # Skip carried-forward b/f lines — the debt already appears in its origin month.
            for li in raw_lines:
                if li.subcategory == _BALANCE_SUB:
                    continue
                events.append((_key(inv.issue_date, inv.created_at, inv.id), inv.issue_date, li.item,
                               li.description or f"Invoice {inv.invoice_number}", li.amount or ZERO, ZERO))
        else:
            events.append((_key(inv.issue_date, inv.created_at, inv.id), inv.issue_date,
                           inv.title or f"Invoice {inv.invoice_number}", inv.invoice_type or "",
                           inv.total_amount or ZERO, ZERO))
    # eTIMS numbers ride along per payment event, so the column below can be
    # decided AFTER the rows are built — see the note where `columns` is
    # assembled. Invoice events carry None, never a blank string, so an
    # invoice line can't be mistaken for a payment with a missing number.
    etims_by_event: dict = {}
    for pay in payments:
        desc = pay.payment_method or pay.source or "Payment"
        key = _key(pay.payment_date, pay.created_at, pay.id)
        events.append((key, pay.payment_date,
                       f"Payment {pay.payment_ref}", desc, ZERO, pay.amount or ZERO))
        prop = pay.property
        if (include_etims and prop is not None and prop.etims_shows("statements")
                and pay.etims_invoice_number):
            etims_by_event[key] = pay.etims_invoice_number

    events.sort(key=lambda e: e[0])

    # Opening balance (owed-positive) = charges − payments strictly BEFORE the window.
    opening = ZERO
    for _k, d, _i, _desc, due, paid in events:
        if start is not None and (d is None or d < start):
            opening += (due or ZERO) - (paid or ZERO)

    rows = []
    running = opening
    total_due = ZERO
    total_paid = ZERO
    if opening != ZERO and start is not None:
        rows.append({"date": start, "item": "Opening balance", "description": "Brought forward",
                     "due": ZERO, "paid": ZERO, "running_balance": running})
    any_etims = False
    for _k, d, item, desc, due, paid in events:
        if not _in_range(d, start, end):
            continue
        running += (due or ZERO) - (paid or ZERO)  # owed increases with charges, drops with payments
        total_due += due or ZERO
        total_paid += paid or ZERO
        etims_number = etims_by_event.get(_k)
        any_etims = any_etims or bool(etims_number)
        rows.append(
            {
                "date": d,
                "item": item,
                "description": desc,
                "due": due,
                "paid": paid,
                "running_balance": running,
                "etims_invoice_number": etims_number,
            }
        )

    columns = [
        Column("date", "Transaction date", DATE),
        Column("item", "Item", TEXT),
        Column("description", "Description", TEXT),
        Column("due", "Money due", MONEY),
        Column("paid", "Money paid", MONEY),
        Column("running_balance", "Running balance", MONEY),
    ]
    # The eTIMS column appears only when at least one line in THIS statement
    # actually has a number (spec §3.2). A column of blanks would read as a
    # list of things the landlord failed to do, which is exactly what this
    # feature must never produce — so when nothing was recorded the statement
    # is byte-identical to its pre-feature layout.
    if any_etims:
        columns.append(Column("etims_invoice_number", "eTIMS No.", TEXT))
    section = Section(
        "transactions",
        "Statement of account",
        columns,
        rows,
        totals={"due": total_due, "paid": total_paid},
    )

    unit_name = tenant.unit.name if tenant.unit else "—"
    prop_name = tenant.unit.property.name if tenant.unit and tenant.unit.property else None
    meta = build_meta(
        landlord,
        report_title="Tenant Statement",
        subject=f"{tenant.first_name} {tenant.last_name} — Unit {unit_name}  ·  {tenant.phone}",
        property_name=prop_name,
        period=_period_label(start_date, end_date),
        # #10 — closing balance shown owed-positive (advance negative), matching the
        # running-balance column. Internal tenant.balance is the opposite sign.
        extra={"closing_balance": float(-(tenant.balance or 0))},
    )
    return ReportDocument("tenant_statement", "Tenant Statement", meta, [section])


# ===========================================================================
# 2. Property Statement  (tenants + expenses + occupancy + summary)
# ===========================================================================


def build_property_statement(landlord, property_id: int, start_date: str | None, end_date: str | None,
                            gross_basis: str | None = None,
                            include_etims: bool = False) -> ReportDocument:
    from models import Expense, Invoice, Payment, Property, Tenant, Unit

    prop = Property.query.filter_by(id=property_id, landlord_id=landlord.id).first()
    if prop is None:
        return _not_found("property_statement", "Property Statement", landlord, "Property not found.")

    start, end = parse_date(start_date), parse_date(end_date)
    tax_rate = _effective_tax_rate(None, prop, landlord)

    # ---- Section A: Tenants ------------------------------------------------
    tenant_columns = [
        Column("house_no", "House no.", TEXT),
        Column("name", "Tenant", TEXT),
        Column("phone", "Phone", TEXT),
        Column("balance_cf", "Balance c/f", MONEY),
        Column("advance", "Advance", MONEY),
        Column("rent", "Rent", MONEY),
        Column("water", "Water", MONEY),
        Column("penalties", "Penalties", MONEY),
        Column("garbage", "Garbage", MONEY),
        Column("service_charge", "Service charge", MONEY),
        Column("security", "Security", MONEY),
        Column("deposit_invoice", "Deposit invoiced", MONEY, default=False),
        Column("deposit_held", "Deposit held", MONEY, default=False),
        Column("other_bills", "Other bills", MONEY),
        Column("amount_due", "Amount due", MONEY),
        Column("service_charge_due", "Service charge due", MONEY, default=False),
        Column("amount_paid", "Amount paid", MONEY),
        Column("tax_deducted", "Tax deducted", MONEY, default=False),
        Column("balance", "Balance", MONEY),
        Column("status", "Status", TEXT),
    ]

    tenants = (
        Tenant.query.join(Unit, Unit.id == Tenant.unit_id)
        .filter(Unit.property_id == property_id, Tenant.is_deleted.is_(False))
        .all()
    )

    tenant_rows = []
    tenant_totals: dict[str, Decimal] = {
        k: ZERO for k in ("balance_cf", "advance", "rent", "water", "penalties", "garbage",
                          "service_charge", "security", "deposit_invoice", "deposit_held",
                          "other_bills", "amount_due", "service_charge_due", "amount_paid",
                          "tax_deducted", "balance")
    }
    total_collected = ZERO

    for t in tenants:
        unit = t.unit
        # charges by category (in period)
        cats = {k: ZERO for k in ("rent", "water", "garbage", "service_charge", "security",
                                  "penalties", "deposit", "electricity", "other")}
        # #14 — accuracy: only non-deleted invoices and only CONFIRMED payments count
        # towards the ledger figures (pending/declined submissions must not inflate them).
        live_invoices = [inv for inv in t.invoices if not inv.is_deleted]
        confirmed_payments = [p for p in t.payments
                              if not p.is_deleted and (p.status or "") == "confirmed"
                              and _is_cash_payment(p)]

        amount_due = ZERO          # total invoiced in period (excludes b/f re-presentations)
        for inv in live_invoices:
            if not _in_range(inv.issue_date, start, end):
                continue
            for li in (inv.line_items or []):
                if li.subcategory == _BALANCE_SUB:
                    continue
                cats[_classify_line_item(li.item)] += li.amount or ZERO
            if not inv.line_items:
                cats["rent"] += inv.total_amount or ZERO
            amount_due += _invoice_charge(inv)

        # payments (in period, confirmed cash only)
        amount_paid = ZERO
        for pay in confirmed_payments:
            if _in_range(pay.payment_date, start, end):
                amount_paid += pay.amount or ZERO
        total_collected += amount_paid

        # Balance carried forward = what the tenant OWED entering the period
        # (net of pre-period charges and payments), shown OWED-POSITIVE to match
        # the "Balance" column (a negative here would read as an advance/credit).
        # A first-month tenant with no pre-period activity correctly shows 0.
        # Only computed when a period start is given; over "all time" everything
        # is in-range so there is nothing carried forward.
        balance_cf = ZERO
        if start:
            pre_charges = ZERO
            pre_payments = ZERO
            for inv in live_invoices:
                if inv.issue_date and inv.issue_date < start:
                    pre_charges += _invoice_charge(inv)
            for pay in confirmed_payments:
                if pay.payment_date and pay.payment_date < start:
                    pre_payments += pay.amount or ZERO
            balance_cf = pre_charges - pre_payments   # owed-positive; may be negative (advance)

        # Deposit HELD = refundable deposit money the tenant has actually PAID,
        # from BOTH sources: (a) the onboarding deposit captured on the tenant
        # record (t.deposit_paid — the security/rent deposit taken at move-in),
        # and (b) any deposit-subcategory invoice LINE ITEMS billed later (e.g. a
        # water deposit) that have been paid. An UNPAID deposit line (a kept-unpaid
        # water deposit) contributes nothing to held — only amount_paid counts.
        # Invoiced deposit = onboarding deposit + all deposit lines billed.
        deposit_invoiced_li = ZERO
        deposit_paid_li = ZERO
        for inv in live_invoices:
            for li in (inv.line_items or []):
                if li.subcategory == _DEPOSIT_SUB:
                    deposit_invoiced_li += li.amount or ZERO
                    deposit_paid_li += li.amount_paid or ZERO
        onboarding_deposit_paid = t.deposit_paid or ZERO
        onboarding_deposit_invoiced = t.deposit_amount or ZERO
        deposit_invoiced = onboarding_deposit_invoiced + deposit_invoiced_li
        deposit_held = (onboarding_deposit_paid + deposit_paid_li) - (t.deposit_returned or ZERO)
        rent_charged = cats["rent"]
        tax_deducted = (rent_charged * tax_rate / Decimal(100)).quantize(Decimal("0.01"))
        other_bills = cats["other"] + cats["electricity"]
        # #10 — internal ledger: negative = owed. Display balance owed-positive.
        internal_balance = t.balance or ZERO
        balance = -internal_balance  # owed shows positive, advance shows negative
        status = "In arrears" if internal_balance < 0 else ("Advance/Credit" if internal_balance > 0 else "Settled")

        row = {
            "house_no": unit.name if unit else "—",
            "name": f"{t.first_name} {t.last_name}",
            "phone": t.phone,
            "balance_cf": balance_cf,
            "advance": internal_balance if internal_balance > 0 else ZERO,
            "rent": cats["rent"],
            "water": cats["water"],
            "penalties": cats["penalties"],
            "garbage": cats["garbage"],
            "service_charge": cats["service_charge"],
            "security": cats["security"],
            "deposit_invoice": deposit_invoiced,
            "deposit_held": deposit_held,
            "other_bills": other_bills,
            "amount_due": amount_due,
            "service_charge_due": cats["service_charge"],
            "amount_paid": amount_paid,
            "tax_deducted": tax_deducted,
            "balance": balance,
            "status": status,
        }
        tenant_rows.append(row)
        for k in tenant_totals:
            tenant_totals[k] += row[k] if isinstance(row[k], Decimal) else ZERO

    tenants_section = Section("tenants", "Tenants", tenant_columns, tenant_rows, totals=tenant_totals)

    # ---- Section B: Expenses ----------------------------------------------
    expense_columns = [
        Column("date", "Date", DATE),
        Column("unit", "Unit", TEXT),
        Column("category", "Category", TEXT),
        Column("description", "Description", TEXT),
        Column("amount", "Amount", MONEY),
    ]
    expense_rows = []
    total_expenses = ZERO
    exp_q = Expense.query.filter_by(landlord_id=landlord.id, property_id=property_id)
    for e in exp_q.all():
        if not _in_range(e.expense_date, start, end):
            continue
        expense_rows.append(
            {
                "date": e.expense_date,
                "unit": e.unit.name if e.unit else "—",
                "category": e.category or "—",
                "description": e.notes or "—",
                "amount": e.amount or ZERO,
            }
        )
        total_expenses += e.amount or ZERO
    expense_rows.sort(key=lambda r: r["date"] or date.min)
    expenses_section = Section(
        "expenses", "Expenses", expense_columns, expense_rows, totals={"amount": total_expenses}
    )

    # ---- Section C: Occupancy ---------------------------------------------
    occ_columns = [
        Column("description", "Property", TEXT),
        Column("total_units", "Total units", NUMBER),
        Column("occupied_units", "Occupied", NUMBER),
        Column("unoccupied_units", "Unoccupied", NUMBER),
        Column("occupancy_rate", "Occupancy rate", PERCENT),
    ]
    units = Unit.query.filter_by(property_id=property_id, is_deleted=False).all()
    total_units = len(units)
    occupied = sum(1 for u in units if u.is_occupied)
    unoccupied = total_units - occupied
    occ_rate = round((occupied / total_units) * 100, 1) if total_units else 0
    occupancy_section = Section(
        "occupancy",
        "Occupancy",
        occ_columns,
        [
            {
                "description": prop.name,
                "total_units": total_units,
                "occupied_units": occupied,
                "unoccupied_units": unoccupied,
                "occupancy_rate": occ_rate,
            }
        ],
    )

    # ---- Section D: Summary (net income) ----------------------------------
    # The gross a manager may net against depends on WHO is reading:
    #   "all"       every collection that is income (rent + utilities/other)
    #   "rent_only" rent current + rent arrears alone — the only lawful base for
    #               a Kenyan managing agent's commission
    # Deposits are excluded from both: held, refundable money is never income.
    from services.commission_service import (
        GROSS_BASIS_RENT_ONLY, collections_breakdown, commission_for, gross_for,
        owner_payouts_total, resolve_basis,
    )

    basis = resolve_basis(landlord, gross_basis)
    breakdown = collections_breakdown(landlord.id, prop.id, start, end)
    gross = gross_for(breakdown, basis)
    commission = commission_for(breakdown, prop.commission_rate)
    remitted = owner_payouts_total(landlord.id, prop.id, start, end)

    earnings_before_tax = gross - commission - total_expenses
    total_tax = (earnings_before_tax * tax_rate / Decimal(100)).quantize(Decimal("0.01")) if earnings_before_tax > 0 else ZERO
    net_income = earnings_before_tax - total_tax
    retained = net_income - remitted
    currency = getattr(landlord, "currency", "KES") or "KES"

    def _kv(label, value):
        return {"label": label, "value": float(value), "display": f"{currency} {float(value):,.2f}"}

    gross_label = (
        "Gross — rent collected (current + arrears)"
        if basis == GROSS_BASIS_RENT_ONLY
        else "Total amount collected"
    )
    summary_rows = [_kv(gross_label, gross)]

    if basis == GROSS_BASIS_RENT_ONLY and breakdown["other_collected"] > 0:
        summary_rows.append(
            _kv("Other collections — not commissionable", breakdown["other_collected"])
        )
    if breakdown["deposits_collected"] > 0:
        summary_rows.append(_kv("Deposits held — not income", breakdown["deposits_collected"]))
    if commission > 0:
        summary_rows.append({
            "label": f"Commission ({prop.commission_rate}% of rent collected)",
            "value": float(commission),
            "display": f"{currency} {float(commission):,.2f}",
        })

    summary_rows += [
        _kv("Total expenses", total_expenses),
        _kv("Earnings before tax", earnings_before_tax),
        {"label": f"Total tax deducted ({tax_rate}%)", "value": float(total_tax), "display": f"{currency} {float(total_tax):,.2f}"},
        _kv("Net income", net_income),
    ]
    if remitted > 0:
        summary_rows.append(_kv("Remitted to owner", remitted))
        summary_rows.append(_kv("Retained", retained))

    # The managing agent's OWN eTIMS invoice to the owner, for the commission
    # deducted from the payouts in this window (spec §3.3). Only rendered when
    # the property opted in AND a number was actually recorded — a payout with
    # none contributes nothing, exactly like everywhere else.
    if include_etims and prop.etims_shows("statements"):
        from models import OwnerPayout

        payout_query = OwnerPayout.query.filter(
            OwnerPayout.landlord_id == landlord.id,
            OwnerPayout.property_id == prop.id,
            OwnerPayout.etims_invoice_number.isnot(None),
        )
        if start:
            payout_query = payout_query.filter(OwnerPayout.payout_date >= start)
        if end:
            payout_query = payout_query.filter(OwnerPayout.payout_date <= end)
        for payout in payout_query.order_by(OwnerPayout.payout_date.asc()).all():
            summary_rows.append({
                "label": "Commission eTIMS invoice no.",
                "value": None,
                "display": payout.etims_invoice_number,
            })

    summary_section = Section(
        "summary",
        "Summary",
        [Column("label", "Item", TEXT), Column("value", "Amount", MONEY)],
        summary_rows,
        kind="keyvalue",
    )

    meta = build_meta(
        landlord,
        report_title="Property Statement",
        property_name=prop.name,
        subject=f"{prop.name} — {prop.city}",
        period=_period_label(start_date, end_date),
        # The basis is printed in the letterhead so a PRINTED statement always
        # says which gross it was built on — otherwise two copies of the same
        # month disagree and nobody can tell why.
        extra={
            "tax_rate": float(tax_rate),
            "gross_basis": basis,
            "gross_basis_label": (
                "Rent only (excl. deposits)" if basis == GROSS_BASIS_RENT_ONLY
                else "All collections"
            ),
            "commission_rate": float(prop.commission_rate or 0),
            # Footer PINs (spec §3.2/§3.3). Both keys are omitted entirely
            # rather than set to None when there's nothing to show, so the
            # letterhead renderer has no empty value to lay out.
            **(
                {
                    k: v for k, v in {
                        "owner_kra_pin": prop.effective_kra_pin,
                        "agent_kra_pin": (landlord.user.kra_pin
                                          if landlord.user else None),
                    }.items() if v
                }
                if include_etims and prop.etims_shows("statements") else {}
            ),
        },
    )
    return ReportDocument(
        "property_statement",
        "Property Statement",
        meta,
        [tenants_section, expenses_section, occupancy_section, summary_section],
    )


# ===========================================================================
# 3. Arrears Report
# ===========================================================================


def build_arrears_report(landlord, property_id: int | None, as_of_date: str | None,
                         allowed_property_ids: set[int] | None = None) -> ReportDocument:
    from models import Invoice, Tenant, Unit

    as_of = parse_date(as_of_date) or date.today()
    month_start = as_of.replace(day=1)

    query = Tenant.query.filter(Tenant.landlord_id == landlord.id, Tenant.is_deleted.is_(False), Tenant.balance < 0)
    if property_id or allowed_property_ids is not None:
        query = query.join(Unit, Unit.id == Tenant.unit_id)
    if property_id:
        query = query.filter(Unit.property_id == property_id)
    if allowed_property_ids is not None:
        query = query.filter(Unit.property_id.in_(allowed_property_ids))

    columns = [
        Column("unit", "Unit", TEXT),
        Column("name", "Tenant", TEXT),
        Column("phone", "Phone", TEXT),
        Column("arrears_cf", "Arrears b/f", MONEY),
        Column("current_bills", "Current-month bills", MONEY),
        Column("total_arrears", "Total arrears", MONEY),
        Column("days_in_arrears", "Days in arrears", NUMBER),
    ]

    from sqlalchemy.orm import joinedload, selectinload

    # Each row reads the tenant's unit and walks their invoices — without
    # eager loading that is 2 queries per tenant in arrears, which on a
    # 1,000-tenant estate is the whole report's cost.
    query = query.options(
        joinedload(Tenant.unit),
        selectinload(Tenant.invoices),
    )

    rows = []
    total_arrears_sum = ZERO
    for t in query.order_by(Tenant.balance.asc()).all():
        total_arrears = abs(t.balance or ZERO)
        # Current-month bills vs everything owed before this month.
        current_bills = ZERO
        oldest_unpaid_due = None
        for inv in t.invoices:
            if inv.issue_date and inv.issue_date >= month_start and inv.issue_date <= as_of:
                current_bills += inv.total_amount or ZERO
            if (inv.balance or ZERO) > 0 and inv.due_date:
                if oldest_unpaid_due is None or inv.due_date < oldest_unpaid_due:
                    oldest_unpaid_due = inv.due_date
        arrears_cf = total_arrears - current_bills
        if arrears_cf < 0:
            arrears_cf = ZERO
        days = max((as_of - oldest_unpaid_due).days, 0) if oldest_unpaid_due else 0
        rows.append(
            {
                "unit": t.unit.name if t.unit else "—",
                "name": f"{t.first_name} {t.last_name}",
                "phone": t.phone,
                "arrears_cf": arrears_cf,
                "current_bills": current_bills,
                "total_arrears": total_arrears,
                "days_in_arrears": days,
            }
        )
        total_arrears_sum += total_arrears

    section = Section("arrears", "Tenants in arrears", columns, rows, totals={"total_arrears": total_arrears_sum})
    meta = build_meta(
        landlord,
        report_title="Arrears Report",
        period=f"As of {as_of.isoformat()}",
    )
    return ReportDocument("arrears", "Arrears Report", meta, [section])


# ===========================================================================
# 4. Expenses Report
# ===========================================================================


def build_expenses_report(landlord, property_id: int | None, start_date: str | None, end_date: str | None,
                          allowed_property_ids: set[int] | None = None) -> ReportDocument:
    from models import Expense

    start, end = parse_date(start_date), parse_date(end_date)
    query = Expense.query.filter_by(landlord_id=landlord.id)
    if property_id:
        query = query.filter(Expense.property_id == property_id)
    if allowed_property_ids is not None:
        query = query.filter(Expense.property_id.in_(allowed_property_ids))

    columns = [
        Column("date", "Date", DATE),
        Column("property", "Property", TEXT),
        Column("unit", "Unit", TEXT),
        Column("category", "Category", TEXT),
        Column("description", "Description", TEXT),
        Column("amount", "Amount", MONEY),
    ]
    rows = []
    total = ZERO
    for e in query.all():
        if not _in_range(e.expense_date, start, end):
            continue
        rows.append(
            {
                "date": e.expense_date,
                "property": e.property.name if e.property else "—",
                "unit": e.unit.name if e.unit else "—",
                "category": e.category or "—",
                "description": e.notes or "—",
                "amount": e.amount or ZERO,
            }
        )
        total += e.amount or ZERO
    rows.sort(key=lambda r: r["date"] or date.min)

    section = Section("expenses", "Expenses", columns, rows, totals={"amount": total})
    meta = build_meta(landlord, report_title="Expenses Report", period=_period_label(start_date, end_date))
    return ReportDocument("expenses", "Expenses Report", meta, [section])


# ===========================================================================
# 5. Deleted (archived) Tenants Report
# ===========================================================================


def build_deleted_tenants_report(landlord, property_id: int | None,
                                 allowed_property_ids: set[int] | None = None) -> ReportDocument:
    from extensions import db
    from models import Tenant, Unit

    query = (
        db.session.query(Tenant)
        .execution_options(include_deleted=True)
        .filter(Tenant.landlord_id == landlord.id, Tenant.is_deleted.is_(True))
    )
    if property_id or allowed_property_ids is not None:
        query = query.join(Unit, Unit.id == Tenant.unit_id)
    if property_id:
        query = query.filter(Unit.property_id == property_id)
    if allowed_property_ids is not None:
        query = query.filter(Unit.property_id.in_(allowed_property_ids))

    columns = [
        Column("unit", "Unit", TEXT),
        Column("name", "Tenant", TEXT),
        Column("phone", "Phone", TEXT),
        Column("move_in", "Move-in date", DATE),
        Column("move_out", "Move-out date", DATE),
        Column("deleted_on", "Date deleted", DATE),
        Column("balance", "Balance left", MONEY),
        Column("deposit_invoice", "Deposit invoiced", MONEY),
        Column("deposit_refunded", "Deposit refunded", MONEY),
        Column("notes", "Notes", TEXT),
    ]
    rows = []
    for t in query.all():
        rows.append(
            {
                "unit": t.unit.name if t.unit else "—",
                "name": f"{t.first_name} {t.last_name}",
                "phone": t.phone,
                "move_in": t.move_in_date,
                "move_out": t.move_out_date,
                "deleted_on": t.deleted_at.date() if t.deleted_at else None,
                "balance": t.balance or ZERO,
                "deposit_invoice": t.deposit_amount or ZERO,
                "deposit_refunded": t.deposit_returned or ZERO,
                "notes": t.notes or "—",
            }
        )
    section = Section("deleted", "Archived tenants", columns, rows)
    meta = build_meta(landlord, report_title="Deleted Tenants Report")
    return ReportDocument("deleted_tenants", "Deleted Tenants Report", meta, [section])


# ===========================================================================
# 6/7. Comparative reports — Month-on-Month & Year-on-Year
# ===========================================================================

# Metric columns shared by MoM, YoY and the Grouping report.
_COMPARATIVE_METRICS = [
    ("occupancy", "Occupancy", PERCENT),
    ("carried_forward", "Carried forward", MONEY),
    ("total_rent", "Total rent", MONEY),
    ("total_water", "Total water", MONEY),
    ("deposit_withheld", "Deposit withheld", MONEY),
    ("other_bills", "Other bills", MONEY),
    ("total_bills", "Total bills", MONEY),
    ("total_paid", "Total paid", MONEY),
    ("percentage_paid", "% paid", PERCENT),
    ("total_expense", "Total expense", MONEY),
]


def _bucket_bounds(key: str, period: str) -> tuple[date, date]:
    if period == "month":
        y, m = int(key[:4]), int(key[5:7])
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    else:
        y = int(key)
        start, end = date(y, 1, 1), date(y, 12, 31)
    return start, end


def _window_metrics(invoices, payments, expenses, units, histories, start, end, total_units) -> dict:
    """Compute the comparative metric set for a [start, end] window."""
    cats = {k: ZERO for k in ("rent", "water", "garbage", "service_charge", "security",
                              "penalties", "deposit", "electricity", "other")}
    total_bills = ZERO
    carried_forward = ZERO  # net owed BEFORE the window opened
    for inv in invoices:
        d = inv.issue_date
        if d and d < start:
            carried_forward += _invoice_charge(inv)
        if _in_range(d, start, end):
            for li in (inv.line_items or []):
                if li.subcategory == _BALANCE_SUB:
                    continue
                cats[_classify_line_item(li.item)] += li.amount or ZERO
            if not inv.line_items:
                cats["rent"] += inv.total_amount or ZERO
            total_bills += _invoice_charge(inv)

    total_paid = ZERO
    for pay in payments:
        if not _is_cash_payment(pay):
            continue
        if pay.payment_date and pay.payment_date < start:
            carried_forward -= pay.amount or ZERO
        if _in_range(pay.payment_date, start, end):
            total_paid += pay.amount or ZERO
    if carried_forward < 0:
        carried_forward = ZERO

    total_expense = sum((e.amount or ZERO for e in expenses if _in_range(e.expense_date, start, end)), ZERO)

    # deposits collected from tenants who moved in during the window
    deposit_withheld = ZERO
    for u in units:
        for t in getattr(u, "tenants", []):
            if t.move_in_date and _in_range(t.move_in_date, start, end):
                deposit_withheld += (t.deposit_paid or ZERO) - (t.deposit_returned or ZERO)

    # occupancy: units with a tenancy overlapping the window / total units
    occupied_units = set()
    for h in histories:
        mi, mo = h.moved_in_at, h.moved_out_at
        if mi and mi <= end and (mo is None or mo >= start):
            occupied_units.add(h.unit_id)
    occupancy = round((len(occupied_units) / total_units) * 100, 1) if total_units else 0

    other_bills = cats["garbage"] + cats["service_charge"] + cats["security"] + cats["penalties"] + cats["electricity"] + cats["other"]
    pct_paid = round(float(total_paid) / float(total_bills) * 100, 1) if total_bills else 0
    return {
        "occupancy": occupancy,
        "carried_forward": carried_forward,
        "total_rent": cats["rent"],
        "total_water": cats["water"],
        "deposit_withheld": deposit_withheld,
        "other_bills": other_bills,
        "total_bills": total_bills,
        "total_paid": total_paid,
        "percentage_paid": pct_paid,
        "total_expense": total_expense,
    }


def _load_comparative_data(landlord, property_id, allowed_property_ids=None):
    from models import Expense, Invoice, Payment, Property, TenantUnitHistory, Unit

    inv_q = Invoice.query.filter_by(landlord_id=landlord.id)
    pay_q = Payment.query.filter_by(landlord_id=landlord.id)
    exp_q = Expense.query.filter_by(landlord_id=landlord.id)
    unit_q = Unit.query.join(Property, Property.id == Unit.property_id).filter(
        Property.landlord_id == landlord.id, Unit.is_deleted.is_(False)
    )
    if property_id:
        inv_q = inv_q.filter(Invoice.property_id == property_id)
        pay_q = pay_q.filter(Payment.property_id == property_id)
        exp_q = exp_q.filter(Expense.property_id == property_id)
        unit_q = unit_q.filter(Unit.property_id == property_id)
    # A team member restricted to certain properties gets figures built ONLY
    # from those properties — including when they ask for "all", which for them
    # means all they may see.
    if allowed_property_ids is not None:
        inv_q = inv_q.filter(Invoice.property_id.in_(allowed_property_ids))
        pay_q = pay_q.filter(Payment.property_id.in_(allowed_property_ids))
        exp_q = exp_q.filter(Expense.property_id.in_(allowed_property_ids))
        unit_q = unit_q.filter(Unit.property_id.in_(allowed_property_ids))

    invoices, payments, expenses, units = inv_q.all(), pay_q.all(), exp_q.all(), unit_q.all()
    unit_ids = {u.id for u in units}
    histories = [h for h in TenantUnitHistory.query.all() if h.unit_id in unit_ids]
    return invoices, payments, expenses, units, histories


def _comparative(landlord, property_id, year, period: str,
                 allowed_property_ids: set[int] | None = None,
                 gross_basis: str | None = None) -> ReportDocument:
    invoices, payments, expenses, units, histories = _load_comparative_data(
        landlord, property_id, allowed_property_ids)
    total_units = len(units)

    # discover buckets from invoice + payment dates
    keys = set()
    fmt = "%Y-%m" if period == "month" else "%Y"
    for inv in invoices:
        if inv.issue_date and (year is None or inv.issue_date.year == year or period == "year"):
            keys.add(inv.issue_date.strftime(fmt))
    for pay in payments:
        if pay.payment_date and (year is None or pay.payment_date.year == year or period == "year"):
            keys.add(pay.payment_date.strftime(fmt))
    buckets = sorted(keys)

    from services.commission_service import (
        GROSS_BASIS_RENT_ONLY, collections_breakdown, resolve_basis,
    )

    basis = resolve_basis(landlord, gross_basis)
    rent_only = basis == GROSS_BASIS_RENT_ONLY

    # On the rent-only basis "Total paid" must mean rent collected, not every
    # shilling banked — otherwise the column a manager reads their commission
    # off silently includes deposits and utilities they may not charge on.
    metrics = list(_COMPARATIVE_METRICS)
    if rent_only:
        metrics = [
            (k, "Rent collected" if k == "total_paid" else label, kind)
            for k, label, kind in metrics
        ]

    columns = [Column("period", "Period", TEXT)] + [Column(k, label, kind) for k, label, kind in metrics]
    rows = []
    for key in buckets:
        start, end = _bucket_bounds(key, period)
        m = _window_metrics(invoices, payments, expenses, units, histories, start, end, total_units)
        if rent_only:
            # One extra query per bucket (12 at most) — the allocation rows are
            # the only place that knows which charge a payment actually paid.
            breakdown = collections_breakdown(
                landlord.id, property_id, start, end, allowed_property_ids,
            )
            m["total_paid"] = breakdown["rent_collected"]
            m["percentage_paid"] = (
                round(float(m["total_paid"]) / float(m["total_bills"]) * 100, 1)
                if m["total_bills"] else 0
            )
        rows.append({"period": key, **m})

    charts = [
        {"key": k, "title": label, "type": "bar", "x": "period", "y": k}
        for k, label, _ in metrics
    ]
    section = Section(
        "comparative",
        "Month-on-Month" if period == "month" else "Year-on-Year",
        columns,
        rows,
        charts=charts,
        note="Add any metric's graph to the download using the chart toggles.",
    )
    title = "Month-on-Month Report" if period == "month" else "Year-on-Year Report"
    meta = build_meta(
        landlord, report_title=title,
        period=(f"Year {year}" if (period == "month" and year) else "All periods"),
        extra={
            "gross_basis": basis,
            "gross_basis_label": (
                "Rent only (excl. deposits)" if rent_only else "All collections"
            ),
        },
    )
    return ReportDocument("month_on_month" if period == "month" else "year_on_year", title, meta, [section])


def build_mom_report(landlord, property_id: int | None, year: int | None,
                     allowed_property_ids: set[int] | None = None,
                     gross_basis: str | None = None) -> ReportDocument:
    return _comparative(landlord, property_id, year, "month", allowed_property_ids, gross_basis)


def build_yoy_report(landlord, property_id: int | None,
                     allowed_property_ids: set[int] | None = None,
                     gross_basis: str | None = None) -> ReportDocument:
    return _comparative(landlord, property_id, None, "year", allowed_property_ids, gross_basis)


# ===========================================================================
# 8. Property Grouping Report
# ===========================================================================


def build_grouping_report(landlord, group_id: int, start_date: str | None, end_date: str | None) -> ReportDocument:
    from models import Property, PropertyGroup, TenantUnitHistory, Unit

    group = PropertyGroup.query.filter_by(id=group_id, landlord_id=landlord.id).first()
    if group is None:
        return _not_found("grouping", "Property Grouping Report", landlord, "Property group not found.")

    start = parse_date(start_date) or date(1970, 1, 1)
    end = parse_date(end_date) or date.today()

    columns = [Column("property", "Property", TEXT)] + [Column(k, label, kind) for k, label, kind in _COMPARATIVE_METRICS]
    rows = []
    group_totals = {k: ZERO for k, _, kind in _COMPARATIVE_METRICS if kind == MONEY}
    for prop in group.properties:
        invoices, payments, expenses, units, histories = _load_comparative_data(landlord, prop.id)
        m = _window_metrics(invoices, payments, expenses, units, histories, start, end, len(units))
        rows.append({"property": prop.name, **m})
        for k in group_totals:
            group_totals[k] += m[k] if isinstance(m[k], Decimal) else ZERO

    charts = [
        {"key": "total_paid", "title": "Total paid by property", "type": "bar", "x": "property", "y": "total_paid"},
        {"key": "occupancy", "title": "Occupancy by property", "type": "bar", "x": "property", "y": "occupancy"},
        {"key": "total_bills", "title": "Total bills by property", "type": "bar", "x": "property", "y": "total_bills"},
        {"key": "total_expense", "title": "Total expense by property", "type": "bar", "x": "property", "y": "total_expense"},
    ]
    section = Section(
        "grouping",
        f"Group: {group.name}",
        columns,
        rows,
        totals=group_totals,
        charts=charts,
        note="Each property in the group compared across the same metrics.",
    )
    meta = build_meta(landlord, report_title="Property Grouping Report", subject=f"Group: {group.name}",
                      period=_period_label(start_date, end_date))
    return ReportDocument("grouping", "Property Grouping Report", meta, [section])
