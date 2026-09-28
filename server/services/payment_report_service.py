"""
services/payment_report_service.py — the Payments Report.

WHAT A MANAGER HAS TO BE ABLE TO ANSWER FROM IT
-----------------------------------------------
  * For each charge (Rent, Water, Security, Penalty, deposits…): how much was
    billed, how much was collected, and how much is still owed — in figures,
    never "see statement".
  * For each MONTH a charge was for: the same three numbers. "Rent for August"
    is a different thing from "rent collected in August", and the report keeps
    them apart.
  * For every shilling collected: which payment (receipt no., M-Pesa code,
    date) cleared which invoice line, for which month. Any payment on a
    receipt can be found here, and it is the same line, the same month and the
    same amount as the receipt (both come from services/line_period.py).
  * That the money adds up: cash received = allocated to charges + held as
    advance credit.

IT IS NEVER STALE
-----------------
Everything is computed from the ledger at request time — invoices, lines,
allocations, credit. There is no cached copy to fall behind: a payment
allocated a second ago is in the next load of the page.

Definitions
  invoiced     current + deposit lines, by the month they are FOR. Balance-b/f
               lines are carried debt, not new charges, and are never counted
               as invoiced (that would bill the same rent twice).
  collected    confirmed allocations whose PAYMENT DATE is in the range, split
               into current / arrears (balance) / deposit. Credit re-applications
               count here (they are what cleared the line) and are marked as such
               in the ledger.
  outstanding  what is still owed on live lines NOW, by the month it is for
               (a rolled line's debt is on its balance-b/f line; counted once).
  total_collected = balance + current. Deposits are held money, reported apart.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from extensions import db
from models import (
    BalanceRollover, ChargeCategory, CreditLedger, Invoice, InvoiceLineItem, InvoiceStatus,
    LineItemStatus, Payment, PaymentAllocation, PaymentSource, PaymentStatus, Property,
    SubCategory, Tenant, Unit, UtilityReading,
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


def _month_in_range(m, date_from, date_to) -> bool:
    """A month is in range when any day of it is."""
    if m is None:
        return date_from is None and date_to is None
    nxt = date(m.year + (m.month // 12), m.month % 12 + 1, 1)
    if date_from and nxt <= date_from:
        return False
    if date_to and m > date_to:
        return False
    return True


def _first(d):
    return date(d.year, d.month, 1) if d else None


def _month_label(m) -> str:
    return m.strftime("%B %Y") if m else "No month (one-off)"


def _scope(landlord_id, property_id=None, allowed_property_ids=None):
    """Tenants (incl. moved-out/deleted, whose history still counts) with unit + property."""
    q = (db.session.query(Tenant, Unit, Property)
         .join(Unit, Unit.id == Tenant.unit_id)
         .join(Property, Property.id == Unit.property_id)
         .filter(Tenant.landlord_id == landlord_id))
    if property_id:
        q = q.filter(Property.id == property_id)
    if allowed_property_ids is not None:
        q = q.filter(Property.id.in_(list(allowed_property_ids) or [-1]))
    return {t.id: {"tenant": t, "unit": u, "property": p} for t, u, p in q.all()}


def _load(landlord_id, tenant_ids, cat_ids):
    """Lines, their categories' rollover trails, reading months and allocations — in five queries."""
    lines = (
        db.session.query(InvoiceLineItem, Invoice)
        .join(Invoice, InvoiceLineItem.invoice_id == Invoice.id)
        .filter(Invoice.landlord_id == landlord_id, Invoice.is_deleted.is_(False),
                Invoice.status != InvoiceStatus.void.value,
                Invoice.tenant_id.in_(tenant_ids),
                InvoiceLineItem.category_id.in_(cat_ids))
        .all()
    )
    line_ids = [li.id for li, _ in lines]
    trails = defaultdict(list)
    rolled = set()
    reading_month = {}
    if line_ids:
        for r in (BalanceRollover.query
                  .filter(BalanceRollover.target_line_item_id.in_(line_ids))
                  .order_by(BalanceRollover.origin_month, BalanceRollover.id).all()):
            trails[r.target_line_item_id].append((_first(r.origin_month), Decimal(r.amount or 0)))
        rolled = {sid for (sid,) in db.session.query(BalanceRollover.source_line_item_id)
                  .filter(BalanceRollover.source_line_item_id.in_(line_ids)).all()}
        reading_ids = [li.utility_reading_id for li, _ in lines if li.utility_reading_id]
        if reading_ids:
            for rid, rm in (db.session.query(UtilityReading.id, UtilityReading.reading_month)
                            .filter(UtilityReading.id.in_(reading_ids)).all()):
                try:
                    reading_month[rid] = date(int(rm[:4]), int(rm[5:7]), 1)
                except (TypeError, ValueError):
                    pass
    allocs = (
        db.session.query(PaymentAllocation, Payment)
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .filter(Payment.landlord_id == landlord_id, Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
                PaymentAllocation.line_item_id.in_(line_ids or [-1]))
        .order_by(PaymentAllocation.id)
        .all()
    )
    return lines, trails, rolled, reading_month, allocs


