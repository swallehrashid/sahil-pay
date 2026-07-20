"""
services/pricing_analytics_service.py — Per-package performance analytics
=========================================================================
§7.2 — powers the admin "package details" drill-down: how many landlords
sit on a package, how many are active vs inactive, how much revenue the
package has earned (all-time and within a period), a monthly performance
series for charting, and a downloadable report (PDF/Excel).

Revenue = paid subscription BillingTransactions from the landlords currently
on the package.  "Active" = the landlord's User.is_active flag.  Monthly
"new subscribers" is approximated from landlord.created_at (we do not keep a
package-change history), which is accurate for the common case where a
landlord stays on one package.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import (
    Package, Landlord, BillingTransaction,
    Unit, Property, BillingTransactionType, BillingTransactionStatus,
)
from services.export_service import _render_table


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _subscriber_ids(package_id: int) -> list[int]:
    rows = db.session.query(Landlord.id).filter(Landlord.package_id == package_id).all()
    return [r[0] for r in rows]


def _unit_count(landlord_id: int) -> int:
    return (
        Unit.query.join(Property)
        .filter(
            Property.landlord_id == landlord_id,
            Property.is_deleted.is_(False),
            Unit.is_deleted.is_(False),
        )
        .count()
    )


def _paid_subscription_revenue(landlord_ids, start=None, end=None) -> Decimal:
    if not landlord_ids:
        return Decimal("0")
    q = (
        db.session.query(func.coalesce(func.sum(BillingTransaction.amount), 0))
        .filter(
            BillingTransaction.landlord_id.in_(landlord_ids),
            BillingTransaction.type == BillingTransactionType.subscription.value,
            BillingTransaction.status == BillingTransactionStatus.paid.value,
        )
    )
    if start:
        q = q.filter(BillingTransaction.created_at >= start)
    if end:
        q = q.filter(BillingTransaction.created_at <= f"{end} 23:59:59")
    return q.scalar() or Decimal("0")


def _monthly_series(landlord_ids, months: int = 6) -> list[dict]:
    """Revenue + payment count per calendar month for the last `months`."""
    if not landlord_ids:
        buckets = _empty_month_buckets(months)
        return list(buckets.values())

    month_col = func.to_char(func.date_trunc("month", BillingTransaction.created_at), "YYYY-MM")
    rows = (
        db.session.query(
            month_col.label("month"),
            func.coalesce(func.sum(BillingTransaction.amount), 0).label("revenue"),
            func.count(BillingTransaction.id).label("payments"),
        )
        .filter(
            BillingTransaction.landlord_id.in_(landlord_ids),
            BillingTransaction.type == BillingTransactionType.subscription.value,
            BillingTransaction.status == BillingTransactionStatus.paid.value,
        )
        .group_by("month")
        .all()
    )
    revenue_by_month = {r.month: (_f(r.revenue), int(r.payments)) for r in rows}

    # New subscribers per month (by landlord.created_at)
    sub_rows = (
        db.session.query(
            func.to_char(func.date_trunc("month", Landlord.created_at), "YYYY-MM").label("month"),
            func.count(Landlord.id).label("n"),
        )
        .filter(Landlord.id.in_(landlord_ids))
        .group_by("month")
        .all()
    )
    new_by_month = {r.month: int(r.n) for r in sub_rows}

    buckets = _empty_month_buckets(months)
    for key, bucket in buckets.items():
        rev, pays = revenue_by_month.get(key, (0.0, 0))
        bucket["revenue"] = rev
        bucket["payments"] = pays
        bucket["new_subscribers"] = new_by_month.get(key, 0)
    return list(buckets.values())


def _empty_month_buckets(months: int) -> dict:
    """Ordered {'YYYY-MM': {...}} for the last `months` including current."""
    today = date.today()
    out = {}
    for i in range(months - 1, -1, -1):
        y = today.year
        m = today.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y:04d}-{m:02d}"
        out[key] = {"month": key, "revenue": 0.0, "payments": 0, "new_subscribers": 0}
    return out


def package_analytics(package_id: int, start_date=None, end_date=None, months: int = 6) -> dict:
    package = db.session.get(Package, package_id)
    if not package:
        return None

    subscribers = (
        db.session.query(Landlord)
        .filter(Landlord.package_id == package_id)
        .all()
    )
    ids = [l.id for l in subscribers]

    landlord_rows = []
    active_count = 0
    for l in subscribers:
        is_active = bool(l.user.is_active) if l.user else False
        if is_active:
            active_count += 1
        sub = l.subscription
        landlord_rows.append({
            "id":                  l.id,
            "company_name":        l.company_name,
            "email":               l.user.email if l.user else None,
            "is_active":           is_active,
            "is_on_trial":         l.is_on_trial,
            "subscription_status": sub.status if sub else None,
            "subscription_cost":   _f(sub.subscription_cost) if sub else 0.0,
            "unit_count":          _unit_count(l.id),
            "total_paid":          _f(_paid_subscription_revenue([l.id])),
        })

    mrr = sum(r["subscription_cost"] for r in landlord_rows if r["is_active"])

    return {
        "package":          package.to_dict(),
        "subscriber_count": len(subscribers),
        "active_count":     active_count,
        "inactive_count":   len(subscribers) - active_count,
        "total_revenue":    _f(_paid_subscription_revenue(ids)),
        "period_revenue":   _f(_paid_subscription_revenue(ids, start_date, end_date)),
        "mrr_estimate":     mrr,
        "monthly":          _monthly_series(ids, months),
        "landlords":        sorted(landlord_rows, key=lambda r: r["total_paid"], reverse=True),
    }


def package_report(package_id: int, fmt: str, start_date=None, end_date=None) -> bytes:
    """Render a downloadable per-package performance report (PDF or Excel)."""
    data = package_analytics(package_id, start_date, end_date)
    if data is None:
        return None

    pkg = data["package"]
    title = f"Package Report — {pkg['name']}"

    # Summary block rendered as a two-column table, then the landlord roster.
    summary_headers = ["Metric", "Value"]
    summary_rows = [
        ["Subscribers", data["subscriber_count"]],
        ["Active", data["active_count"]],
        ["Inactive", data["inactive_count"]],
        ["Total revenue (KES)", f"{data['total_revenue']:,.2f}"],
        ["Period revenue (KES)", f"{data['period_revenue']:,.2f}"],
        ["Est. MRR (KES)", f"{data['mrr_estimate']:,.2f}"],
    ]

    roster_headers = ["Landlord", "Email", "Status", "Sub. status", "Units", "Sub. cost", "Total paid"]
    roster_rows = [
        [
            r["company_name"], r["email"] or "—",
            "Active" if r["is_active"] else "Inactive",
            r["subscription_status"] or "—",
            r["unit_count"],
            f"{r['subscription_cost']:,.2f}",
            f"{r['total_paid']:,.2f}",
        ]
        for r in data["landlords"]
    ]

    if fmt == "excel":
        # One combined sheet: summary rows then a blank line then the roster.
        headers = roster_headers
        rows = (
            [["Metric", "Value", "", "", "", "", ""]]
            + [[m, v, "", "", "", "", ""] for m, v in summary_rows]
            + [["", "", "", "", "", "", ""], roster_headers]
            + roster_rows
        )
        return _render_table(title, headers, rows, "excel")

    # PDF: render summary + roster into one document.
    from services.pdf_service import _BASE_STYLE
    from utils import render_pdf

    def _tbl(headers, rows):
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{'' if c is None else c}</td>" for c in row) + "</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    period = ""
    if start_date or end_date:
        period = f"<p class='muted'>Period: {start_date or '—'} to {end_date or '—'}</p>"

    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>{_BASE_STYLE}</head><body>"
        f"<h1>{title}</h1>{period}"
        f"<h2>Summary</h2>{_tbl(summary_headers, summary_rows)}"
        f"<h2>Subscribers</h2>{_tbl(roster_headers, roster_rows)}"
        f"</body></html>"
    )
    return render_pdf(html)
