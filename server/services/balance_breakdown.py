"""
services/balance_breakdown.py — the single source of truth for "where a
tenant's balance came from".

Both the tenant dashboard (routes/tenant_portal_routes.py) and every default
reminder communication (invoice / overdue / payment-reminder — see
services/reminder_templates.py) render the SAME itemised breakdown so a tenant
who reads the dashboard and a tenant who reads an SMS/email/in-app reminder see
identical numbers that always reconcile to their total outstanding.

The breakdown is driven by INVOICE LINE ITEMS, not by the coarse invoice_type
bucket. Each open line item carries:
  - item        : human label ("Rent", "Water Deposit", "Garbage", …)
  - subcategory : deposit | balance | current  (SubCategory enum)
  - remaining   : amount - amount_paid
so we can group precisely into "Rent", "Rent Balance b/f", "Water Deposit",
"Water", "Electricity", etc. Invoices with no line items fall back to their
header (title / invoice_type / balance) so nothing is ever silently dropped.
"""

from decimal import Decimal

from models import InvoiceStatus, SubCategory, LineItemStatus


# How each subcategory is surfaced to the tenant, appended to the item label.
_SUBCATEGORY_SUFFIX = {
    SubCategory.deposit.value: "Deposit",
    SubCategory.balance.value: "Balance b/f",
    SubCategory.current.value: "",
}

# Deposits are refundable money held, not an arrears the tenant is "behind" on —
# we surface them in their own group so a reminder can say so.
_DEPOSIT_SUB = SubCategory.deposit.value


def _label_for_line(li) -> str:
    """Build the display label for a single open line item."""
    base = (li.item or "Charge").strip()
    suffix = _SUBCATEGORY_SUFFIX.get((li.subcategory or "").lower(), "")
    if not suffix:
        return base
    # Avoid "Water Deposit Deposit" if item already contains the word.
    if suffix.split()[0].lower() in base.lower():
        return base
    return f"{base} {suffix}"


def build_breakdown(tenant) -> dict:
    """
    Return a fully-itemised outstanding-balance breakdown for `tenant`.

    Shape:
      {
        "total_due":  Decimal-as-float, sum of all open remaining amounts,
        "deposits_due": float,     # refundable deposits portion of total_due
        "arrears_due":  float,     # everything that is NOT a deposit
        "items": [                 # one row per (label) group, largest first
            {"label": "Rent", "amount": 10000.0, "is_deposit": False,
             "subcategory": "current"},
            ...
        ],
        "invoices": [              # per-invoice detail, oldest first
            {"id", "invoice_number", "title", "type", "issue_date",
             "due_date", "balance", "is_overdue",
             "lines": [{"label","amount","subcategory","is_deposit"}...]},
            ...
        ],
      }
    """
    from datetime import date

    open_invoices = [
        inv for inv in tenant.invoices
        if not inv.is_deleted
        and inv.status in (InvoiceStatus.open.value, InvoiceStatus.partial.value)
    ]
    open_invoices.sort(key=lambda x: (x.issue_date or date.min))

    today = date.today()
    groups: dict[str, dict] = {}
    invoices_out: list[dict] = []
    total = Decimal("0")
    deposits_total = Decimal("0")

    def _add_group(label, amount, subcategory, is_deposit):
        g = groups.setdefault(
            label,
            {"label": label, "amount": Decimal("0"),
             "is_deposit": is_deposit, "subcategory": subcategory},
        )
        g["amount"] += amount

    for inv in open_invoices:
        inv_lines_out = []
        # Prefer line-item level detail; fall back to the invoice header.
        open_lines = [
            li for li in inv.line_items
            if (li.status or "").lower() != LineItemStatus.rolled.value
            and (li.remaining or Decimal("0")) > 0
        ]

        if open_lines:
            for li in open_lines:
                remaining = li.remaining or Decimal("0")
                label = _label_for_line(li)
                is_dep = (li.subcategory or "").lower() == _DEPOSIT_SUB
                total += remaining
                if is_dep:
                    deposits_total += remaining
                _add_group(label, remaining, li.subcategory, is_dep)
                inv_lines_out.append({
                    "label": label,
                    "amount": float(remaining),
                    "subcategory": li.subcategory,
                    "is_deposit": is_dep,
                })
        else:
            # No line items — use the invoice header so the amount still shows.
            bal = (inv.balance if inv.balance is not None
                   else (inv.total_amount or Decimal("0")) - (inv.amount_paid or Decimal("0")))
            bal = bal or Decimal("0")
            if bal > 0:
                is_dep = (inv.invoice_type or "").lower() == "deposit"
                label = (inv.title or inv.invoice_type or "Charge").strip()
                total += bal
                if is_dep:
                    deposits_total += bal
                _add_group(label, bal, "current", is_dep)
                inv_lines_out.append({
                    "label": label,
                    "amount": float(bal),
                    "subcategory": "current",
                    "is_deposit": is_dep,
                })

        invoices_out.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "title": inv.title or inv.invoice_type,
            "type": inv.invoice_type,
            "issue_date": str(inv.issue_date) if inv.issue_date else None,
            "due_date": str(inv.due_date) if inv.due_date else None,
            "balance": float(inv.balance or 0),
            "is_overdue": bool(inv.due_date and inv.due_date < today),
            "lines": inv_lines_out,
        })

    items = sorted(
        (
            {
                "label": g["label"],
                "amount": float(g["amount"]),
                "is_deposit": g["is_deposit"],
                "subcategory": g["subcategory"],
            }
            for g in groups.values()
        ),
        key=lambda x: (x["is_deposit"], -x["amount"]),  # non-deposits first, largest first
    )

    return {
        "total_due": float(total),
        "deposits_due": float(deposits_total),
        "arrears_due": float(total - deposits_total),
        "items": items,
        "invoices": invoices_out,
    }


def breakdown_as_lines(breakdown: dict, currency: str = "KES") -> list[str]:
    """
    Render the itemised breakdown as plain text lines, e.g.
        Rent — KES 10,000.00
        Water — KES 4,200.00
        Water Deposit — KES 5,000.00
    Used by SMS / in-app / plain-text email reminders so no reminder is ever
    "just a number".
    """
    lines = []
    for it in breakdown.get("items", []):
        lines.append(f"{it['label']} — {currency} {it['amount']:,.2f}")
    return lines
