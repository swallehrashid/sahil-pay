"""
services/tenant_score_service.py — how reliably has this tenant paid rent?

A percentage out of 100, averaged over every completed month of the tenancy, so
a landlord can tell at a glance whether somebody has paid on time for two years
or has been chased every month. A high score is evidence of reliability — the
kind of thing that should qualify a tenant for credit; a low one is evidence of
the opposite.

Scoring (OPUS_EXECUTION_SPEC Phase 4.1):

  For each completed month, score by the day of the month the month's RENT was
  fully cleared:

      day 1–5   → 100      day 16–20 → 70
      day 6–10  →  90      day 21–25 → 60
      day 11–15 →  80      day 26+   → 50

  Cleared in a LATER month, or never → 0 for that month.

  Then subtract 5 points for every month that ENDED with rent arrears still
  outstanding, capped at −20 so one bad patch cannot erase a long good record.

Only RENT counts — deposits are refundable money the tenant lends the landlord,
and utilities vary with meters and seasons; neither says anything about whether
somebody pays their rent. A tenant with fewer than two completed months has no
meaningful history and scores None ("New") rather than a flattering 100.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

# (inclusive day-of-month upper bound, score)
SCORE_BANDS: tuple[tuple[int, int], ...] = (
    (5, 100),
    (10, 90),
    (15, 80),
    (20, 70),
    (25, 60),
    (31, 50),
)

ARREARS_PENALTY_PER_MONTH = 5
MAX_ARREARS_PENALTY = 20
MIN_MONTHS_FOR_SCORE = 2


def band_for_day(day: int) -> int:
    """The score for rent cleared on `day` of its own month."""
    for upper, score in SCORE_BANDS:
        if day <= upper:
            return score
    return 50


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _tenancy_start(tenant) -> date | None:
    """When this tenancy's scoring history begins."""
    for candidate in (tenant.move_in_date, tenant.lease_start_date):
        if candidate:
            return _month_start(candidate)

    earliest = None
    for invoice in tenant.invoices:
        if invoice.is_deleted or not invoice.issue_date:
            continue
        if earliest is None or invoice.issue_date < earliest:
            earliest = invoice.issue_date
    return _month_start(earliest) if earliest else None


