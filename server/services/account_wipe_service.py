"""
services/account_wipe_service.py — Backup & Delete: start an account over.

People trying the system out load a property or two, a few tenants, a month of
payments — and then want a clean slate before loading the real thing. Deleting
a thousand rows one at a time is not a way to do that.

What goes:  every RECORD — properties and everything under them (units,
            tenants, invoices, payments and their allocations, utilities and
            queued charges, expenses, maintenance, leases, messages,
            notifications, penalties, owner payouts), plus the owners and
            groups a property manager keeps.
What stays: the account itself — login, settings, branding, automation and
            alert settings, charge categories, message and document templates,
            SMS balance, subscription and billing history, M-Pesa payment
            sources and Co-pilot devices, team members and their permissions,
            and the audit trail (which records the wipe itself).

Deletes are HARD: after a wipe nothing of the old records remains in the
database. That is why a full backup is built first, in the same request, and
nothing is deleted unless the backup was produced.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text


def account_number(landlord) -> str:
    return f"SP-{landlord.id:05d}"


def confirmation_phrase(landlord) -> str:
    return f"DELETE ACCOUNT {account_number(landlord)}"


# ---------------------------------------------------------------------------
# What is in the account
# ---------------------------------------------------------------------------

# Live records — what the owner recognises from their pages. The wipe also removes
# soft-deleted history rows, and the backup includes them.
_COUNT_SQL = {
    "properties":       "SELECT count(*) FROM properties WHERE landlord_id = :l AND NOT is_deleted",
    "units":            "SELECT count(*) FROM units u JOIN properties p ON p.id = u.property_id "
                        "WHERE p.landlord_id = :l AND NOT u.is_deleted AND NOT p.is_deleted",
    "tenants":          "SELECT count(*) FROM tenants WHERE landlord_id = :l AND NOT is_deleted",
    "invoices":         "SELECT count(*) FROM invoices WHERE landlord_id = :l AND NOT is_deleted",
    "payments":         "SELECT count(*) FROM payments WHERE landlord_id = :l AND NOT is_deleted",
    "utility_readings": "SELECT count(*) FROM utility_readings WHERE landlord_id = :l",
    "expenses":         "SELECT count(*) FROM expenses WHERE landlord_id = :l AND NOT is_deleted",
    "leases":           "SELECT count(*) FROM lease_agreements WHERE landlord_id = :l",
    "owners":           "SELECT count(*) FROM property_owners WHERE landlord_id = :l",
}


def record_counts(landlord_id: int) -> dict:
    from extensions import db
    return {k: db.session.execute(text(q), {"l": landlord_id}).scalar() or 0 for k, q in _COUNT_SQL.items()}


# ---------------------------------------------------------------------------
# The backup
# ---------------------------------------------------------------------------

def _cell(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _sheet(wb, title, rows, first=()):
    ws = wb.create_sheet(title=title[:31])
    if not rows:
        ws.append(["(none)"])
        return
    keys = list(first) + [k for k in rows[0].keys() if k not in first]
    ws.append(keys)
    for r in rows:
        ws.append([_cell(r.get(k)) for k in keys])


def build_full_backup(landlord) -> bytes:
    """One Excel workbook, a sheet per kind of record, every column."""
    from openpyxl import Workbook

    from models import (
        CommunicationLog, Expense, Invoice, InvoiceLineItem, LeaseAgreement, MaintenanceRequest,
        OwnerPayout, Payment, PaymentAllocation, Property, PropertyGroup, PropertyOwner,
        QueuedCharge, Tenant, Unit, UtilityReading,
    )

    lid = landlord.id
    props = Property.query.filter_by(landlord_id=lid).order_by(Property.name).all()
    prop_name = {p.id: p.name for p in props}
    units = (Unit.query.filter(Unit.property_id.in_(list(prop_name) or [0]))
             .order_by(Unit.property_id, Unit.name).all())
    unit_name = {u.id: u.name for u in units}
    tenants = Tenant.query.filter_by(landlord_id=lid).order_by(Tenant.last_name, Tenant.first_name).all()
    tenant_name = {t.id: f"{t.first_name} {t.last_name}" for t in tenants}

    def with_names(row, *, prop_key="property_id", unit_key="unit_id", tenant_key="tenant_id"):
        if prop_key in row:
            row["property_name"] = prop_name.get(row.get(prop_key))
        if unit_key in row:
            row["unit_name"] = unit_name.get(row.get(unit_key))
        if tenant_key in row:
            row["tenant_name"] = tenant_name.get(row.get(tenant_key))
        return row

    invoices = Invoice.query.filter_by(landlord_id=lid).order_by(Invoice.issue_date, Invoice.id).all()
    invoice_ids = [i.id for i in invoices] or [0]
    payments = Payment.query.filter_by(landlord_id=lid).order_by(Payment.payment_date, Payment.id).all()

    wb = Workbook()
    about = wb.active
    about.title = "About this backup"
    about.append(["Account", landlord.company_name])
    about.append(["Account number", account_number(landlord)])
    about.append(["Generated (UTC)", datetime.utcnow().isoformat(timespec="seconds")])
    about.append([])
    about.append(["Sheet", "Rows"])

    sheets = [
        ("Properties", [p.to_dict() for p in props], ("id", "name", "city")),
        ("Units", [with_names(u.to_dict()) for u in units], ("id", "property_name", "name", "rent_amount")),
        ("Tenants", [with_names(t.to_dict()) for t in tenants],
         ("id", "first_name", "last_name", "phone", "email", "unit_name", "account_number", "balance")),
        ("Invoices", [with_names(i.to_dict()) for i in invoices],
         ("id", "invoice_number", "tenant_name", "unit_name", "issue_date", "total_amount", "amount_paid", "balance", "status")),
        ("Invoice lines", [li.to_dict() for li in InvoiceLineItem.query.filter(
            InvoiceLineItem.invoice_id.in_(invoice_ids)).order_by(InvoiceLineItem.invoice_id).all()],
         ("id", "invoice_id", "item", "amount", "amount_paid", "status")),
        ("Payments", [with_names(p.to_dict()) for p in payments],
         ("id", "payment_ref", "tenant_name", "amount", "payment_date", "status")),
        ("Payment allocations", [a.to_dict() for a in PaymentAllocation.query.filter(
            PaymentAllocation.invoice_id.in_(invoice_ids)).all()], ()),
        ("Utility readings", [with_names(r.to_dict()) for r in UtilityReading.query.filter_by(landlord_id=lid).all()],
         ("id", "property_name", "unit_name", "utility_item", "reading_month")),
        ("Queued charges", [q.to_dict() for q in QueuedCharge.query.filter_by(landlord_id=lid).all()], ()),
        ("Expenses", [with_names(e.to_dict()) for e in Expense.query.filter_by(landlord_id=lid).all()], ()),
        ("Maintenance", [with_names(m.to_dict()) for m in MaintenanceRequest.query.filter_by(landlord_id=lid).all()], ()),
        ("Leases", [with_names(la.to_dict()) for la in LeaseAgreement.query.filter_by(landlord_id=lid).all()], ()),
        ("Owners", [o.to_dict() for o in PropertyOwner.query.filter_by(landlord_id=lid).all()], ()),
        ("Owner payouts", [o.to_dict() for o in OwnerPayout.query.filter_by(landlord_id=lid).all()], ()),
        ("Property groups", [g.to_dict() for g in PropertyGroup.query.filter_by(landlord_id=lid).all()], ()),
        ("Messages sent", [c.to_dict() for c in CommunicationLog.query.filter_by(landlord_id=lid)
                           .order_by(CommunicationLog.id).all()], ()),
    ]
    for title, rows, first in sheets:
        _sheet(wb, title, rows, first)
        about.append([title, len(rows)])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# The wipe
# ---------------------------------------------------------------------------

# Children before parents. Each statement is scoped to one landlord.
_PROPS = "(SELECT id FROM properties WHERE landlord_id = :l)"
_UNITS = f"(SELECT id FROM units WHERE property_id IN {_PROPS})"
_TENANTS = "(SELECT id FROM tenants WHERE landlord_id = :l)"
_INVOICES = "(SELECT id FROM invoices WHERE landlord_id = :l)"
_PAYMENTS = "(SELECT id FROM payments WHERE landlord_id = :l)"

_WIPE_STEPS: list[tuple[str, str]] = [
    ("payment_allocations", f"DELETE FROM payment_allocations WHERE payment_id IN {_PAYMENTS} OR invoice_id IN {_INVOICES}"),
    ("credit_ledger", "DELETE FROM credit_ledger WHERE landlord_id = :l"),
    ("balance_rollovers", "DELETE FROM balance_rollovers WHERE landlord_id = :l"),
    ("allocation_audit", "DELETE FROM allocation_audit WHERE landlord_id = :l"),
    ("copilot_messages", "DELETE FROM copilot_messages WHERE landlord_id = :l"),
    ("bank_statement_transactions", "DELETE FROM bank_statement_transactions WHERE bank_statement_id IN "
                                    "(SELECT id FROM bank_statement_uploads WHERE landlord_id = :l)"),
    ("queued_charges", "DELETE FROM queued_charges WHERE landlord_id = :l"),
    ("invoice_line_items", f"DELETE FROM invoice_line_items WHERE invoice_id IN {_INVOICES}"),
    ("penalty_charges", "DELETE FROM penalty_charges WHERE landlord_id = :l"),
    ("mpesa_transactions", "DELETE FROM mpesa_transactions WHERE landlord_id = :l"),
    ("payout_lines", "DELETE FROM payout_lines WHERE payout_id IN (SELECT id FROM owner_payouts WHERE landlord_id = :l)"),
    ("owner_payouts", "DELETE FROM owner_payouts WHERE landlord_id = :l"),
    ("-", "UPDATE expenses SET maintenance_request_id = NULL WHERE landlord_id = :l"),
    ("-", "UPDATE maintenance_requests SET expense_id = NULL WHERE landlord_id = :l"),
    ("maintenance_comments", "DELETE FROM maintenance_comments WHERE request_id IN "
                             "(SELECT id FROM maintenance_requests WHERE landlord_id = :l)"),
    ("maintenance_requests", "DELETE FROM maintenance_requests WHERE landlord_id = :l"),
    ("expenses", "DELETE FROM expenses WHERE landlord_id = :l"),
    ("recurring_expenses", "DELETE FROM recurring_expenses WHERE landlord_id = :l"),
    ("utility_readings", "DELETE FROM utility_readings WHERE landlord_id = :l"),
    ("payments", "DELETE FROM payments WHERE landlord_id = :l"),
    ("invoices", "DELETE FROM invoices WHERE landlord_id = :l"),
    ("bank_statement_uploads", "DELETE FROM bank_statement_uploads WHERE landlord_id = :l"),
    ("lease_agreements", "DELETE FROM lease_agreements WHERE landlord_id = :l"),
    ("tenant_documents", f"DELETE FROM tenant_documents WHERE tenant_id IN {_TENANTS}"),
    ("tenant_unit_history", f"DELETE FROM tenant_unit_history WHERE tenant_id IN {_TENANTS} OR unit_id IN {_UNITS}"),
    ("tenant_messages", "DELETE FROM tenant_messages WHERE landlord_id = :l"),
    ("communication_logs", "DELETE FROM communication_logs WHERE landlord_id = :l"),
    ("notifications", f"DELETE FROM notifications WHERE landlord_id = :l OR recipient_tenant_id IN {_TENANTS}"),
    ("tenants", "DELETE FROM tenants WHERE landlord_id = :l"),
    ("recurring_bills", "DELETE FROM recurring_bills WHERE landlord_id = :l"),
    ("unit_pay_code_aliases", "DELETE FROM unit_pay_code_aliases WHERE landlord_id = :l"),
    ("manager_assignments", f"DELETE FROM manager_assignments WHERE property_id IN {_PROPS} OR unit_id IN {_UNITS} "
                            "OR property_group_id IN (SELECT id FROM property_groups WHERE landlord_id = :l)"),
    ("team_member_property_access", f"DELETE FROM team_member_property_access WHERE property_id IN {_PROPS}"),
    ("team_member_property_permissions", f"DELETE FROM team_member_property_permissions WHERE property_id IN {_PROPS}"),
    ("units", f"DELETE FROM units WHERE property_id IN {_PROPS}"),
    ("penalty_tiers", "DELETE FROM penalty_tiers WHERE policy_id IN "
                      "(SELECT id FROM property_penalty_policies WHERE landlord_id = :l)"),
    ("property_penalty_policies", "DELETE FROM property_penalty_policies WHERE landlord_id = :l"),
    ("-", "UPDATE payment_sources SET mapped_property_id = NULL, mapped_owner_id = NULL WHERE landlord_id = :l"),
    ("properties", "DELETE FROM properties WHERE landlord_id = :l"),
    ("property_groups", "DELETE FROM property_groups WHERE landlord_id = :l"),
    ("property_owners", "DELETE FROM property_owners WHERE landlord_id = :l"),
]


def wipe_records(landlord_id: int) -> dict:
    """
    Hard-delete every record of the account (see module docstring for what
    stays). Runs in the caller's transaction; the caller commits or rolls back.
    Tenant logins that no longer hold any tenancy anywhere are removed too.
    """
    from extensions import db

    tenant_users = [uid for (uid,) in db.session.execute(
        text("SELECT DISTINCT user_id FROM tenants WHERE landlord_id = :l AND user_id IS NOT NULL"),
        {"l": landlord_id})]

    deleted = {}
    for table, sql in _WIPE_STEPS:
        result = db.session.execute(text(sql), {"l": landlord_id})
        if table != "-":
            deleted[table] = result.rowcount or 0

    deleted["tenant_logins"] = 0
    if tenant_users:
        # A login still named in the audit trail stays: it has no tenancy left to
        # open, and the audit trail must keep pointing at a real user.
        orphaned = [uid for (uid,) in db.session.execute(
            text("SELECT u.id FROM users u WHERE u.id = ANY(:ids) AND u.role = 'tenant' "
                 "AND NOT EXISTS (SELECT 1 FROM tenants t WHERE t.user_id = u.id) "
                 "AND NOT EXISTS (SELECT 1 FROM audit_logs a WHERE a.actor_user_id = u.id)"),
            {"ids": tenant_users})]
        if orphaned:
            try:
                with db.session.begin_nested():
                    for sql in ("DELETE FROM otp_tokens WHERE user_id = ANY(:ids)",
                                "DELETE FROM user_preferences WHERE user_id = ANY(:ids)",
                                "DELETE FROM notifications WHERE recipient_user_id = ANY(:ids) OR sender_user_id = ANY(:ids)",
                                "DELETE FROM users WHERE id = ANY(:ids)"):
                        db.session.execute(text(sql), {"ids": orphaned})
                deleted["tenant_logins"] = len(orphaned)
            except Exception:
                import logging
                logging.getLogger(__name__).warning("wipe: kept %d tenant logins still referenced elsewhere",
                                                    len(orphaned), exc_info=True)

    db.session.flush()
    return deleted
