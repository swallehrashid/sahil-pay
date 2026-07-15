"""
services/payment_report_service.py — the Payments Report (charge-category restructure §5.5).

Per (category, tenant): consolidates what was invoiced/collected against each of the
category's three subcategories over a date range.

Columns per tenant, per category:
  deposit_invoiced   — deposit lines issued in range
  deposit_paid       — allocations to deposit lines, by payment date, in range
  deposit_balance    — deposit still outstanding (to date; deposits never roll)
  deposit_held       — deposit collected all-time (money currently held)
  balance_collected  — allocations to the balance subcategory in range
  current_collected  — allocations to the current subcategory in range
  total_collected    — balance + current  (deposits DELIBERATELY excluded)

"Collected" counts every confirmed allocation, including credit re-applications
(source='credit') — the report measures what cleared each subcategory, not new cash.
"""

from __future__ import annotations

from decimal import Decimal

from extensions import db
from models import (
    ChargeCategory, Invoice, InvoiceLineItem, LineItemStatus, Payment,
    PaymentAllocation, PaymentStatus, SubCategory, Tenant,
)

Z = Decimal("0")


def _in_range(d, date_from, date_to) -> bool:
    if d is None:
        return False
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _tenant_ids_in_scope(landlord_id, property_id):
    q = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False)
    if property_id:
        from models import Unit
        q = q.join(Unit, Unit.id == Tenant.unit_id).filter(Unit.property_id == property_id)
    return {t.id: t for t in q.all()}


def build_payments_report(landlord_id, category_id="all", date_from=None, date_to=None,
                          property_id=None) -> dict:
    tenants = _tenant_ids_in_scope(landlord_id, property_id)
    tenant_ids = set(tenants.keys())

    cat_q = ChargeCategory.query.filter_by(landlord_id=landlord_id)
    if category_id not in (None, "all"):
        cat_q = cat_q.filter_by(id=int(category_id))
    else:
        cat_q = cat_q.filter_by(is_active=True)
    categories = cat_q.order_by(ChargeCategory.is_default.desc(), ChargeCategory.name.asc()).all()
    cat_ids = [c.id for c in categories]
    if not cat_ids or not tenant_ids:
        return {"categories": [], "grand_total": _empty_totals(),
                "date_from": _iso(date_from), "date_to": _iso(date_to)}

    # ---- Line items (with owning invoice's tenant + issue date) ----
    line_rows = (
        db.session.query(
            InvoiceLineItem.id, InvoiceLineItem.category_id, InvoiceLineItem.subcategory,
            InvoiceLineItem.amount, InvoiceLineItem.amount_paid, InvoiceLineItem.status,
            Invoice.tenant_id, Invoice.issue_date,
        )
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(Invoice.landlord_id == landlord_id, Invoice.is_deleted.is_(False),
                InvoiceLineItem.category_id.in_(cat_ids),
                Invoice.tenant_id.in_(tenant_ids))
        .all()
    )
    # line_id -> (tenant_id, category_id, subcategory)
    line_meta: dict[int, tuple] = {}

    # acc[(tenant_id, category_id)] = metrics dict
    acc: dict[tuple, dict] = {}

    def bucket(tid, cid):
        return acc.setdefault((tid, cid), _empty_row())

    for (lid, cid, sub, amount, paid, status, tid, issue) in line_rows:
        line_meta[lid] = (tid, cid, sub)
        amount = amount or Z
        paid = paid or Z
        row = bucket(tid, cid)
        if sub == SubCategory.deposit.value:
            if _in_range(issue, date_from, date_to):
                row["deposit_invoiced"] += amount
            if status != LineItemStatus.rolled.value:
                row["deposit_balance"] += (amount - paid)

    # ---- Allocations (confirmed payments) ----
    alloc_rows = (
        db.session.query(PaymentAllocation.line_item_id, PaymentAllocation.amount_allocated,
                         Payment.payment_date)
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .filter(Payment.landlord_id == landlord_id, Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
                PaymentAllocation.line_item_id.in_(line_meta.keys()))
        .all()
    )
    for (lid, amt, pay_date) in alloc_rows:
        meta = line_meta.get(lid)
        if meta is None:
            continue
        tid, cid, sub = meta
        amt = amt or Z
        row = bucket(tid, cid)
        if sub == SubCategory.deposit.value:
            row["deposit_held"] += amt
            if _in_range(pay_date, date_from, date_to):
                row["deposit_paid"] += amt
        elif sub == SubCategory.balance.value and _in_range(pay_date, date_from, date_to):
            row["balance_collected"] += amt
        elif sub == SubCategory.current.value and _in_range(pay_date, date_from, date_to):
            row["current_collected"] += amt

    # ---- Assemble per-category sections ----
    sections = []
    grand = _empty_totals()
    for cat in categories:
        rows = []
        totals = _empty_totals()
        for tid, tenant in tenants.items():
            row = acc.get((tid, cat.id))
            if not row or _row_is_empty(row):
                continue
            total_collected = row["balance_collected"] + row["current_collected"]
            entry = {
                "tenant_id":         tid,
                "tenant_name":       f"{tenant.first_name} {tenant.last_name}".strip(),
                "deposit_invoiced":  _f(row["deposit_invoiced"]),
                "deposit_paid":      _f(row["deposit_paid"]),
                "deposit_balance":   _f(row["deposit_balance"]),
                "deposit_held":      _f(row["deposit_held"]),
                "balance_collected": _f(row["balance_collected"]),
                "current_collected": _f(row["current_collected"]),
                "total_collected":   _f(total_collected),
            }
            rows.append(entry)
            for k in totals:
                totals[k] += entry[k]
        rows.sort(key=lambda r: r["tenant_name"].lower())
        sections.append({
            "category_id":   cat.id,
            "category_name": cat.name,
            "kind":          cat.kind,
            "rows":          rows,
            "totals":        {k: round(v, 2) for k, v in totals.items()},
        })
        for k in grand:
            grand[k] += totals[k]

    return {
        "categories":  sections,
        "grand_total": {k: round(v, 2) for k, v in grand.items()},
        "date_from":   _iso(date_from),
        "date_to":     _iso(date_to),
    }


