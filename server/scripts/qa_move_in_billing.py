"""
QA helper for the move-in walkthrough (client/scripts/qa/move-in-days.mjs).

Given tenant ids, runs the REAL monthly billing engine for their units only —
September (as if someone ran it on the 30th, after they had all moved in) and
then October — and reports, per tenant, every rent line billed for September,
October and what November would bill. Prints JSON.

    APP_ENV=development PYTHONPATH=. venv/bin/python scripts/qa_move_in_billing.py 12 13 14 …

Never against production.
"""

import json
import os
import sys
from datetime import date

if (os.environ.get("APP_ENV") or "").lower() == "production":
    sys.exit("refusing to run against production")

from app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from extensions import db
    from models import Invoice, InvoiceLineItem, Landlord, Tenant
    from tasks.invoice_tasks import preview_monthly_for_tenant, run_monthly_billing_task

    ids = [int(x) for x in sys.argv[1:]]
    tenants = Tenant.query.filter(Tenant.id.in_(ids)).all()
    landlord = db.session.get(Landlord, tenants[0].landlord_id)
    units = [t.unit_id for t in tenants]

    sept = run_monthly_billing_task.run(landlord.id, "2026-09-30", None, units, None, True, True)
    octo = run_monthly_billing_task.run(landlord.id, "2026-10-01", None, units, None, True, True)

    out = {"september_run": sept, "october_run": octo, "tenants": {}}
    for t in tenants:
        rows = (db.session.query(InvoiceLineItem, Invoice)
                .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
                .filter(Invoice.tenant_id == t.id, Invoice.is_deleted.is_(False),
                        InvoiceLineItem.item == "Rent", InvoiceLineItem.subcategory == "current")
                .all())
        per_month = {}
        for li, inv in rows:
            m = (li.period_month or date(inv.issue_date.year, inv.issue_date.month, 1)).isoformat()[:7]
            per_month.setdefault(m, []).append({"amount": float(li.amount), "invoice": inv.invoice_number,
                                                "type": inv.invoice_type})
        nov = preview_monthly_for_tenant(landlord, t, date(2026, 11, 1))
        out["tenants"][str(t.id)] = {
            "move_in": t.move_in_date.isoformat() if t.move_in_date else None,
            "lease_start": t.lease_start_date.isoformat() if t.lease_start_date else None,
            "unit_rent": float(t.unit.rent_amount or 0),
            "rent_lines": per_month,
            "november_rent": nov["rent"],
        }
    print(json.dumps(out))
