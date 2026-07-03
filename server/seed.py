"""
SahilPay — seed.py
===================
Extensive, multi-landlord test fixture covering every portal (system admin,
landlord, team member, tenant) with realistic, financially-consistent data.

IMPORTANT — this is a DESTRUCTIVE reset, not an idempotent merge:
    python seed.py
TRUNCATEs every business table (RESTART IDENTITY CASCADE) and rebuilds from
scratch. This guarantees a known, reproducible fixture every time you run it
— exactly what you want when "extensively testing" rather than accumulating
drift across runs. Never point this at a production database.

What it builds
---------------
  Platform        — global TrialConfig, 3 Packages (Starter/Growth/Scale)
  System Admin    — 1 admin account
  4 Landlords     — deliberately varied account states:
                      Acme Properties Ltd      — active, paid, Growth plan
                      Sunrise Estates          — on trial (20 days left)
                      Pioneer Housing Group    — SUSPENDED (policy violation)
                      Coastal Rentals          — trial expiring in 2 days
                      (+ a per-landlord TrialConfig override on Coastal)
  Per landlord    — 2 properties (1 grouped via PropertyGroup), units mixing
                    occupied/vacant, occupied-unit tenants with 3 months of
                    invoice+payment history covering every balance scenario
                    (paid in full / arrears / partial / advance credit), one
                    moved-out tenant, one soft-deleted tenant, utility
                    readings, expenses (+1 recurring), maintenance requests
                    (incl. one converted to an expense), message + document
                    templates, 2 team members with DIFFERENT permission
                    profiles, and billing transaction history.

Ledger convention (see routes/payment_routes.py, landlord_dashboard_routes.py):
    tenant.balance < 0  → arrears (tenant owes money)
    tenant.balance > 0  → advance / credit
    tenant.balance == 0 → settled
Every invoice created here mirrors tasks/invoice_tasks.py's `balance -= total`;
every payment mirrors payment_routes.py's `balance += amount`.

Usage
-----
    python seed.py
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app import create_app
from extensions import db

app = create_app()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

_ALL_TABLES = [
    "users", "system_admins", "landlords", "team_members", "team_member_permissions",
    "team_member_property_access", "otp_tokens", "property_groups", "properties", "units",
    "recurring_bills", "manager_assignments", "tenants", "tenant_unit_history", "tenant_documents",
    "invoices", "invoice_line_items", "bank_statement_uploads", "payments", "payment_allocations",
    "bank_statement_transactions", "mpesa_transactions", "recurring_expenses", "expenses",
    "utility_readings", "maintenance_requests", "message_templates", "communication_logs",
    "document_templates", "packages", "subscriptions", "billing_transactions", "trial_configs",
    "impersonation_requests", "landlord_settings", "automation_settings", "alert_settings",
    "audit_logs", "backups", "notifications",
]


def reset_all_data() -> None:
    """Wipe every business table so each run starts from a known, clean slate."""
    from sqlalchemy import text

    db.session.execute(text(f"TRUNCATE TABLE {', '.join(_ALL_TABLES)} RESTART IDENTITY CASCADE;"))
    db.session.commit()
    print("─── All tables truncated — starting from a clean slate ───\n")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _first_of_month(d: date, months_ago: int = 0) -> date:
    return (d.replace(day=1) - relativedelta(months=months_ago))


def _create_user(m, email, phone, role, password=None, is_verified=True, is_active=True):
    from utils import hash_password

    user = m.User(
        email=email,
        phone=phone,
        role=role,
        password_hash=hash_password(password) if password else None,
        is_verified=is_verified,
        is_active=is_active,
    )
    db.session.add(user)
    db.session.flush()
    return user


# ---------------------------------------------------------------------------
# Landlord + property structure
# ---------------------------------------------------------------------------

def _create_landlord(m, spec, packages, today) -> "m.Landlord":
    user = _create_user(
        m, spec["email"], spec["phone"], m.UserRole.landlord.value,
        password=spec["password"], is_active=spec.get("user_active", True),
    )
    landlord = m.Landlord(
        user_id=user.id,
        company_name=spec["company_name"],
        abbreviated_name=spec["abbreviated_name"],
        company_address=spec.get("address"),
        currency="KES",
        timezone="Africa/Nairobi",
        mpesa_type=m.MpesaType.paybill.value,
        mpesa_number=spec["mpesa_number"],
        default_account_number=spec["abbreviated_name"].upper(),
        account_type=m.AccountType.landlord.value,
        default_tax_rate=Decimal("7.50"),
        agent_code=f"{spec['abbreviated_name'].upper()}-AGENT-001",
        sms_balance=spec.get("sms_balance", 200),
        package_id=packages[spec["package"]].id,
        trial_ends_at=spec["trial_ends_at"],
        is_on_trial=spec["is_on_trial"],
    )
    db.session.add(landlord)
    db.session.flush()

    db.session.add(m.LandlordSettings(
        landlord_id=landlord.id, sms_enabled=True, whatsapp_enabled=False,
        email_enabled=True, low_sms_balance_threshold=50,
    ))
    db.session.add(m.AutomationSettings(
        landlord_id=landlord.id,
        auto_generate_recurring_invoices=True, auto_generate_recurring_bills=True,
        alert_on_new_tenant=True, auto_send_payment_acknowledgments=True,
        monthly_reminders_enabled=True, monthly_reminder_day=1,
        lease_expiry_notifications=True, lease_expiry_range_days=30,
    ))

    unit_count = spec["unit_count_for_subscription"]
    cost = (packages[spec["package"]].price_per_unit or Decimal("0")) * unit_count
    db.session.add(m.Subscription(
        landlord_id=landlord.id,
        plan=m.SubscriptionPlan.monthly.value,
        unit_count=unit_count,
        subscription_cost=cost,
        billing_cycle=m.BillingCycle.monthly.value,
        discount_rate=Decimal("0.00"),
        amount_due=Decimal("0.00") if spec["sub_status"] != "past_due" else cost,
        next_billing_date=_first_of_month(today, -1),
        status=spec["sub_status"],
    ))

    for alert_type in (m.AlertType.payment, m.AlertType.arrears, m.AlertType.lease_expiry):
        db.session.add(m.AlertSetting(
            landlord_id=landlord.id, alert_type=alert_type.value, is_enabled=True,
            cadence=m.AlertCadence.daily.value, channel=m.AlertChannel.dashboard.value,
        ))

    db.session.flush()
    return landlord


def _create_property_with_units(m, landlord, prop_spec, group_id):
    prop = m.Property(
        landlord_id=landlord.id,
        property_group_id=group_id,
        name=prop_spec["name"],
        number_of_units=len(prop_spec["units"]),
        city=prop_spec["city"],
        street_name=prop_spec["street"],
        water_rate=Decimal(str(prop_spec.get("water_rate", 100))),
        electricity_rate=Decimal(str(prop_spec.get("electricity_rate", 25))),
        tax_rate=Decimal("7.50"),
        management_fee=Decimal("5000.00"),
        owner_phone=landlord.mpesa_number,
    )
    db.session.add(prop)
    db.session.flush()

    units = {}
    for u in prop_spec["units"]:
        unit = m.Unit(
            property_id=prop.id, name=u["name"], rent_amount=Decimal(str(u["rent"])),
            is_occupied=u["occupied"],
        )
        db.session.add(unit)
        db.session.flush()
        units[u["name"]] = unit
    return prop, units


# ---------------------------------------------------------------------------
# Tenants + financial history
# ---------------------------------------------------------------------------

def _create_tenant(m, landlord, unit, t_spec, today):
    user = _create_user(m, t_spec.get("email"), t_spec["phone"], m.UserRole.tenant.value, password=None, is_verified=False)
    tenant = m.Tenant(
        user_id=user.id, landlord_id=landlord.id, unit_id=unit.id,
        first_name=t_spec["first_name"], last_name=t_spec["last_name"],
        phone=t_spec["phone"], email=t_spec.get("email"),
        account_number=t_spec["account_number"],
        deposit_amount=unit.rent_amount, deposit_paid=unit.rent_amount, deposit_returned=Decimal("0.00"),
        balance=Decimal("0.00"),
        lease_start_date=t_spec["move_in"], lease_expiry_date=t_spec["move_in"] + relativedelta(years=1),
        move_in_date=t_spec["move_in"], move_out_date=t_spec.get("move_out"),
        is_deleted=t_spec.get("is_deleted", False),
        deleted_at=today if t_spec.get("is_deleted") else None,
    )
    db.session.add(tenant)
    db.session.flush()

    db.session.add(m.TenantUnitHistory(
        tenant_id=tenant.id, unit_id=unit.id,
        moved_in_at=t_spec["move_in"], moved_out_at=t_spec.get("move_out"),
    ))
    db.session.flush()
    return tenant


def _seed_financial_history(m, landlord, tenant, unit, prop, scenario, today, months=3):
    """
    Builds `months` rent invoices (oldest -> newest) and matching payments per
    scenario, mutating tenant.balance with the SAME formula the live routes use:
    invoice issued -> balance -= total; payment recorded -> balance += amount.
    """
    from utils import gen_reference

    rent = unit.rent_amount
    unpaid_recent = 1 if scenario == "arrears" else 0

    for i in range(months - 1, -1, -1):  # oldest first
        issue_date = _first_of_month(today, i)
        due_date = issue_date + timedelta(days=5)
        month_label = issue_date.strftime("%B %Y")

        # Categorized charges so property/tenant statements have real per-item
        # breakdowns (rent + utilities + service/security, and a late penalty on
        # the current unpaid month for arrears/partial tenants).
        water = (Decimal("1000") + Decimal(i * 150)).quantize(Decimal("1"))  # varies month to month
        charges = [
            ("Rent",          f"Monthly rent for {month_label}",      rent),
            ("Water",         f"Water usage for {month_label}",       water),
            ("Garbage",       "Garbage collection",                   Decimal("300")),
            ("Service Charge","Common-area service charge",           Decimal("2000")),
            ("Security",      "Security services",                    Decimal("1500")),
        ]
        is_most_recent = (i == 0)
        if is_most_recent and scenario in ("arrears", "partial"):
            charges.append(("Penalty", "Late payment penalty", Decimal("500")))

        invoice_total = sum((amt for _, _, amt in charges), Decimal("0"))

        invoice = m.Invoice(
            invoice_number=gen_reference("INV"), landlord_id=landlord.id, tenant_id=tenant.id,
            unit_id=unit.id, property_id=prop.id, invoice_type=m.InvoiceType.rent.value,
            issue_date=issue_date, due_date=due_date, status=m.InvoiceStatus.open.value,
            total_amount=invoice_total, amount_paid=Decimal("0.00"), balance=invoice_total,
            title=f"Rent & charges — {month_label}",
        )
        db.session.add(invoice)
        db.session.flush()
        for item, desc, amt in charges:
            db.session.add(m.InvoiceLineItem(
                invoice_id=invoice.id, item=item, description=desc,
                quantity=Decimal("1"), unit_price=amt, amount=amt,
            ))
        tenant.balance = (tenant.balance or Decimal("0")) - invoice_total

        pay_amount = Decimal("0")
        if scenario == "arrears" and is_most_recent and unpaid_recent:
            pay_amount = Decimal("0")  # leave this month's invoice fully unpaid
        elif scenario == "partial" and is_most_recent:
            pay_amount = (invoice_total / 2).quantize(Decimal("1"))  # half-paid most recent month
        else:
            pay_amount = invoice_total  # paid / advance: every month paid in full

        if pay_amount > 0:
            payment = m.Payment(
                payment_ref=gen_reference("PMT"), landlord_id=landlord.id, tenant_id=tenant.id,
                unit_id=unit.id, property_id=prop.id, amount=pay_amount, payment_date=issue_date,
                status=m.PaymentStatus.confirmed.value, source=m.PaymentSource.mpesa.value,
                payment_method="M-Pesa", mpesa_reference=gen_reference("QA")[:20],
            )
            db.session.add(payment)
            db.session.flush()
            db.session.add(m.PaymentAllocation(
                payment_id=payment.id, invoice_id=invoice.id, amount_allocated=pay_amount,
            ))
            invoice.amount_paid = pay_amount
            invoice.balance = invoice.total_amount - pay_amount
            invoice.status = (
                m.InvoiceStatus.paid.value if invoice.balance <= 0 else m.InvoiceStatus.partial.value
            )
            tenant.balance = (tenant.balance or Decimal("0")) + pay_amount

    if scenario == "advance":
        # One extra unallocated overpayment on top of fully-paid invoices -> pure credit.
        extra = (rent * Decimal("0.3")).quantize(Decimal("1"))
        payment = m.Payment(
            payment_ref=gen_reference("PMT"), landlord_id=landlord.id, tenant_id=tenant.id,
            unit_id=unit.id, property_id=prop.id, amount=extra, payment_date=today,
            status=m.PaymentStatus.confirmed.value, source=m.PaymentSource.manual.value,
            payment_method="Bank transfer", notes="Advance payment toward next month's rent.",
        )
        db.session.add(payment)
        tenant.balance = (tenant.balance or Decimal("0")) + extra

    db.session.flush()


# ---------------------------------------------------------------------------
# Team members
# ---------------------------------------------------------------------------

def _create_team_member(m, landlord, tm_spec, property_ids):
    user = _create_user(
        m, tm_spec["email"], tm_spec["phone"], m.UserRole.team_member.value,
        password=tm_spec["password"], is_verified=True,
    )
    tm = m.TeamMember(
        user_id=user.id, landlord_id=landlord.id, username=tm_spec["username"],
        first_name=tm_spec["first_name"], last_name=tm_spec["last_name"], phone=tm_spec["phone"],
        role=tm_spec["role"], property_access_all=tm_spec["property_access_all"], is_active=True,
    )
    db.session.add(tm)
    db.session.flush()

    perms = dict(tm_spec["permissions"])

    # Backfill the four first-class modules added later (expenses, maintenance,
    # reports, groups) with role-based defaults when a spec predates them, so
    # every seeded member can exercise those pages. Editors get view+edit;
    # viewers get view-only; reports is inherently read-only for both.
    is_editor = tm_spec["role"] == "editor"
    for mod in ("expenses", "maintenance", "groups"):
        perms.setdefault(mod, (True, is_editor))
    perms.setdefault("reports", (True, False))

    for module, (can_view, can_edit) in perms.items():
        db.session.add(m.TeamMemberPermission(
            team_member_id=tm.id, module=module, can_view=can_view, can_edit=can_edit,
        ))

    if not tm_spec["property_access_all"]:
        for pid in tm_spec["scoped_property_ids"](property_ids):
            db.session.add(m.TeamMemberPropertyAccess(team_member_id=tm.id, property_id=pid))

    db.session.flush()
    return tm


# ---------------------------------------------------------------------------
# Operations: utilities, expenses, maintenance, templates, billing
# ---------------------------------------------------------------------------

def _seed_operations(m, landlord, prop, units_by_name, occupied_unit_names, today):
    # Utility readings — water + electricity, current + previous month, for occupied units.
    for uname in occupied_unit_names[:2]:
        unit = units_by_name[uname]
        for item, base in ((m.UtilityItem.water, Decimal("80")), (m.UtilityItem.electricity, Decimal("150"))):
            prev_reading = base
            for i in (1, 0):
                month = _first_of_month(today, i).strftime("%Y-%m")
                current = prev_reading + Decimal("12")
                db.session.add(m.UtilityReading(
                    landlord_id=landlord.id, property_id=prop.id, unit_id=unit.id,
                    utility_item=item.value, previous_reading=prev_reading, current_reading=current,
                    consumption=current - prev_reading, reading_month=month, invoice_id=None,
                ))
                prev_reading = current
    db.session.flush()

    # Recurring expense template + one instantiated Expense linked to it.
    recurring = m.RecurringExpense(
        landlord_id=landlord.id, property_id=prop.id, unit_id=None,
        category=m.ExpenseCategory.security.value, amount=Decimal("8000.00"),
        payment_method="cash", notes="Monthly security guard fee.", day_of_month=1, is_active=True,
    )
    db.session.add(recurring)
    db.session.flush()

    expenses = [
        {"category": m.ExpenseCategory.security, "amount": "8000.00", "recurring": recurring,
         "notes": "Security guard — monthly instance of recurring template."},
        {"category": m.ExpenseCategory.garbage, "amount": "3500.00", "recurring": None,
         "notes": "Garbage collection contract."},
        {"category": m.ExpenseCategory.cleaning, "amount": "4200.00", "recurring": None,
         "notes": "Common-area cleaning service."},
        {"category": m.ExpenseCategory.electricity, "amount": "12500.00", "recurring": None,
         "notes": "Common-area electricity bill."},
    ]
    created_expenses = []
    for i, e in enumerate(expenses):
        exp = m.Expense(
            landlord_id=landlord.id, property_id=prop.id, unit_id=None,
            category=e["category"].value, amount=Decimal(e["amount"]), payment_method="bank transfer",
            expense_date=_first_of_month(today, i % 3), status=m.ExpenseStatus.confirmed.value,
            notes=e["notes"], recurring_expense_id=e["recurring"].id if e["recurring"] else None,
        )
        db.session.add(exp)
        db.session.flush()
        created_expenses.append(exp)

    # Maintenance requests: open, in_progress, and one closed+converted to an expense.
    tenant_for_maint = None
    if occupied_unit_names:
        tenant_for_maint = units_by_name[occupied_unit_names[0]].tenants[0] if units_by_name[occupied_unit_names[0]].tenants else None

    open_req = m.MaintenanceRequest(
        landlord_id=landlord.id, property_id=prop.id, unit_id=units_by_name[occupied_unit_names[0]].id,
        tenant_id=tenant_for_maint.id if tenant_for_maint else None,
        summary="Leaking kitchen tap", description="Cold water tap has been dripping for two days.",
        category=m.MaintenanceCategory.plumbing.value, status=m.MaintenanceStatus.open.value,
    )
    db.session.add(open_req)

    in_progress_req = m.MaintenanceRequest(
        landlord_id=landlord.id, property_id=prop.id, unit_id=units_by_name[occupied_unit_names[-1]].id,
        tenant_id=None, summary="Faulty wiring in living room",
        description="Intermittent power loss reported by tenant.",
        category=m.MaintenanceCategory.electrical.value, status=m.MaintenanceStatus.in_progress.value,
    )
    db.session.add(in_progress_req)

    closed_req = m.MaintenanceRequest(
        landlord_id=landlord.id, property_id=prop.id, unit_id=units_by_name[occupied_unit_names[0]].id,
        tenant_id=tenant_for_maint.id if tenant_for_maint else None,
        summary="Roof repair after storm damage", description="Several tiles dislodged in the last storm.",
        category=m.MaintenanceCategory.roofing.value, status=m.MaintenanceStatus.closed.value,
    )
    db.session.add(closed_req)
    db.session.flush()

    # Convert the closed request into an Expense (circular FK, post_update on both sides).
    conv_expense = m.Expense(
        landlord_id=landlord.id, property_id=prop.id, unit_id=closed_req.unit_id,
        category=m.ExpenseCategory.maintenance.value, amount=Decimal("15000.00"),
        payment_method="cash", expense_date=today, status=m.ExpenseStatus.confirmed.value,
        notes="Roof repair following storm damage.", maintenance_request_id=closed_req.id,
    )
    db.session.add(conv_expense)
    db.session.flush()
    closed_req.expense_id = conv_expense.id
    db.session.flush()

    # Message + document templates.
    db.session.add(m.MessageTemplate(
        landlord_id=landlord.id, name="Balance Reminder", channel=m.MessageChannel.sms.value,
        template_type=m.MessageTemplateType.balance_reminder.value,
        body=("Hi {tenant_name}, your current balance is KES {balance}. Please pay via Paybill, "
              "account: {account_number}. Thank you."),
    ))
    db.session.add(m.MessageTemplate(
        landlord_id=landlord.id, name="Invoice Reminder", channel=m.MessageChannel.email.value,
        template_type=m.MessageTemplateType.invoice_reminder.value,
        body="Dear {tenant_name}, invoice {invoice_number} for KES {amount} is due on {due_date}.",
    ))
    db.session.add(m.DocumentTemplate(
        landlord_id=landlord.id, name="Standard Lease Agreement", document_type=m.DocumentType.lease.value,
        content="<h1>Lease Agreement</h1><p>Between {landlord_name} and {tenant_name}...</p>",
        is_template=True,
    ))
    db.session.flush()


def _seed_notifications(m, landlord, tenant, team_member, today):
    """
    A small, representative mix so the bell/notifications page isn't empty
    on a fresh seed: one read + one unread to the landlord, one to the
    tenant, one to the team member (if this landlord has one).
    """
    landlord_user_id = landlord.user_id
    rows = [
        m.Notification(
            recipient_user_id=landlord_user_id, sender_user_id=None, landlord_id=landlord.id,
            category=m.NotificationCategory.payment_received.value,
            title="Payment received",
            body=f"{tenant.first_name} {tenant.last_name} paid KES {tenant.unit.rent_amount:,.2f}.",
            link="/landlord/payments", entity_type="payment", entity_id=None,
            is_read=True, read_at=datetime.utcnow(),
        ),
        m.Notification(
            recipient_user_id=landlord_user_id, sender_user_id=None, landlord_id=landlord.id,
            category=m.NotificationCategory.new_maintenance_request.value,
            title="New maintenance request",
            body=f"{tenant.first_name} {tenant.last_name} reported an issue in their unit.",
            link="/landlord/maintenance", entity_type="maintenance", entity_id=None,
            is_read=False,
        ),
    ]
    if tenant.user_id:
        rows.append(m.Notification(
            recipient_user_id=tenant.user_id, sender_user_id=landlord_user_id, landlord_id=landlord.id,
            category=m.NotificationCategory.broadcast.value,
            title="Welcome to your tenant portal",
            body="You can now pay rent, raise maintenance requests, and view your statement online.",
            link="/portal/dashboard", is_read=False,
        ))
    if team_member is not None:
        rows.append(m.Notification(
            recipient_user_id=team_member.user_id, sender_user_id=landlord_user_id, landlord_id=landlord.id,
            category=m.NotificationCategory.team_member_activated.value,
            title="Account activated",
            body=f"Welcome to the team, {team_member.first_name}. Your account is now active.",
            link="/team/dashboard", is_read=False,
        ))
    db.session.add_all(rows)
    db.session.flush()


def _seed_billing_history(m, landlord, spec, today):
    for txn in spec.get("billing_transactions", []):
        db.session.add(m.BillingTransaction(
            landlord_id=landlord.id, type=txn["type"], amount=Decimal(txn["amount"]),
            sms_count=txn.get("sms_count"), payment_reference=txn.get("ref", "SEED-REF"),
            status=txn["status"],
        ))
    db.session.flush()


# ---------------------------------------------------------------------------
# Landlord specs — the dataset
# ---------------------------------------------------------------------------

def _landlord_specs(today):
    return [
        {
            "key": "acme", "company_name": "Acme Properties Ltd", "abbreviated_name": "Acme",
            "email": "landlord@sahilpay.test", "password": "Landlord@123", "phone": "+254700000001",
            "mpesa_number": "123456", "package": "Growth", "sub_status": "active",
            "is_on_trial": False, "trial_ends_at": today - timedelta(days=200), "user_active": True,
            "sms_balance": 500, "unit_count_for_subscription": 7,
            "groups": ["Nairobi Portfolio"],
            "properties": [
                {"name": "Riverside Apartments", "group": "Nairobi Portfolio", "city": "Nairobi",
                 "street": "Riverside Dr", "water_rate": 100, "electricity_rate": 25,
                 "units": [
                     {"name": "A1", "rent": 25000, "occupied": True},
                     {"name": "A2", "rent": 25000, "occupied": True},
                     {"name": "A3", "rent": 28000, "occupied": True},
                     {"name": "A4", "rent": 22000, "occupied": False},
                 ]},
                {"name": "Park View Towers", "group": "Nairobi Portfolio", "city": "Nairobi",
                 "street": "Park Rd", "water_rate": 120, "electricity_rate": 30,
                 "units": [
                     {"name": "B1", "rent": 35000, "occupied": True},
                     {"name": "B2", "rent": 32000, "occupied": False},
                     {"name": "B3", "rent": 30000, "occupied": True},
                 ]},
            ],
            "tenants": [
                {"unit": "A1", "first_name": "James", "last_name": "Mwangi", "phone": "+254711000001",
                 "email": "james.mwangi@tenant.test", "account_number": "ACME-T001", "scenario": "paid"},
                {"unit": "A2", "first_name": "Amina", "last_name": "Hassan", "phone": "+254711000002",
                 "email": "amina.hassan@tenant.test", "account_number": "ACME-T002", "scenario": "arrears"},
                {"unit": "A3", "first_name": "Brian", "last_name": "Kiprotich", "phone": "+254711000003",
                 "email": "brian.kiprotich@tenant.test", "account_number": "ACME-T003", "scenario": "advance"},
                {"unit": "B1", "first_name": "Grace", "last_name": "Wambui", "phone": "+254711000004",
                 "email": "grace.wambui@tenant.test", "account_number": "ACME-T004", "scenario": "paid"},
                {"unit": "B3", "first_name": "Diana", "last_name": "Achieng", "phone": "+254711000005",
                 "email": "diana.achieng@tenant.test", "account_number": "ACME-T005", "scenario": "partial"},
            ],
            "moved_out_tenant": {"unit": "B2", "first_name": "Kevin", "last_name": "Omondi",
                                  "phone": "+254711000006", "account_number": "ACME-T006"},
            "deleted_tenant": {"unit": "B2", "first_name": "Faith", "last_name": "Njeri",
                                "phone": "+254711000007", "account_number": "ACME-T007"},
            "team_members": [
                {"username": "caretaker1", "email": "caretaker@sahilpay.test", "password": "Caretaker@123",
                 "phone": "+254722000001", "first_name": "David", "last_name": "Otieno",
                 "role": "editor", "property_access_all": False,
                 "scoped_property_ids": lambda pids: [pids[0]],
                 "permissions": {
                     "payments": (True, True), "invoices": (True, True), "utilities": (True, True),
                     "unit_utilities": (True, True), "tenants": (True, True),
                     "units": (True, False), "properties": (True, False), "messages": (True, True),
                 }},
                {"username": "viewer1", "email": "viewer.acme@sahilpay.test", "password": "Viewer@123",
                 "phone": "+254722000002", "first_name": "Patrick", "last_name": "Mutua",
                 "role": "viewer", "property_access_all": True, "scoped_property_ids": lambda pids: [],
                 "permissions": {
                     "payments": (True, False), "invoices": (True, False), "utilities": (True, False),
                     "unit_utilities": (True, False), "tenants": (True, False),
                     "units": (True, False), "properties": (True, False), "messages": (True, False),
                 }},
            ],
            "billing_transactions": [
                {"type": "subscription", "amount": "280.00", "status": "paid", "ref": "ACME-SUB-001"},
                {"type": "sms_purchase", "amount": "200.00", "sms_count": 200, "status": "paid", "ref": "ACME-SMS-001"},
            ],
        },
        {
            "key": "sunrise", "company_name": "Sunrise Estates", "abbreviated_name": "Sunrise",
            "email": "sunrise@sahilpay.test", "password": "Sunrise@123", "phone": "+254700000002",
            "mpesa_number": "654321", "package": "Starter", "sub_status": "trial",
            "is_on_trial": True, "trial_ends_at": today + timedelta(days=20), "user_active": True,
            "sms_balance": 100, "unit_count_for_subscription": 5,
            "groups": [],
            "properties": [
                {"name": "Sunrise Court", "group": None, "city": "Mombasa", "street": "Nyali Rd",
                 "units": [
                     {"name": "S1", "rent": 18000, "occupied": True},
                     {"name": "S2", "rent": 18000, "occupied": True},
                     {"name": "S3", "rent": 16000, "occupied": False},
                 ]},
                {"name": "Beachside Villas", "group": None, "city": "Mombasa", "street": "Beach Rd",
                 "units": [
                     {"name": "V1", "rent": 40000, "occupied": True},
                     {"name": "V2", "rent": 38000, "occupied": False},
                 ]},
            ],
            "tenants": [
                {"unit": "S1", "first_name": "Peter", "last_name": "Mwakio", "phone": "+254712000001",
                 "email": "peter.mwakio@tenant.test", "account_number": "SUN-T001", "scenario": "paid"},
                {"unit": "S2", "first_name": "Mary", "last_name": "Wanjala", "phone": "+254712000002",
                 "email": "mary.wanjala@tenant.test", "account_number": "SUN-T002", "scenario": "arrears"},
                {"unit": "V1", "first_name": "John", "last_name": "Baraka", "phone": "+254712000003",
                 "email": "john.baraka@tenant.test", "account_number": "SUN-T003", "scenario": "advance"},
            ],
            "moved_out_tenant": {"unit": "S3", "first_name": "Lucy", "last_name": "Adhiambo",
                                  "phone": "+254712000004", "account_number": "SUN-T004"},
            "deleted_tenant": {"unit": "S3", "first_name": "Samuel", "last_name": "Kiptoo",
                                "phone": "+254712000005", "account_number": "SUN-T005"},
            "team_members": [
                {"username": "sunrise.editor", "email": "editor.sunrise@sahilpay.test", "password": "Editor@123",
                 "phone": "+254723000001", "first_name": "Esther", "last_name": "Chebet",
                 "role": "editor", "property_access_all": True, "scoped_property_ids": lambda pids: [],
                 "permissions": {
                     "payments": (True, True), "invoices": (True, True), "utilities": (True, True),
                     "unit_utilities": (True, True), "tenants": (True, True),
                     "units": (True, True), "properties": (True, True), "messages": (True, True),
                 }},
                {"username": "sunrise.viewer", "email": "viewer.sunrise@sahilpay.test", "password": "Viewer@123",
                 "phone": "+254723000002", "first_name": "Robert", "last_name": "Were",
                 "role": "viewer", "property_access_all": False, "scoped_property_ids": lambda pids: [pids[1]],
                 "permissions": {
                     "payments": (False, False), "invoices": (True, False), "utilities": (True, False),
                     "unit_utilities": (True, False), "tenants": (True, False),
                     "units": (True, False), "properties": (True, False), "messages": (False, False),
                 }},
            ],
            "billing_transactions": [],
        },
        {
            "key": "pioneer", "company_name": "Pioneer Housing Group", "abbreviated_name": "Pioneer",
            "email": "pioneer@sahilpay.test", "password": "Pioneer@123", "phone": "+254700000003",
            "mpesa_number": "789012", "package": "Scale", "sub_status": "suspended",
            "is_on_trial": False, "trial_ends_at": today - timedelta(days=90), "user_active": False,
            "sms_balance": 0, "unit_count_for_subscription": 5,
            "groups": [],
            "properties": [
                {"name": "Pioneer Heights", "group": None, "city": "Kisumu", "street": "Oginga Odinga Rd",
                 "units": [
                     {"name": "P1", "rent": 20000, "occupied": True},
                     {"name": "P2", "rent": 20000, "occupied": True},
                     {"name": "P3", "rent": 18000, "occupied": False},
                 ]},
                {"name": "Lakeview Residences", "group": None, "city": "Kisumu", "street": "Lake Rd",
                 "units": [
                     {"name": "L1", "rent": 27000, "occupied": True},
                     {"name": "L2", "rent": 25000, "occupied": False},
                 ]},
            ],
            "tenants": [
                {"unit": "P1", "first_name": "Susan", "last_name": "Atieno", "phone": "+254713000001",
                 "email": "susan.atieno@tenant.test", "account_number": "PIO-T001", "scenario": "arrears"},
                {"unit": "P2", "first_name": "Tom", "last_name": "Onyango", "phone": "+254713000002",
                 "email": "tom.onyango@tenant.test", "account_number": "PIO-T002", "scenario": "paid"},
                {"unit": "L1", "first_name": "Ruth", "last_name": "Akinyi", "phone": "+254713000003",
                 "email": "ruth.akinyi@tenant.test", "account_number": "PIO-T003", "scenario": "paid"},
            ],
            "moved_out_tenant": {"unit": "P3", "first_name": "Joseph", "last_name": "Ouma",
                                  "phone": "+254713000004", "account_number": "PIO-T004"},
            "deleted_tenant": {"unit": "P3", "first_name": "Nancy", "last_name": "Achieng",
                                "phone": "+254713000005", "account_number": "PIO-T005"},
            "team_members": [
                {"username": "pioneer.editor", "email": "editor.pioneer@sahilpay.test", "password": "Editor@123",
                 "phone": "+254724000001", "first_name": "Michael", "last_name": "Otieno",
                 "role": "editor", "property_access_all": True, "scoped_property_ids": lambda pids: [],
                 "permissions": {
                     "payments": (True, True), "invoices": (True, True), "utilities": (True, True),
                     "unit_utilities": (True, True), "tenants": (True, True),
                     "units": (True, True), "properties": (True, False), "messages": (True, True),
                 }},
                {"username": "pioneer.viewer", "email": "viewer.pioneer@sahilpay.test", "password": "Viewer@123",
                 "phone": "+254724000002", "first_name": "Janet", "last_name": "Mwende",
                 "role": "viewer", "property_access_all": False, "scoped_property_ids": lambda pids: [pids[0]],
                 "permissions": {
                     "payments": (True, False), "invoices": (True, False), "utilities": (False, False),
                     "unit_utilities": (False, False), "tenants": (True, False),
                     "units": (True, False), "properties": (False, False), "messages": (False, False),
                 }},
            ],
            "billing_transactions": [
                {"type": "subscription", "amount": "150.00", "status": "paid", "ref": "PIO-SUB-001"},
            ],
        },
        {
            "key": "coastal", "company_name": "Coastal Rentals", "abbreviated_name": "Coastal",
            "email": "coastal@sahilpay.test", "password": "Coastal@123", "phone": "+254700000004",
            "mpesa_number": "345678", "package": "Starter", "sub_status": "trial",
            "is_on_trial": True, "trial_ends_at": today + timedelta(days=2), "user_active": True,
            "sms_balance": 50, "unit_count_for_subscription": 5,
            "groups": [],
            "properties": [
                {"name": "Coastal Breeze Apartments", "group": None, "city": "Malindi", "street": "Casuarina Rd",
                 "units": [
                     {"name": "C1", "rent": 22000, "occupied": True},
                     {"name": "C2", "rent": 22000, "occupied": True},
                     {"name": "C3", "rent": 20000, "occupied": False},
                 ]},
                {"name": "Palm Grove", "group": None, "city": "Malindi", "street": "Palm Ave",
                 "units": [
                     {"name": "G1", "rent": 26000, "occupied": True},
                     {"name": "G2", "rent": 24000, "occupied": False},
                 ]},
            ],
            "tenants": [
                {"unit": "C1", "first_name": "Daniel", "last_name": "Mwambire", "phone": "+254714000001",
                 "email": "daniel.mwambire@tenant.test", "account_number": "CST-T001", "scenario": "advance"},
                {"unit": "C2", "first_name": "Esther", "last_name": "Wanyama", "phone": "+254714000002",
                 "email": "esther.wanyama@tenant.test", "account_number": "CST-T002", "scenario": "arrears"},
                {"unit": "G1", "first_name": "Michael", "last_name": "Juma", "phone": "+254714000003",
                 "email": "michael.juma@tenant.test", "account_number": "CST-T003", "scenario": "paid"},
            ],
            "moved_out_tenant": {"unit": "C3", "first_name": "Sarah", "last_name": "Kahindi",
                                  "phone": "+254714000004", "account_number": "CST-T004"},
            "deleted_tenant": {"unit": "C3", "first_name": "George", "last_name": "Mwangangi",
                                "phone": "+254714000005", "account_number": "CST-T005"},
            "team_members": [
                {"username": "coastal.editor", "email": "editor.coastal@sahilpay.test", "password": "Editor@123",
                 "phone": "+254725000001", "first_name": "Lilian", "last_name": "Mwakio",
                 "role": "editor", "property_access_all": True, "scoped_property_ids": lambda pids: [],
                 "permissions": {
                     "payments": (True, True), "invoices": (True, True), "utilities": (True, True),
                     "unit_utilities": (True, True), "tenants": (True, True),
                     "units": (True, True), "properties": (True, True), "messages": (True, True),
                 }},
                {"username": "coastal.viewer", "email": "viewer.coastal@sahilpay.test", "password": "Viewer@123",
                 "phone": "+254725000002", "first_name": "Hassan", "last_name": "Said",
                 "role": "viewer", "property_access_all": False, "scoped_property_ids": lambda pids: [pids[0]],
                 "permissions": {
                     "payments": (True, False), "invoices": (True, False), "utilities": (True, False),
                     "unit_utilities": (True, False), "tenants": (True, False),
                     "units": (True, False), "properties": (True, False), "messages": (True, False),
                 }},
            ],
            "billing_transactions": [],
        },
    ]


# ---------------------------------------------------------------------------
# Main seed
# ---------------------------------------------------------------------------

def seed() -> None:
    import models as m

    today = date.today()
    trial_days = app.config["DEFAULT_TRIAL_DAYS"]

    print("─── SahilPay extensive seed starting ───\n")

    # ===== Platform =====
    db.session.add(m.TrialConfig(
        scope=m.TrialScope.global_scope.value, landlord_id=None,
        duration_days=trial_days, is_active=True,
    ))
    package_specs = [
        {"name": "Starter", "min_units": 1, "max_units": 20, "price_per_unit": Decimal("50.00")},
        {"name": "Growth", "min_units": 21, "max_units": 70, "price_per_unit": Decimal("40.00")},
        {"name": "Scale", "min_units": 71, "max_units": None, "price_per_unit": Decimal("30.00")},
    ]
    packages = {}
    for spec in package_specs:
        pkg = m.Package(name=spec["name"], min_units=spec["min_units"], max_units=spec["max_units"],
                         price_per_unit=spec["price_per_unit"], flat_price=None, is_active=True)
        db.session.add(pkg)
        db.session.flush()
        packages[spec["name"]] = pkg
    print(f"  Platform: TrialConfig + {len(packages)} packages")

    # ===== System Admin =====
    from utils import hash_password
    admin_user = m.User(
        email="admin@sahilpay.test", role=m.UserRole.system_admin.value,
        password_hash=hash_password("Admin@123"), is_verified=True, is_active=True,
    )
    db.session.add(admin_user)
    db.session.flush()
    db.session.add(m.SystemAdmin(user_id=admin_user.id, first_name="Platform", last_name="Admin"))
    print("  System Admin: admin@sahilpay.test")

    db.session.flush()

    # ===== Landlords =====
    credentials = [("SYSTEM ADMIN", "admin@sahilpay.test", "Admin@123")]

    for spec in _landlord_specs(today):
        landlord = _create_landlord(m, spec, packages, today)
        credentials.append((f"LANDLORD ({spec['company_name']})", spec["email"], spec["password"]))
        print(f"\n  ── Landlord: {spec['company_name']} ({spec['sub_status']}) ──")

        groups = {}
        for gname in spec["groups"]:
            grp = m.PropertyGroup(landlord_id=landlord.id, name=gname)
            db.session.add(grp)
            db.session.flush()
            groups[gname] = grp.id

        properties = []
        units_by_name = {}
        for p_spec in spec["properties"]:
            group_id = groups.get(p_spec["group"]) if p_spec.get("group") else None
            prop, units = _create_property_with_units(m, landlord, p_spec, group_id)
            properties.append(prop)
            units_by_name.update(units)
            print(f"    Property: {prop.name} ({len(units)} units)")

        # Occupied tenants with financial history
        occupied_names_by_prop = {}
        for t_spec in spec["tenants"]:
            unit = units_by_name[t_spec["unit"]]
            tenant = _create_tenant(m, landlord, unit, {**t_spec, "move_in": today - relativedelta(months=4)}, today)
            _seed_financial_history(m, landlord, tenant, unit, unit.property, t_spec["scenario"], today)
            occupied_names_by_prop.setdefault(unit.property_id, []).append(t_spec["unit"])
            print(f"    Tenant: {tenant.first_name} {tenant.last_name} — {t_spec['scenario']} "
                  f"(balance after history: {tenant.balance})")

        # Moved-out tenant (history only, vacant unit now)
        mo = spec["moved_out_tenant"]
        mo_unit = units_by_name[mo["unit"]]
        mo_tenant = _create_tenant(m, landlord, mo_unit, {
            **mo, "email": f"{mo['first_name'].lower()}@former-tenant.test",
            "move_in": today - relativedelta(months=10), "move_out": today - relativedelta(months=1),
        }, today)
        print(f"    Moved-out tenant: {mo_tenant.first_name} {mo_tenant.last_name} (unit {mo['unit']})")

        # Soft-deleted tenant
        dl = spec["deleted_tenant"]
        dl_unit = units_by_name[dl["unit"]]
        dl_tenant = _create_tenant(m, landlord, dl_unit, {
            **dl, "email": f"{dl['first_name'].lower()}@deleted-tenant.test",
            "move_in": today - relativedelta(months=8), "move_out": today - relativedelta(months=3),
            "is_deleted": True,
        }, today)
        print(f"    Soft-deleted tenant: {dl_tenant.first_name} {dl_tenant.last_name} (unit {dl['unit']})")

        # Operations seeded on the FIRST property (utilities/expenses/maintenance/templates)
        first_prop = properties[0]
        occ_names = occupied_names_by_prop.get(first_prop.id, [n for n, u in units_by_name.items() if u.property_id == first_prop.id])
        if not occ_names:
            occ_names = list(units_by_name.keys())[:1]
        _seed_operations(m, landlord, first_prop, units_by_name, occ_names, today)
        print(f"    Operations: utility readings, expenses, maintenance, templates seeded on {first_prop.name}")

        # Team members with DIFFERENT permission profiles
        property_ids = [p.id for p in properties]
        tm = None
        for tm_spec in spec["team_members"]:
            tm = _create_team_member(m, landlord, tm_spec, property_ids)
            credentials.append((f"TEAM MEMBER ({spec['abbreviated_name']}/{tm_spec['role']})", tm_spec["email"], tm_spec["password"]))
            print(f"    Team member: {tm.first_name} {tm.last_name} ({tm_spec['role']}, "
                  f"{'all properties' if tm_spec['property_access_all'] else 'scoped'})")

        _seed_billing_history(m, landlord, spec, today)
        _seed_notifications(m, landlord, tenant, tm, today)
        print("    Notifications: sample read/unread rows seeded for landlord/tenant/team member")

        # Per-landlord trial override demo on Coastal (the near-expiry one)
        if spec["key"] == "coastal":
            db.session.add(m.TrialConfig(
                scope=m.TrialScope.per_landlord.value, landlord_id=landlord.id,
                duration_days=14, is_active=True,
            ))

        credentials.append((f"TENANT (OTP, {spec['abbreviated_name']})",
                             ", ".join(t["phone"] for t in spec["tenants"]), "POST /api/otp/request"))

    db.session.commit()
    print("\n─── Seed committed successfully ───\n")
    _print_credentials(credentials)


def _print_credentials(rows) -> None:
    width = 92
    print("=" * width)
    print("  SEEDED ACCOUNTS — use these to log in")
    print("=" * width)
    print(f"  {'Role':<32}  {'Email / Phone':<40}  Password")
    print("-" * width)
    for role, ident, pw in rows:
        print(f"  {role:<32}  {ident:<40}  {pw}")
    print("=" * width)
    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        reset_all_data()
        db.create_all()
        seed()