def build_payments_report_document(landlord, category_id="all", date_from=None,
                                   date_to=None, property_id=None):
    """Wrap build_payments_report as a ReportDocument for PDF/Excel export (spec §4.4)."""
    from services.report_builder import Column, Section, ReportDocument, build_meta, TEXT, MONEY

    data = build_payments_report(landlord.id, category_id, date_from, date_to, property_id)
    columns = [
        Column("tenant_name", "Tenant", TEXT),
        Column("deposit_invoiced", "Deposit invoiced", MONEY),
        Column("deposit_paid", "Deposit paid", MONEY),
        Column("deposit_balance", "Deposit balance", MONEY),
        Column("deposit_held", "Deposit held", MONEY),
        Column("balance_collected", "Balance collected", MONEY),
        Column("current_collected", "Current collected", MONEY),
        Column("total_collected", "Total collected", MONEY),
    ]
    total_keys = [c.key for c in columns if c.key != "tenant_name"]

    sections = []
    for sec in data["categories"]:
        rows = [{**r} for r in sec["rows"]]
        sections.append(Section(
            key=f"cat_{sec['category_id']}",
            title=f"{sec['category_name']} ({sec['kind']})",
            columns=columns,
            rows=rows,
            totals={k: sec["totals"].get(k, 0) for k in total_keys},
        ))
    if category_id in (None, "all") and data.get("grand_total"):
        sections.append(Section(
            key="grand_total",
            title="All categories — grand total",
            columns=columns,
            rows=[{"tenant_name": "Everything", **{k: data["grand_total"].get(k, 0) for k in total_keys}}],
            totals={},
            note="Total collected excludes deposits (held money).",
        ))

    def _period():
        if data["date_from"] or data["date_to"]:
            return f"{data['date_from'] or '…'} to {data['date_to'] or '…'}"
        return None

    meta = build_meta(landlord, report_title="Payments Report", period=_period())
    return ReportDocument("payments_report", "Payments Report", meta, sections)


def rollover_trail(line_item_id, landlord_id) -> dict:
    """
    The provenance of a balance line: its BalanceRollover components with each origin
    month and how much of it is still owed (line.amount_paid consumed OLDEST-first).
    """
    from models import BalanceRollover

    li = (
        InvoiceLineItem.query
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(InvoiceLineItem.id == line_item_id, Invoice.landlord_id == landlord_id)
        .first()
    )
    if li is None:
        return {"error": "not_found"}

    comps = (
        BalanceRollover.query
        .filter_by(target_line_item_id=li.id)
        .order_by(BalanceRollover.origin_month.asc(), BalanceRollover.id.asc())
        .all()
    )
    paid = li.amount_paid or Z
    trail = []
    for c in comps:
        amt = c.amount or Z
        if paid >= amt:
            remaining = Z
            paid -= amt
        else:
            remaining = amt - paid
            paid = Z
        trail.append({
            "origin_month": c.origin_month.isoformat() if c.origin_month else None,
            "amount":       _f(amt),
            "remaining":    _f(remaining),
        })

    return {
        "line_item_id": li.id,
        "item":         li.item,
        "amount":       _f(li.amount or Z),
        "amount_paid":  _f(li.amount_paid or Z),
        "remaining":    _f(li.remaining),
        "components":   trail,
    }


# --- helpers --------------------------------------------------------------

_METRIC_KEYS = ("deposit_invoiced", "deposit_paid", "deposit_balance", "deposit_held",
                "balance_collected", "current_collected", "total_collected")


def _empty_row():
    return {k: Z for k in _METRIC_KEYS}


def _empty_totals():
    return {k: 0.0 for k in _METRIC_KEYS}


def _row_is_empty(row) -> bool:
    return all((row[k] or Z) == Z for k in row)


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _iso(d):
    return d.isoformat() if d else None
