"""
SahilPay — services/affiliate_report_service.py
==================================================
Admin-facing affiliate program reports (AFFILIATE_PROGRAM_SPEC.md §9).
Reuses export_service's (headers, rows) -> bytes render path — every report
here supports ?fmt=pdf|csv|xlsx via the same _render_table dispatcher the
rest of the platform's reports use.

The payouts report is the owner's KRA remittance working paper: gross /
WHT withheld / platform fee collected / net paid, per affiliate, for a
period — so its numbers are computed straight off AffiliateWithdrawal rows
(paid, within the date range), never recomputed or re-derived.
"""

from __future__ import annotations

from decimal import Decimal

from services.export_service import _render_table, _date_range_filter
from services.pdf_service import _money


def _quantize(value) -> Decimal:
    from decimal import ROUND_HALF_UP
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1) Payouts report — the KRA remittance working paper
# ---------------------------------------------------------------------------

def generate_payouts_report(fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from models import AffiliateWithdrawal, Affiliate, WithdrawalStatus

    query = AffiliateWithdrawal.query.filter(AffiliateWithdrawal.status == WithdrawalStatus.paid.value)
    query = _date_range_filter(query, AffiliateWithdrawal.processed_at, start_date, end_date)
    withdrawals = query.order_by(AffiliateWithdrawal.affiliate_id).all()

    by_affiliate: dict[int, dict] = {}
    for w in withdrawals:
        row = by_affiliate.setdefault(w.affiliate_id, {
            "gross": Decimal("0"), "wht": Decimal("0"), "fee": Decimal("0"),
            "net": Decimal("0"), "count": 0,
        })
        row["gross"] += Decimal(str(w.gross_amount))
        row["wht"]   += Decimal(str(w.wht_amount))
        row["fee"]   += Decimal(str(w.fee_amount))
        row["net"]   += Decimal(str(w.net_amount))
        row["count"] += 1

    headers = ["Affiliate", "Withdrawals", "Gross Paid Out", "WHT Withheld", "Platform Fee Collected", "Net Paid"]
    rows, totals = [], {"gross": Decimal("0"), "wht": Decimal("0"), "fee": Decimal("0"), "net": Decimal("0"), "count": 0}
    for affiliate_id, agg in by_affiliate.items():
        affiliate = Affiliate.query.get(affiliate_id)
        rows.append([
            affiliate.full_name if affiliate else f"#{affiliate_id}",
            agg["count"], _money(agg["gross"]), _money(agg["wht"]), _money(agg["fee"]), _money(agg["net"]),
        ])
        for k in ("gross", "wht", "fee", "net"):
            totals[k] += agg[k]
        totals["count"] += agg["count"]

    rows.append(["TOTAL", totals["count"], _money(totals["gross"]), _money(totals["wht"]),
                _money(totals["fee"]), _money(totals["net"])])

    return _render_table("Affiliate Payouts Report", headers, rows, fmt)


# ---------------------------------------------------------------------------
# 2) Earnings report
# ---------------------------------------------------------------------------

def generate_earnings_report(fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from extensions import db
    from models import Affiliate, AffiliateCommission, CommissionStatus
    from services import affiliate_service as svc

    affiliates = Affiliate.query.order_by(Affiliate.full_name).all()
    headers = ["Affiliate", "Confirmed in Period", "Reversed in Period", "Current Balance", "Lifetime Earned"]
    rows = []
    for a in affiliates:
        confirmed_q = AffiliateCommission.query.filter_by(affiliate_id=a.id, status=CommissionStatus.confirmed.value)
        confirmed_q = _date_range_filter(confirmed_q, AffiliateCommission.created_at, start_date, end_date)
        confirmed_period = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
            AffiliateCommission.id.in_([c.id for c in confirmed_q.all()])
        ).scalar() if confirmed_q.count() else 0

        reversed_q = AffiliateCommission.query.filter_by(affiliate_id=a.id, status=CommissionStatus.reversed.value)
        reversed_q = _date_range_filter(reversed_q, AffiliateCommission.reversed_at, start_date, end_date)
        reversed_period = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
            AffiliateCommission.id.in_([c.id for c in reversed_q.all()])
        ).scalar() if reversed_q.count() else 0

        lifetime = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
            AffiliateCommission.affiliate_id == a.id, AffiliateCommission.status == CommissionStatus.confirmed.value,
        ).scalar()

        rows.append([
            a.full_name, _money(confirmed_period), _money(reversed_period),
            _money(svc.get_balance(a.id)), _money(lifetime),
        ])

    return _render_table("Affiliate Earnings Report", headers, rows, fmt)


