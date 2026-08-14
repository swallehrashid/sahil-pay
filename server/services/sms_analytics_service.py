"""
services/sms_analytics_service.py — Admin SMS reselling analytics
=================================================================
§9.3 — powers the admin "SMS management" monitoring + report. SahilPay resells
SMS to landlords; this module answers, platform-wide:

  * how many SMS have been **sold** (BillingTransaction type=sms_purchase, paid)
    and the **revenue** that generated (default vs custom rate),
  * how many SMS have been **spent** by landlords (delivered CommunicationLog
    rows), split shared (default, out of the pool) vs own-sender (custom),
  * SahilPay's **platform cost** for those sends — charged on EVERY send, since
    every sender ID is registered on SahilPay's own provider account,
  * the resulting **gross margin** and margin %, the shared-pool balance, the
    pool usage %, and the effective average resale rate,
  * a **per-landlord** breakdown, and a **monthly** revenue-vs-cost series.

`build_sms_report()` returns a `ReportDocument` so the admin SMS report gets
preview / column-editing / PDF / Excel for free via the shared report engine
(exactly like the landlord reports), rendered with SahilPay platform letterhead.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from models import (
    Landlord, BillingTransaction, CommunicationLog, SmsPricingConfig, SmsPoolTopUp,
    BillingTransactionType, BillingTransactionStatus,
    MessageChannel, CommunicationStatus,
)
from services.report_builder import (
    Column, ReportDocument, Section, build_meta,
    TEXT, MONEY, NUMBER, PERCENT,
)
from services.sms_billing import load_rates

ZERO = Decimal("0.00")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _label(landlord) -> str:
    return landlord.company_name if landlord else "—"


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def _purchases_by_landlord() -> dict:
    """{landlord_id: {"bought": int, "revenue": float}} from paid SMS purchases."""
    rows = (
        db.session.query(
            BillingTransaction.landlord_id.label("lid"),
            func.coalesce(func.sum(BillingTransaction.sms_count), 0).label("bought"),
            func.coalesce(func.sum(BillingTransaction.amount), 0).label("revenue"),
        )
        .filter(
            BillingTransaction.type == BillingTransactionType.sms_purchase.value,
            BillingTransaction.status == BillingTransactionStatus.paid.value,
        )
        .group_by(BillingTransaction.landlord_id)
        .all()
    )
    return {r.lid: {"bought": int(r.bought or 0), "revenue": _f(r.revenue)} for r in rows}


def _usage_by_landlord() -> dict:
    """
    {landlord_id: {"spent","spent_shared","spent_own","cost"}} from delivered SMS.
    Segments (credits) are the unit of "spend"; cost is SahilPay's platform cost.
    Demo shadow landlords (DEMO_MODE_SPEC.md §3.4) are excluded — their sends
    never touch the shared pool or platform cost, and must not appear in
    platform-wide SMS usage/revenue analytics.
    """
    rows = (
        db.session.query(
            CommunicationLog.landlord_id.label("lid"),
            CommunicationLog.uses_own_sender.label("own"),
            func.coalesce(func.sum(CommunicationLog.sms_segments), 0).label("segments"),
            func.coalesce(func.sum(CommunicationLog.platform_cost), 0).label("cost"),
        )
        .join(Landlord, Landlord.id == CommunicationLog.landlord_id)
        .filter(
            CommunicationLog.message_type == MessageChannel.sms.value,
            CommunicationLog.status == CommunicationStatus.delivered.value,
            Landlord.is_demo.is_(False),
        )
        .group_by(CommunicationLog.landlord_id, CommunicationLog.uses_own_sender)
        .all()
    )
    out: dict = {}
    for r in rows:
        seg = int(r.segments or 0)
        bucket = out.setdefault(r.lid, {"spent": 0, "spent_shared": 0, "spent_own": 0, "cost": 0.0})
        bucket["spent"] += seg
        bucket["cost"] += _f(r.cost)
        if r.own:
            bucket["spent_own"] += seg
        else:
            bucket["spent_shared"] += seg
    return out


def _monthly_series(months: int = 6) -> list[dict]:
    """Revenue (SMS sales) vs platform cost (SMS delivered) per calendar month."""
    rev_col = func.to_char(func.date_trunc("month", BillingTransaction.created_at), "YYYY-MM")
    rev_rows = (
        db.session.query(
            rev_col.label("month"),
            func.coalesce(func.sum(BillingTransaction.amount), 0).label("revenue"),
            func.coalesce(func.sum(BillingTransaction.sms_count), 0).label("sold"),
        )
        .filter(
            BillingTransaction.type == BillingTransactionType.sms_purchase.value,
            BillingTransaction.status == BillingTransactionStatus.paid.value,
        )
        .group_by("month")
        .all()
    )
    rev_by_month = {r.month: (_f(r.revenue), int(r.sold or 0)) for r in rev_rows}

    cost_col = func.to_char(func.date_trunc("month", CommunicationLog.created_at), "YYYY-MM")
    cost_rows = (
        db.session.query(
            cost_col.label("month"),
            func.coalesce(func.sum(CommunicationLog.platform_cost), 0).label("cost"),
            func.coalesce(func.sum(CommunicationLog.sms_segments), 0).label("spent"),
        )
        .join(Landlord, Landlord.id == CommunicationLog.landlord_id)
        .filter(
            CommunicationLog.message_type == MessageChannel.sms.value,
            CommunicationLog.status == CommunicationStatus.delivered.value,
            Landlord.is_demo.is_(False),
        )
        .group_by("month")
        .all()
    )
    cost_by_month = {r.month: (_f(r.cost), int(r.spent or 0)) for r in cost_rows}

    buckets = _empty_month_buckets(months)
    for key, bucket in buckets.items():
        rev, sold = rev_by_month.get(key, (0.0, 0))
        cost, spent = cost_by_month.get(key, (0.0, 0))
        bucket["revenue"] = rev
        bucket["sold"] = sold
        bucket["cost"] = cost
        bucket["spent"] = spent
        bucket["margin"] = round(rev - cost, 2)
    return list(buckets.values())


def _empty_month_buckets(months: int) -> dict:
    today = date.today()
    out = {}
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = f"{y:04d}-{m:02d}"
        out[key] = {"month": key, "revenue": 0.0, "sold": 0, "cost": 0.0, "spent": 0, "margin": 0.0}
    return out


def _pct(part: float, whole: float) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


# ---------------------------------------------------------------------------
# Public: overview payload + per-landlord rows
# ---------------------------------------------------------------------------

# Below this many credits a landlord is about to stop being able to send, and
# is worth a "top up?" nudge. A landlord who has never bought sits at 0 and is
# therefore always flagged, which is correct — they are the ones to call.
LOW_BALANCE_THRESHOLD = 50


def _landlord_rows() -> list[dict]:
    """
    One row per ACTIVE landlord — not merely those who have transacted.

    Listing only buyers would hide exactly the accounts worth chasing: a
    landlord sitting on zero credits never appears in a purchase or usage
    query, yet they are the one who cannot send a rent reminder tomorrow.
    """
    from services.sms_billing import effective_price_per_sms

    purchases = _purchases_by_landlord()
    usage = _usage_by_landlord()

    landlords = (
        Landlord.query
        .filter(Landlord.is_demo.is_(False))    # demo shadows are not customers
        .all()
    )

    rows = []
    for l in landlords:
        p = purchases.get(l.id, {})
        u = usage.get(l.id, {})
        settings = l.landlord_settings
        balance = int(l.sms_balance or 0)
        rows.append({
            "landlord_id":  l.id,
            "landlord":     _label(l),
            "bought":       int(p.get("bought", 0)),
            "revenue":      round(p.get("revenue", 0.0), 2),
            "spent":        int(u.get("spent", 0)),
            "spent_shared": int(u.get("spent_shared", 0)),
            "spent_own":    int(u.get("spent_own", 0)),
            "cost":         round(u.get("cost", 0.0), 2),
            "balance":      balance,
            "low_balance":  balance < LOW_BALANCE_THRESHOLD,
            # What this landlord pays per credit right now, and whether that is
            # a negotiated figure or the account-wide default.
            "rate":         float(effective_price_per_sms(settings, landlord=l)),
            "has_own_rate": l.sms_price_override is not None,
            "sender_id":    (settings.sms_sender_id
                             if settings and settings.sms_connected else None),
        })
    # Lowest balances first: this table is read to find who needs topping up.
    rows.sort(key=lambda r: (r["balance"], -r["revenue"]))
    return rows


def sms_overview(months: int = 6) -> dict:
    cfg = SmsPricingConfig.get_singleton()
    rates = load_rates()
    rows = _landlord_rows()
    monthly = _monthly_series(months)

    total_sold    = sum(r["bought"] for r in rows)
    total_revenue = round(sum(r["revenue"] for r in rows), 2)
    total_spent   = sum(r["spent"] for r in rows)
    total_shared  = sum(r["spent_shared"] for r in rows)
    total_own     = sum(r["spent_own"] for r in rows)
    total_cost    = round(sum(r["cost"] for r in rows), 2)
    gross_margin  = round(total_revenue - total_cost, 2)

    pool_added = db.session.query(
        func.coalesce(func.sum(SmsPoolTopUp.credits_added), 0)
    ).scalar() or 0
    pool_added = int(pool_added)
    # Total credits that have flowed into the shared pool (top-ups) vs what's
    # left; usage % is how much of the shared capacity has been consumed.
    pool_capacity = max(pool_added, cfg.pool_balance + total_shared)
    pool_used = max(pool_capacity - cfg.pool_balance, 0)

    return {
        "pricing": cfg.to_dict(),
        "pool_balance":       cfg.pool_balance,
        "pool_added_total":   pool_added,
        "pool_used":          pool_used,
        "pool_usage_pct":     _pct(pool_used, pool_capacity),
        "shared_enabled":     rates["shared_enabled"],
        # The two figures the rate dialog needs: what everyone pays by default,
        # and what a credit costs Sahil Pay — so the margin on a proposed rate
        # is visible while it is being typed.
        "rates": {
            "default_price": float(rates["default_price"]),
            "platform_cost": float(rates["platform_cost"]),
            "low_balance_threshold": LOW_BALANCE_THRESHOLD,
        },
        "totals": {
            "sms_sold":       total_sold,
            "revenue":        total_revenue,
            "sms_spent":      total_spent,
            "spent_shared":   total_shared,
            "spent_own":      total_own,
            "platform_cost":  total_cost,
            "gross_margin":   gross_margin,
            "margin_pct":     _pct(gross_margin, total_revenue),
            "avg_rate":       round(total_revenue / total_sold, 4) if total_sold else 0.0,
        },
        "landlords": rows,
        "monthly":   monthly,
    }


# ---------------------------------------------------------------------------
# Public: downloadable ReportDocument (preview / PDF / Excel via report engine)
# ---------------------------------------------------------------------------

def build_sms_report(months: int = 12) -> ReportDocument:
    ov = sms_overview(months=months)
    t = ov["totals"]
    p = ov["pricing"]

    def _kv(label, value, display):
        return {"label": label, "value": value, "display": display}

    summary = Section(
        "summary", "SMS reselling summary",
        [Column("label", "Metric", TEXT), Column("value", "Value", TEXT)],
        [
            _kv("Shared pool balance", ov["pool_balance"], f"{ov['pool_balance']:,} SMS"),
            _kv("Pool usage", ov["pool_usage_pct"], f"{ov['pool_usage_pct']}%"),
            _kv("SMS sold (all-time)", t["sms_sold"], f"{t['sms_sold']:,}"),
            _kv("SMS spent by landlords", t["sms_spent"], f"{t['sms_spent']:,}"),
            _kv("  · via shared sender", t["spent_shared"], f"{t['spent_shared']:,}"),
            _kv("  · via own sender", t["spent_own"], f"{t['spent_own']:,}"),
            _kv("Resale revenue", t["revenue"], f"KES {t['revenue']:,.2f}"),
            _kv("Platform SMS cost", t["platform_cost"], f"KES {t['platform_cost']:,.2f}"),
            _kv("Gross margin", t["gross_margin"], f"KES {t['gross_margin']:,.2f}"),
            _kv("Margin", t["margin_pct"], f"{t['margin_pct']}%"),
            _kv("Effective average rate", t["avg_rate"], f"KES {t['avg_rate']:,.4f} / SMS"),
            _kv("Default price / SMS", p["default_price_per_sms"], f"KES {_f(p['default_price_per_sms']):,.4f}"),
            _kv("Custom price / SMS", p["custom_price_per_sms"], f"KES {_f(p['custom_price_per_sms']):,.4f}"),
            _kv("Platform cost / SMS", p["platform_cost_per_sms"], f"KES {_f(p['platform_cost_per_sms']):,.4f}"),
        ],
        kind="keyvalue",
    )

    purchases = Section(
        "purchases", "SMS purchases by landlord",
        [
            Column("landlord", "Landlord", TEXT),
            Column("bought", "SMS bought", NUMBER),
            Column("revenue", "Revenue", MONEY),
            Column("balance", "Balance", NUMBER),
        ],
        [{"landlord": r["landlord"], "bought": r["bought"], "revenue": r["revenue"], "balance": r["balance"]}
         for r in ov["landlords"]],
        totals={"bought": t["sms_sold"], "revenue": t["revenue"]},
    )

    usage = Section(
        "usage", "SMS usage by landlord",
        [
            Column("landlord", "Landlord", TEXT),
            Column("spent", "SMS spent", NUMBER),
            Column("spent_shared", "Shared", NUMBER),
            Column("spent_own", "Own sender", NUMBER),
            Column("cost", "Platform cost", MONEY),
        ],
        [{"landlord": r["landlord"], "spent": r["spent"], "spent_shared": r["spent_shared"],
          "spent_own": r["spent_own"], "cost": r["cost"]} for r in ov["landlords"]],
        totals={"spent": t["sms_spent"], "spent_shared": t["spent_shared"],
                "spent_own": t["spent_own"], "cost": t["platform_cost"]},
    )

    monthly = Section(
        "monthly", "Revenue vs cost by month",
        [
            Column("month", "Month", TEXT),
            Column("sold", "SMS sold", NUMBER),
            Column("revenue", "Revenue", MONEY),
            Column("spent", "SMS spent", NUMBER, default=False),
            Column("cost", "Platform cost", MONEY),
            Column("margin", "Margin", MONEY),
        ],
        ov["monthly"],
        charts=[
            {"key": "revenue", "title": "Revenue by month", "type": "bar", "x": "month", "y": "revenue"},
            {"key": "cost", "title": "Platform cost by month", "type": "bar", "x": "month", "y": "cost"},
            {"key": "margin", "title": "Margin by month", "type": "bar", "x": "month", "y": "margin"},
        ],
        note="Add any series' graph to the download using the chart toggles.",
    )

    meta = build_meta(
        None,
        report_title="SMS Reselling Analytics",
        period=f"Last {months} months",
        extra={"company_name": "SahilPay", "currency": "KES"},
    )
    return ReportDocument("sms_analytics", "SMS Reselling Analytics", meta,
                          [summary, purchases, usage, monthly])