def build_payments_report(landlord_id, category_id="all", date_from=None, date_to=None,
                          property_id=None, allowed_property_ids=None,
                          ledger_page: int | None = None, ledger_per_page: int = 100) -> dict:
    scope = _scope(landlord_id, property_id, allowed_property_ids)
    tenant_ids = list(scope.keys())

    cat_q = ChargeCategory.query.filter_by(landlord_id=landlord_id)
    if category_id not in (None, "all", ""):
        cat_q = cat_q.filter_by(id=int(category_id))
    categories = cat_q.order_by(ChargeCategory.is_default.desc(), ChargeCategory.name.asc()).all()
    cats = {c.id: c for c in categories}
    empty = {"categories": [], "grand_total": _empty_totals(), "by_month": [], "summary": [],
             "ledger": [], "ledger_total": 0, "reconciliation": _empty_recon(),
             "date_from": _iso(date_from), "date_to": _iso(date_to)}
    if not cats or not tenant_ids:
        return empty

    lines, trails, rolled, reading_month, allocs = _load(landlord_id, tenant_ids, list(cats))

    undated_cats = {cid for cid, c in cats.items()
                    if (c.name or "").strip().lower() in ("lease agreement", "lease", "lease fee",
                                                          "agreement fee")}

    def line_month(li, inv):
        # Same rule as services/line_period.is_undated, without a query per line.
        if li.category_id in undated_cats or "lease agreement" in (li.item or "").lower():
            return None
        if li.period_month:
            return _first(li.period_month)
        if li.utility_reading_id and li.utility_reading_id in reading_month:
            return reading_month[li.utility_reading_id]
        return _first(inv.issue_date)

    def components(li, inv):
        if li.subcategory == SubCategory.balance.value and trails.get(li.id):
            comps = list(trails[li.id])
            gap = Decimal(li.amount or 0) - sum((a for _, a in comps), Z)
            if gap > 0:
                comps[-1] = (comps[-1][0], comps[-1][1] + gap)
            return comps
        return [(line_month(li, inv), Decimal(li.amount or 0))]

    def slice_(comps, skip, take):
        out = []
        for m, size in comps:
            if take <= 0:
                break
            if skip >= size:
                skip -= size
                continue
            room = size - skip
            skip = Z
            part = min(room, take)
            out.append((m, part))
            take -= part
        if take > 0:
            out.append((comps[-1][0] if comps else None, take))
        return out

    line_info = {li.id: (li, inv) for li, inv in lines}

    # acc[(tenant, cat)] and by_month[(month, cat)]
    acc = defaultdict(_empty_row)
    by_month = defaultdict(lambda: {"invoiced": Z, "collected": Z, "outstanding": Z})

    for li, inv in lines:
        tid, cid, sub = inv.tenant_id, li.category_id, li.subcategory
        row = acc[(tid, cid)]
        m = line_month(li, inv)
        amount = Decimal(li.amount or 0)
        if sub in (SubCategory.current.value, SubCategory.deposit.value, None):
            if _month_in_range(m, date_from, date_to) or (m is None and _in_range(inv.issue_date, date_from, date_to)):
                key = "deposit_invoiced" if sub == SubCategory.deposit.value else "invoiced"
                row[key] += amount
                by_month[(m, cid)]["invoiced"] += amount
        # Outstanding now: live lines only; a rolled line's debt lives on its b/f line.
        if li.status != LineItemStatus.rolled.value and li.id not in rolled:
            remaining = amount - Decimal(li.amount_paid or 0)
            if remaining > 0:
                if sub == SubCategory.deposit.value:
                    row["deposit_balance"] += remaining
                else:
                    row["outstanding"] += remaining
                    for om, part in slice_(components(li, inv), Decimal(li.amount_paid or 0), remaining):
                        by_month[(om, cid)]["outstanding"] += part

    # Allocations, replayed per line in id order so each lands on the right month.
    paid_so_far = defaultdict(lambda: Z)
    ledger = []
    for a, pay in allocs:
        info = line_info.get(a.line_item_id)
        if info is None:
            continue
        li, inv = info
        amt = Decimal(a.amount_allocated or 0)
        offset = paid_so_far[li.id]
        paid_so_far[li.id] = offset + amt
        if amt <= 0:
            continue
        tid, cid, sub = inv.tenant_id, li.category_id, li.subcategory
        row = acc[(tid, cid)]
        if sub == SubCategory.deposit.value:
            row["deposit_held"] += amt
        if not _in_range(pay.payment_date, date_from, date_to):
            continue
        if sub == SubCategory.deposit.value:
            row["deposit_paid"] += amt
        elif sub == SubCategory.balance.value:
            row["balance_collected"] += amt
        else:
            row["current_collected"] += amt
        ctx = scope.get(tid)
        for om, part in slice_(components(li, inv), offset, amt):
            if sub != SubCategory.deposit.value:
                by_month[(om, cid)]["collected"] += part
            ledger.append({
                "payment_date":   pay.payment_date.isoformat() if pay.payment_date else None,
                "receipt_no":     pay.payment_ref,
                "mpesa_ref":      pay.mpesa_reference or "",
                "source":         "Credit applied" if pay.source == PaymentSource.credit.value
                                  else (pay.payment_method or pay.source or "").replace("_", " "),
                "tenant_name":    f"{ctx['tenant'].first_name} {ctx['tenant'].last_name}".strip() if ctx else "",
                "account_number": (ctx["tenant"].account_number or "") if ctx else "",
                "property_name":  ctx["property"].name if ctx else "",
                "unit_name":      ctx["unit"].name if ctx else "",
                "invoice_number": inv.invoice_number,
                "category":       cats[cid].name if cid in cats else "",
                "type":           {"current": "Current", "balance": "Arrears (b/f)",
                                   "deposit": "Deposit"}.get(sub or "current", sub),
                "month_for":      om.isoformat() if om else None,
                "month_label":    _month_label(om) if om else "One-off",
                "amount":         float(part),
            })

    # ---- per-category sections, per tenant ----
    sections, grand = [], _empty_totals()
    for cat in categories:
        rows, totals = [], _empty_totals()
        for tid, ctx in scope.items():
            row = acc.get((tid, cat.id))
            if not row or _row_is_empty(row):
                continue
            t = ctx["tenant"]
            entry = {
                "tenant_id":         tid,
                "tenant_name":       f"{t.first_name} {t.last_name}".strip(),
                "account_number":    t.account_number or "",
                "property_name":     ctx["property"].name,
                "unit_name":         ctx["unit"].name,
                **{k: _f(row[k]) for k in _METRIC_KEYS if k != "total_collected"},
                "total_collected":   _f(row["balance_collected"] + row["current_collected"]),
            }
            rows.append(entry)
            for k in totals:
                totals[k] += entry[k]
        rows.sort(key=lambda r: (r["property_name"].lower(), r["unit_name"].lower(), r["tenant_name"].lower()))
        sections.append({"category_id": cat.id, "category_name": cat.name, "kind": cat.kind,
                         "rows": rows, "totals": {k: round(v, 2) for k, v in totals.items()}})
        for k in grand:
            grand[k] += totals[k]

    summary = [{"category_id": s["category_id"], "category_name": s["category_name"],
                "kind": s["kind"], **s["totals"]} for s in sections]

    month_rows = []
    for (m, cid), v in by_month.items():
        if cid not in cats:
            continue
        if not (_month_in_range(m, date_from, date_to) or v["collected"] or v["outstanding"]):
            continue
        month_rows.append({
            "month": m.isoformat() if m else None, "month_label": _month_label(m) if m else "One-off",
            "category_name": cats[cid].name,
            "invoiced": _f(v["invoiced"]), "collected": _f(v["collected"]),
            "outstanding": _f(v["outstanding"]),
        })
    month_rows.sort(key=lambda r: (r["month"] or "0000", r["category_name"]))

    ledger.sort(key=lambda r: (r["payment_date"] or "", r["receipt_no"], r["month_for"] or ""))
    ledger_total = len(ledger)
    ledger_sum = round(sum(r["amount"] for r in ledger), 2)
    shown = ledger
    if ledger_page:
        start = (max(1, ledger_page) - 1) * ledger_per_page
        shown = ledger[start:start + ledger_per_page]

    return {
        "categories":   sections,
        "summary":      summary,
        "grand_total":  {k: round(v, 2) for k, v in grand.items()},
        "by_month":     month_rows,
        "ledger":       shown,
        "ledger_total": ledger_total,
        "ledger_sum":   ledger_sum,
        "reconciliation": _reconciliation(landlord_id, tenant_ids, date_from, date_to),
        "date_from":    _iso(date_from),
        "date_to":      _iso(date_to),
        "generated_at": date.today().isoformat(),
    }