# ---------------------------------------------------------------------------
# 3) Referral performance report
# ---------------------------------------------------------------------------

def generate_referral_performance_report(fmt: str, start_date: str | None, end_date: str | None) -> bytes:
    from extensions import db
    from models import Affiliate, AffiliateReferral, AffiliateCommission, ReferralStatus, CommissionStatus

    affiliates = Affiliate.query.order_by(Affiliate.full_name).all()
    headers = [
        "Affiliate", "Referrals Attributed", "Converted (Ever)", "Active Windows",
        "Completed", "Conversion Rate", "Commission Cost",
    ]
    rows = []
    for a in affiliates:
        attributed_q = AffiliateReferral.query.filter_by(affiliate_id=a.id)
        attributed_q = _date_range_filter(attributed_q, AffiliateReferral.created_at, start_date, end_date)
        attributed = attributed_q.all()

        total_referrals = AffiliateReferral.query.filter_by(affiliate_id=a.id).count()
        converted = AffiliateReferral.query.filter(
            AffiliateReferral.affiliate_id == a.id,
            AffiliateReferral.window_started_at.isnot(None),
        ).count()
        active = AffiliateReferral.query.filter_by(affiliate_id=a.id, status=ReferralStatus.active.value).count()
        completed = AffiliateReferral.query.filter_by(affiliate_id=a.id, status=ReferralStatus.completed.value).count()
        conversion_rate = f"{(converted / total_referrals * 100):.1f}%" if total_referrals else "—"

        commission_cost = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
            AffiliateCommission.affiliate_id == a.id, AffiliateCommission.status == CommissionStatus.confirmed.value,
        ).scalar()

        rows.append([
            a.full_name, len(attributed), converted, active, completed,
            conversion_rate, _money(commission_cost),
        ])

    return _render_table("Affiliate Referral Performance Report", headers, rows, fmt)


# ---------------------------------------------------------------------------
# 4) Program summary — one-pager
# ---------------------------------------------------------------------------

def generate_program_summary_report(fmt: str) -> bytes:
    from extensions import db
    from models import Affiliate, AffiliateCommission, AffiliateWithdrawal, CommissionStatus, WithdrawalStatus
    from services import affiliate_service as svc

    cfg = svc.get_program_config()

    total_confirmed = db.session.query(db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0)).filter(
        AffiliateCommission.status == CommissionStatus.confirmed.value
    ).scalar()
    total_held = db.session.query(db.func.coalesce(db.func.sum(AffiliateWithdrawal.gross_amount), 0)).filter(
        AffiliateWithdrawal.status.in_(["requested", "processing", "paid"])
    ).scalar()
    total_liability = _quantize(total_confirmed) - _quantize(total_held)

    paid_withdrawals = AffiliateWithdrawal.query.filter_by(status=WithdrawalStatus.paid.value).all()
    total_paid_out = sum((Decimal(str(w.net_amount)) for w in paid_withdrawals), Decimal("0"))
    total_wht = sum((Decimal(str(w.wht_amount)) for w in paid_withdrawals), Decimal("0"))
    total_fees = sum((Decimal(str(w.fee_amount)) for w in paid_withdrawals), Decimal("0"))

    headers = ["Metric", "Value"]
    rows = [
        ["Program active", "Yes" if cfg.is_program_active else "No"],
        ["Default commission rate", f"{cfg.default_commission_rate}%"],
        ["Default commission months", cfg.default_commission_months],
        ["Total outstanding liability (owed, unpaid)", _money(total_liability)],
        ["Total paid out to date (net)", _money(total_paid_out)],
        ["Total WHT remitted to date", _money(total_wht)],
        ["Total platform fees collected to date", _money(total_fees)],
        ["Total affiliates", Affiliate.query.count()],
        ["Active affiliates", Affiliate.query.filter_by(status="active").count()],
        ["Pending approval", Affiliate.query.filter_by(status="pending").count()],
    ]

    leaderboard = (
        db.session.query(
            Affiliate.full_name,
            db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0).label("total"),
        )
        .join(AffiliateCommission, AffiliateCommission.affiliate_id == Affiliate.id)
        .filter(AffiliateCommission.status == CommissionStatus.confirmed.value)
        .group_by(Affiliate.id, Affiliate.full_name)
        .order_by(db.text("total DESC"))
        .limit(10)
        .all()
    )
    rows.append(["", ""])
    rows.append(["Top 10 affiliates by lifetime earnings", ""])
    for name, total in leaderboard:
        rows.append([name, _money(total)])

    return _render_table("Affiliate Program Summary", headers, rows, fmt)