def compute_tenant_score(tenant) -> dict:
    """
    The tenant's score plus the month-by-month working behind it.

    Returns:
        {score, months: [...], penalty, on_time_rate, avg_pay_day,
         months_counted, reason}
    `score` is None when there is not enough history to judge.
    """
    from models import InvoiceLineItem, PaymentAllocation, Payment, PaymentStatus
    from services.category_service import rent_category_id

    empty = {
        "score": None, "months": [], "penalty": 0,
        "on_time_rate": None, "avg_pay_day": None,
        "months_counted": 0, "reason": "new_tenant",
    }

    start = _tenancy_start(tenant)
    if start is None:
        return empty

    today = date.today()
    # Only COMPLETED months are judged — the current month is still in play and
    # scoring it would punish everyone who simply hasn't paid yet this month.
    last_complete = _month_start(today) - relativedelta(months=1)
    if last_complete < start:
        return empty

    rent_cat = rent_category_id(tenant.landlord_id)
    if rent_cat is None:
        return empty

    # ---- Gather this tenant's rent lines, month by month --------------------
    # A month's rent is the 'current' rent line(s) on invoices issued in it.
    rent_lines_by_month: dict[str, list] = {}
    arrears_months: set[str] = set()

    for invoice in tenant.invoices:
        if invoice.is_deleted or not invoice.issue_date:
            continue
        key = invoice.issue_date.strftime("%Y-%m")
        for line in invoice.line_items:
            if line.category_id != rent_cat:
                continue
            subcategory = (line.subcategory or "").lower()
            if subcategory == "current":
                rent_lines_by_month.setdefault(key, []).append(line)
            elif subcategory == "balance" and (line.amount or 0) > 0:
                # A rent arrears line means the PREVIOUS month closed unpaid.
                previous = _month_start(invoice.issue_date) - relativedelta(months=1)
                arrears_months.add(previous.strftime("%Y-%m"))

    if not rent_lines_by_month:
        return empty

    # ---- When was each month's rent actually cleared? ----------------------
    line_ids = [li.id for month_lines in rent_lines_by_month.values() for li in month_lines]
    allocations_by_line: dict[int, list[tuple[date, Decimal]]] = {}
    if line_ids:
        from extensions import db

        rows = (
            db.session.query(
                PaymentAllocation.line_item_id,
                Payment.payment_date,
                PaymentAllocation.amount_allocated,
            )
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .filter(
                PaymentAllocation.line_item_id.in_(line_ids),
                Payment.is_deleted.is_(False),
                Payment.status == PaymentStatus.confirmed.value,
            )
            .order_by(Payment.payment_date.asc())
            .all()
        )
        for line_id, paid_on, amount in rows:
            allocations_by_line.setdefault(line_id, []).append(
                (paid_on, Decimal(str(amount or 0)))
            )

    months = []
    pay_days = []
    cursor = start
    while cursor <= last_complete:
        key = cursor.strftime("%Y-%m")
        lines = rent_lines_by_month.get(key, [])
        if not lines:
            cursor += relativedelta(months=1)
            continue

        rent_due = sum((Decimal(str(li.amount or 0)) for li in lines), Decimal("0"))
        if rent_due <= 0:
            cursor += relativedelta(months=1)
            continue

        # The date cumulative payments first covered the month's rent in full.
        events: list[tuple[date, Decimal]] = []
        for li in lines:
            events.extend(allocations_by_line.get(li.id, []))
        events.sort(key=lambda e: e[0])

        running = Decimal("0")
        cleared_on = None
        for paid_on, amount in events:
            running += amount
            if running >= rent_due:
                cleared_on = paid_on
                break

        month_end = (cursor + relativedelta(months=1)) - relativedelta(days=1)
        if cleared_on is None:
            band = 0                      # never cleared
        elif cleared_on > month_end:
            band = 0                      # cleared, but in a later month
        else:
            band = band_for_day(cleared_on.day)
            pay_days.append(cleared_on.day)

        months.append({
            "month":      key,
            "rent_due":   float(rent_due),
            "paid_on":    cleared_on.isoformat() if cleared_on else None,
            "paid_day":   cleared_on.day if (cleared_on and cleared_on <= month_end) else None,
            "band_score": band,
            "had_arrears": key in arrears_months,
        })
        cursor += relativedelta(months=1)

    if len(months) < MIN_MONTHS_FOR_SCORE:
        return {**empty, "months": months, "months_counted": len(months)}

    average = sum(m["band_score"] for m in months) / len(months)
    penalty = min(
        sum(ARREARS_PENALTY_PER_MONTH for m in months if m["had_arrears"]),
        MAX_ARREARS_PENALTY,
    )
    score = max(0, min(100, round(average - penalty)))

    on_time = sum(1 for m in months if m["band_score"] == 100)
    return {
        "score":          score,
        "months":         months,
        "penalty":        penalty,
        "on_time_rate":   round(on_time / len(months) * 100, 1),
        "avg_pay_day":    round(sum(pay_days) / len(pay_days), 1) if pay_days else None,
        "months_counted": len(months),
        "reason":         None,
    }


def refresh_tenant_score(tenant, *, commit: bool = False):
    """
    Recompute and persist one tenant's score. Does not commit unless asked —
    callers own the transaction, like every other service here.
    """
    from datetime import datetime

    from extensions import db

    result = compute_tenant_score(tenant)
    tenant.tenant_score = result["score"]
    tenant.tenant_score_updated_at = datetime.utcnow()
    db.session.flush()
    if commit:
        db.session.commit()
    return result


def refresh_scores_for_landlord(landlord_id: int, *, chunk: int = 200) -> int:
    """Recompute every active tenant's score for one landlord. Returns the count."""
    from extensions import db
    from models import Tenant

    tenants = Tenant.query.filter_by(landlord_id=landlord_id, is_deleted=False).all()
    for index, tenant in enumerate(tenants, start=1):
        refresh_tenant_score(tenant)
        if index % chunk == 0:
            db.session.commit()
    db.session.commit()
    return len(tenants)


def score_label(score) -> str:
    """The human reading of a score — shared by every portal's badge."""
    if score is None:
        return "New"
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "High risk"