def _reconciliation(landlord_id, tenant_ids, date_from, date_to) -> dict:
    """Cash received in the range = allocated to charges + still held as advance credit."""
    q = (Payment.query.filter(Payment.landlord_id == landlord_id, Payment.is_deleted.is_(False),
                              Payment.status == PaymentStatus.confirmed.value,
                              Payment.source != PaymentSource.credit.value,
                              Payment.tenant_id.in_(tenant_ids)))
    if date_from:
        q = q.filter(Payment.payment_date >= date_from)
    if date_to:
        q = q.filter(Payment.payment_date <= date_to)
    ids = [p.id for p in q.all()]
    cash = sum((Decimal(p.amount or 0) for p in q.all()), Z)
    allocated = Z
    advance = Z
    if ids:
        allocated = Decimal(db.session.query(db.func.coalesce(db.func.sum(PaymentAllocation.amount_allocated), 0))
                            .filter(PaymentAllocation.payment_id.in_(ids)).scalar() or 0)
        advance = Decimal(db.session.query(db.func.coalesce(db.func.sum(CreditLedger.amount), 0))
                          .filter(CreditLedger.payment_id.in_(ids), CreditLedger.amount > 0).scalar() or 0)
    held_now = Decimal(db.session.query(db.func.coalesce(db.func.sum(Tenant.credit_balance), 0))
                       .filter(Tenant.id.in_(tenant_ids)).scalar() or 0)
    return {
        "payments": len(ids),
        "cash_received": _f(cash),
        "allocated_to_charges": _f(allocated),
        "advance_to_credit": _f(advance),
        "difference": _f(cash - allocated - advance),
        "credit_held_now": _f(held_now),
    }