# ---------------------------------------------------------------------------
# Analytics (charts on the admin page)
# ---------------------------------------------------------------------------

def get_analytics() -> dict:
    from extensions import db
    from models import Affiliate, AffiliateReferral, AffiliateCommission, AffiliateWithdrawal, CommissionStatus, WithdrawalStatus
    from services import affiliate_service as svc

    # Monthly time series (last 12 months): commissions accrued, payouts, fees, WHT.
    monthly = (
        db.session.query(
            db.func.to_char(AffiliateCommission.created_at, "YYYY-MM").label("month"),
            db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0).label("accrued"),
        )
        .filter(AffiliateCommission.status == CommissionStatus.confirmed.value)
        .group_by("month")
        .order_by("month")
        .all()
    )
    payouts_monthly = (
        db.session.query(
            db.func.to_char(AffiliateWithdrawal.processed_at, "YYYY-MM").label("month"),
            db.func.coalesce(db.func.sum(AffiliateWithdrawal.net_amount), 0).label("net"),
            db.func.coalesce(db.func.sum(AffiliateWithdrawal.fee_amount), 0).label("fee"),
            db.func.coalesce(db.func.sum(AffiliateWithdrawal.wht_amount), 0).label("wht"),
        )
        .filter(AffiliateWithdrawal.status == WithdrawalStatus.paid.value)
        .group_by("month")
        .order_by("month")
        .all()
    )

    leaderboard = (
        db.session.query(Affiliate.id, Affiliate.full_name,
                         db.func.coalesce(db.func.sum(AffiliateCommission.amount), 0).label("total"))
        .join(AffiliateCommission, AffiliateCommission.affiliate_id == Affiliate.id)
        .filter(AffiliateCommission.status == CommissionStatus.confirmed.value)
        .group_by(Affiliate.id, Affiliate.full_name)
        .order_by(db.text("total DESC"))
        .limit(10)
        .all()
    )

    total_affiliates = Affiliate.query.count()
    approved = Affiliate.query.filter(Affiliate.status.in_(["active", "suspended"])).count()
    with_referral = db.session.query(Affiliate.id).join(
        AffiliateReferral, AffiliateReferral.affiliate_id == Affiliate.id
    ).distinct().count()
    with_conversion = db.session.query(Affiliate.id).join(
        AffiliateReferral, AffiliateReferral.affiliate_id == Affiliate.id
    ).filter(AffiliateReferral.window_started_at.isnot(None)).distinct().count()

    return {
        "monthly_accrued": [{"month": m, "amount": str(_quantize(a))} for m, a in monthly],
        "monthly_payouts": [
            {"month": m, "net": str(_quantize(n)), "fee": str(_quantize(f)), "wht": str(_quantize(w))}
            for m, n, f, w in payouts_monthly
        ],
        "leaderboard": [
            {"affiliate_id": aid, "full_name": name, "total_earned": str(_quantize(total))}
            for aid, name, total in leaderboard
        ],
        "funnel": {
            "signed_up":  total_affiliates,
            "approved":   approved,
            "has_referral": with_referral,
            "has_conversion": with_conversion,
        },
    }