def _empty_recon():
    return {"payments": 0, "cash_received": 0.0, "allocated_to_charges": 0.0,
            "advance_to_credit": 0.0, "difference": 0.0, "credit_held_now": 0.0}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

_TENANT_COLUMNS = [
    ("property_name", "Property", "text"), ("unit_name", "Unit", "text"),
    ("tenant_name", "Tenant", "text"), ("account_number", "Account no.", "text"),
    ("invoiced", "Invoiced", "money"), ("current_collected", "Current collected", "money"),
    ("balance_collected", "Arrears collected", "money"), ("total_collected", "Total collected", "money"),
    ("outstanding", "Still owed", "money"),
    ("deposit_invoiced", "Deposit invoiced", "money"), ("deposit_paid", "Deposit paid", "money"),
    ("deposit_balance", "Deposit owed", "money"), ("deposit_held", "Deposit held", "money"),
]
_SUMMARY_COLUMNS = [("category_name", "Category", "text"), ("kind", "Kind", "text")] + \
    [c for c in _TENANT_COLUMNS if c[2] == "money"]
_MONTH_COLUMNS = [("month_label", "Month (charge is for)", "text"), ("category_name", "Category", "text"),
                  ("invoiced", "Invoiced", "money"), ("collected", "Collected", "money"),
                  ("outstanding", "Still owed", "money")]
_LEDGER_COLUMNS = [
    ("payment_date", "Payment date", "text"), ("receipt_no", "Receipt no.", "text"),
    ("mpesa_ref", "M-Pesa / ref", "text"), ("source", "Method", "text"),
    ("tenant_name", "Tenant", "text"), ("account_number", "Account no.", "text"),
    ("property_name", "Property", "text"), ("unit_name", "Unit", "text"),
    ("invoice_number", "Invoice no.", "text"), ("category", "Category", "text"),
    ("type", "Type", "text"), ("month_label", "For month", "text"), ("amount", "Amount", "money"),
]


def build_payments_report_document(landlord, category_id="all", date_from=None,
                                   date_to=None, property_id=None, allowed_property_ids=None):
    """The report as a ReportDocument, for the PDF export (shared letterhead + signature)."""
    from services.report_builder import Column, Section, ReportDocument, build_meta, TEXT, MONEY

    data = build_payments_report(landlord.id, category_id, date_from, date_to, property_id,
                                 allowed_property_ids)

    def cols(spec):
        return [Column(k, label, MONEY if kind == "money" else TEXT) for k, label, kind in spec]

    def totals_for(spec, rows):
        return {k: round(sum(r.get(k, 0) or 0 for r in rows), 2) for k, _, kind in spec if kind == "money"}

    recon = data["reconciliation"]
    sections = [
        Section(key="summary", title="Summary by category", columns=cols(_SUMMARY_COLUMNS),
                rows=data["summary"], totals=totals_for(_SUMMARY_COLUMNS, data["summary"]),
                note="Total collected = current + arrears. Deposits are held money and shown apart."),
        Section(key="reconciliation", title="Cash reconciliation", kind="keyvalue", columns=[],
                rows=[{"label": "Payments received", "display": str(recon["payments"])},
                      {"label": "Cash received", "display": f"KES {recon['cash_received']:,.2f}"},
                      {"label": "Allocated to charges", "display": f"KES {recon['allocated_to_charges']:,.2f}"},
                      {"label": "Held as advance credit", "display": f"KES {recon['advance_to_credit']:,.2f}"},
                      {"label": "Unexplained difference", "display": f"KES {recon['difference']:,.2f}"}]),
        Section(key="by_month", title="By month the charge is for", columns=cols(_MONTH_COLUMNS),
                rows=data["by_month"], totals=totals_for(_MONTH_COLUMNS, data["by_month"])),
    ]
    for sec in data["categories"]:
        if not sec["rows"]:
            continue
        sections.append(Section(key=f"cat_{sec['category_id']}",
                                title=f"{sec['category_name']} — per tenant",
                                columns=cols(_TENANT_COLUMNS), rows=sec["rows"],
                                totals=totals_for(_TENANT_COLUMNS, sec["rows"])))
    period = None
    if data["date_from"] or data["date_to"]:
        period = f"{data['date_from'] or '…'} to {data['date_to'] or '…'}"
    meta = build_meta(landlord, report_title="Payments Report", period=period)
    return ReportDocument("payments_report", "Payments Report", meta, sections)


def build_payments_report_excel(landlord, category_id="all", date_from=None, date_to=None,
                                property_id=None, allowed_property_ids=None) -> bytes:
    """
    A workbook built to be worked on: one sheet per table, real numbers (not
    text) in money columns, a filter on every header, frozen header rows and
    the full allocation ledger — every allocation, not a page of it.
    """
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from services import branding

    data = build_payments_report(landlord.id, category_id, date_from, date_to, property_id,
                                 allowed_property_ids)
    wb = Workbook()
    wb.properties.creator = branding.BRAND_NAME
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2B2B55")
    money_fmt = '#,##0.00'
    period = (f"{data['date_from'] or 'start'} to {data['date_to'] or 'today'}")

    def sheet(ws, title, spec, rows, total=True):
        ws.title = title[:31]
        ws.cell(row=1, column=1, value=f"{landlord.company_name or ''} — {title}").font = Font(bold=True, size=13)
        ws.cell(row=2, column=1, value=f"Period: {period} · Generated {data['generated_at']} · Currency KES")
        hr = 4
        for ci, (_, label, _k) in enumerate(spec, start=1):
            c = ws.cell(row=hr, column=ci, value=label)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for ri, row in enumerate(rows, start=hr + 1):
            for ci, (key, _label, kind) in enumerate(spec, start=1):
                v = row.get(key)
                c = ws.cell(row=ri, column=ci, value=(float(v or 0) if kind == "money" else (v if v is not None else "")))
                if kind == "money":
                    c.number_format = money_fmt
        last = hr + len(rows)
        if total and rows:
            tr = last + 1
            ws.cell(row=tr, column=1, value="TOTAL").font = Font(bold=True)
            for ci, (key, _label, kind) in enumerate(spec, start=1):
                if kind == "money":
                    col = get_column_letter(ci)
                    c = ws.cell(row=tr, column=ci, value=f"=SUBTOTAL(9,{col}{hr + 1}:{col}{last})")
                    c.number_format, c.font = money_fmt, Font(bold=True)
        ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(spec))}{max(last, hr)}"
        ws.freeze_panes = f"A{hr + 1}"
        for ci, (key, label, kind) in enumerate(spec, start=1):
            longest = max([len(str(label))] + [len(str(r.get(key) or "")) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(ci)].width = min(max(longest + 2, 12), 40)

    sheet(wb.active, "Summary by category", _SUMMARY_COLUMNS, data["summary"])
    sheet(wb.create_sheet(), "By month", _MONTH_COLUMNS, data["by_month"])
    tenant_rows = [{**r, "category_name": sec["category_name"]}
                   for sec in data["categories"] for r in sec["rows"]]
    sheet(wb.create_sheet(), "Per tenant", [("category_name", "Category", "text")] + _TENANT_COLUMNS,
          tenant_rows)
    sheet(wb.create_sheet(), "Allocation ledger", _LEDGER_COLUMNS, data["ledger"])

    recon = data["reconciliation"]
    ws = wb.create_sheet("Reconciliation")
    ws.cell(row=1, column=1, value="Cash reconciliation").font = Font(bold=True, size=13)
    ws.cell(row=2, column=1, value=f"Period: {period}")
    for i, (label, key) in enumerate([
        ("Payments received", "payments"), ("Cash received", "cash_received"),
        ("Allocated to charges", "allocated_to_charges"), ("Held as advance credit", "advance_to_credit"),
        ("Unexplained difference (should be 0)", "difference"),
        ("Credit held on accounts now", "credit_held_now")], start=4):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        c = ws.cell(row=i, column=2, value=recon[key])
        if key != "payments":
            c.number_format = money_fmt
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 18

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def rollover_trail(line_item_id, landlord_id) -> dict:
    """The origin-month breakdown of a balance line, and how much of each is still owed."""
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

_METRIC_KEYS = ("invoiced", "current_collected", "balance_collected", "total_collected",
                "outstanding", "deposit_invoiced", "deposit_paid", "deposit_balance",
                "deposit_held")


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
