"""
SahilPay — services/demo_service.py
=====================================
DEMO_MODE_SPEC.md — creates, seeds, and resets the hidden "shadow" demo
landlord that backs a real landlord's "Try demo mode" toggle.

Unlike server/seed.py (a destructive, whole-database dev fixture), this module
only ever touches ONE landlord's rows — the shadow's — and is safe to call
from a live request handler. It drives the same real engine seed.py uses
(services.category_service, services.allocation_service,
tasks.invoice_tasks._run_monthly_billing_for_tenant) so every rollover /
credit / allocation / statement row it produces is production-identical.

Public API:
    ensure_demo_landlord(real_landlord) -> Landlord   # create+seed if absent, else return existing
    reset_demo_data(real_landlord)      -> Landlord   # wipe + reseed
    get_demo_shadow(real_landlord_id)   -> Landlord | None

None of these commit — callers (routes/demo_routes.py) commit once at the end,
matching every other service in this layer.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from extensions import db

# Every demo tenant/user identity is obviously fake — defense-in-depth on top
# of the service-level simulate-always guard in communication_service.py, so
# even if that guard were ever bypassed there is no real destination to send to.
_FAKE_PHONE_PREFIX = "+254700000"
_FAKE_EMAIL_DOMAIN = "sahilpay.demo"


def get_demo_shadow(real_landlord_id: int):
    from models import Landlord

    return Landlord.query.filter_by(demo_owner_landlord_id=real_landlord_id).first()


def ensure_demo_landlord(real_landlord):
    """Idempotent: returns the existing shadow if one exists, else builds one."""
    existing = get_demo_shadow(real_landlord.id)
    if existing is not None:
        return existing
    return _build_demo_landlord(real_landlord)


def reset_demo_data(real_landlord):
    """Wipe every row scoped to the existing shadow landlord and reseed it."""
    shadow = get_demo_shadow(real_landlord.id)
    if shadow is None:
        raise ValueError("No demo shadow exists for this landlord — call ensure_demo_landlord first.")

    _wipe_landlord_scoped_rows(shadow.id)
    _seed_dataset(shadow)
    shadow.demo_last_reset_at = datetime.utcnow()
    db.session.flush()
    return shadow


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_demo_landlord(real_landlord):
    from utils import hash_password
    from models import User, Landlord, UserRole, AccountType

    stub_email = f"demo+{real_landlord.id}@{_FAKE_EMAIL_DOMAIN}"
    stub_user = User(
        email=stub_email,
        phone=None,
        role=UserRole.landlord.value,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_verified=True,
        # Never allows login — the shadow landlord is scaffolding, not an account.
        is_active=False,
    )
    db.session.add(stub_user)
    db.session.flush()

    shadow = Landlord(
        user_id=stub_user.id,
        company_name=f"{real_landlord.company_name} (Demo)" if real_landlord.company_name else "Demo Properties Ltd",
        abbreviated_name="Demo",
        currency=real_landlord.currency or "KES",
        timezone=real_landlord.timezone or "Africa/Nairobi",
        account_type=AccountType.landlord.value,
        default_tax_rate=Decimal("7.50"),
        sms_balance=500,
        package_id=None,
        is_on_trial=False,
        is_demo=True,
        demo_owner_landlord_id=real_landlord.id,
        demo_created_at=datetime.utcnow(),
        # Tutorials/onboarding checklist is independent scaffolding per the
        # spec §5.7 — leave unset so a landlord can practice it in demo too.
        onboarding_state_json=None,
    )
    db.session.add(shadow)
    db.session.flush()

    from models import LandlordSettings, AutomationSettings

    db.session.add(LandlordSettings(
        landlord_id=shadow.id, sms_enabled=True, whatsapp_enabled=False,
        email_enabled=True, low_sms_balance_threshold=50,
    ))
    db.session.add(AutomationSettings(
        landlord_id=shadow.id,
        auto_generate_recurring_invoices=True, auto_generate_recurring_bills=True,
        alert_on_new_tenant=True, auto_send_payment_acknowledgments=True,
        monthly_reminders_enabled=True, monthly_reminder_day=1,
        lease_expiry_notifications=True, lease_expiry_range_days=30,
    ))
    db.session.flush()

    _seed_dataset(shadow)
    return shadow


# ---------------------------------------------------------------------------
# Dataset (drives the real engine — mirrors seed.py::_seed_category_demo)
# ---------------------------------------------------------------------------

def _first_of_month(d: date, months_ago: int = 0) -> date:
    return d.replace(day=1) - relativedelta(months=months_ago)


def _create_demo_user(first_name: str, seq: int):
    """Fake, login-disabled tenant identity — never reachable from OTP login."""
    from models import User, UserRole

    user = User(
        email=f"demo{seq}@{_FAKE_EMAIL_DOMAIN}",
        phone=f"{_FAKE_PHONE_PREFIX}{seq:02d}",
        role=UserRole.tenant.value,
        password_hash=None,
        is_verified=False,
        is_active=False,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _seed_dataset(shadow):
    """
    3 properties -> units -> ~12 tenants -> 3 months of real billing/payments
    -> operational garnish. See DEMO_MODE_SPEC.md §4.1 for the content plan.
    """
    import models as m
    from services.category_service import seed_default_categories
    from services.allocation_service import (
        auto_allocate, apply_allocations, normalize_manual_allocations, outstanding_line_items,
    )
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant
    from utils import gen_reference

    today = date.today()

    # ---- Charge categories: seeded defaults + two custom ones -------------
    seed_default_categories(shadow.id)
    db.session.flush()
    cats = {c.name: c for c in m.ChargeCategory.query.filter_by(landlord_id=shadow.id).all()}
    garbage = m.ChargeCategory(
        landlord_id=shadow.id, name="Garbage", kind="utility", is_metered=False,
        default_rate=Decimal("300"), auto_bill_monthly=True, is_default=False, is_active=True,
    )
    parking = m.ChargeCategory(
        landlord_id=shadow.id, name="Parking", kind="invoice", is_metered=False,
        auto_bill_monthly=False, is_default=False, is_active=True,
    )
    db.session.add_all([garbage, parking])
    db.session.flush()
    cats["Garbage"] = garbage
    cats["Parking"] = parking

    # ---- Properties + units -------------------------------------------------
    group = m.PropertyGroup(landlord_id=shadow.id, name="North Nairobi Portfolio")
    db.session.add(group)
    db.session.flush()

    def make_property(name, city, street, group_id, unit_specs, water_rate=120, electricity_rate=30):
        prop = m.Property(
            landlord_id=shadow.id, property_group_id=group_id, name=name,
            number_of_units=len(unit_specs), city=city, street_name=street,
            water_rate=Decimal(str(water_rate)), electricity_rate=Decimal(str(electricity_rate)),
            tax_rate=Decimal("7.50"), management_fee=Decimal("5000.00"),
        )
        db.session.add(prop)
        db.session.flush()
        units = {}
        for uname, rent, occupied in unit_specs:
            unit = m.Unit(property_id=prop.id, name=uname, rent_amount=Decimal(str(rent)), is_occupied=occupied)
            db.session.add(unit)
            db.session.flush()
            units[uname] = unit
        return prop, units

    sunrise_units = [(f"S{i}", 12000, i <= 6) for i in range(1, 9)]       # 8 units, 2 vacant
    sunrise, sunrise_u = make_property("Sunrise Apartments", "Nairobi", "Ngong Road", group.id, sunrise_units)

    green_units = [(f"G{i}", 15000, i <= 3) for i in range(1, 5)]        # 4 units, 1 vacant
    green, green_u = make_property("Green Court", "Nairobi", "Argwings Kodhek Rd", group.id, green_units)

    palm_units = [(f"P{i}", 20000, True) for i in range(1, 4)]          # 3 units, all occupied
    palm, palm_u = make_property("Palm Villas", "Nairobi", "Kilimani Lane", None, palm_units, water_rate=140, electricity_rate=32)

    m1, m2, m3 = _first_of_month(today, 2), _first_of_month(today, 1), _first_of_month(today, 0)
    move_in = _first_of_month(today, 4)

    seq = [0]

    def make_tenant(unit, fn, ln, acct):
        seq[0] += 1
        user = _create_demo_user(fn, seq[0])
        tenant = m.Tenant(
            user_id=user.id, landlord_id=shadow.id, unit_id=unit.id,
            first_name=fn, last_name=ln, phone=user.phone, email=user.email,
            account_number=f"DEMO-{acct}",
            deposit_amount=unit.rent_amount, deposit_paid=unit.rent_amount, deposit_returned=Decimal("0.00"),
            balance=Decimal("0.00"),
            lease_start_date=move_in, lease_expiry_date=move_in + relativedelta(years=1),
            move_in_date=move_in,
        )
        db.session.add(tenant)
        db.session.flush()
        db.session.add(m.TenantUnitHistory(tenant_id=tenant.id, unit_id=unit.id, moved_in_at=move_in))
        db.session.flush()
        return tenant

    def bill(tenant, month):
        _run_monthly_billing_for_tenant(shadow, tenant, month, month, None)
        db.session.flush()

    def pay(tenant, amount, when, mode="auto", manual=None):
        p = m.Payment(
            payment_ref=gen_reference("PMT"), landlord_id=shadow.id, tenant_id=tenant.id,
            unit_id=tenant.unit_id, property_id=tenant.unit.property_id, amount=Decimal(str(amount)),
            payment_date=when, status=m.PaymentStatus.confirmed.value,
            source=(m.PaymentSource.manual.value if mode == "manual" else m.PaymentSource.mpesa.value),
            payment_method=("Manual" if mode == "manual" else "M-Pesa"),
        )
        db.session.add(p)
        db.session.flush()
        rows = (normalize_manual_allocations(manual, tenant, shadow, ref_date=when)
                if mode == "manual" else auto_allocate(tenant, p.amount, shadow, ref_date=when))
        apply_allocations(p, tenant, rows, shadow.id)
        db.session.flush()

    def line_of(tenant, cat_name, subcat):
        for li in outstanding_line_items(tenant):
            if li.category_id == cats[cat_name].id and li.subcategory == subcat:
                return li
        return None

    # ---- Tenants: several straightforward paid-up tenants -------------------
    paid_up_specs = [
        (sunrise_u["S1"], "Amina", "Otieno", "A01"),
        (sunrise_u["S2"], "Brian", "Kamau", "A02"),
        (sunrise_u["S3"], "Cynthia", "Wanjiru", "A03"),
        (green_u["G1"], "Daniel", "Mwangi", "A04"),
        (palm_u["P1"], "Esther", "Njeri", "A05"),
        (palm_u["P2"], "Felix", "Omondi", "A06"),
    ]
    for unit, fn, ln, acct in paid_up_specs:
        tenant = make_tenant(unit, fn, ln, acct)
        for mo in (m1, m2, m3):
            bill(tenant, mo)
            due = sum(li.remaining for li in outstanding_line_items(tenant))
            if due > 0:
                pay(tenant, due, mo, mode="auto")

    # ---- Ben-style partial payer: rent rolls into a 2-origin-month balance --
    partial = make_tenant(sunrise_u["S4"], "Grace", "Achieng", "A07")
    for mo in (m1, m2, m3):
        bill(partial, mo)
        gl = line_of(partial, "Garbage", "current")
        if gl:
            pay(partial, gl.remaining, mo, mode="manual", manual=[{"line_item_id": gl.id, "amount": float(gl.remaining)}])

    # ---- Overpayer: credit consumed by the next month's billing -------------
    overpayer = make_tenant(sunrise_u["S5"], "Hassan", "Ali", "A08")
    bill(overpayer, m1)
    first_due = sum(li.remaining for li in outstanding_line_items(overpayer))
    pay(overpayer, first_due + Decimal("2000"), m1, mode="auto")   # overpay by 2000 -> credit
    bill(overpayer, m2)                                            # apply_tenant_credit consumes it
    rem = sum(li.remaining for li in outstanding_line_items(overpayer))
    if rem > 0:
        pay(overpayer, rem, m2, mode="auto")
    bill(overpayer, m3)
    rem = sum(li.remaining for li in outstanding_line_items(overpayer))
    if rem > 0:
        pay(overpayer, rem, m3, mode="auto")

    # ---- Unpaid deposit (never rolls) + metered water/electricity -----------
    metered = make_tenant(green_u["G2"], "Irene", "Chebet", "A09")
    dep_inv = m.Invoice(
        invoice_number=gen_reference("INV"), landlord_id=shadow.id, tenant_id=metered.id,
        unit_id=metered.unit_id, property_id=green.id, invoice_type=m.InvoiceType.deposit.value,
        issue_date=m1, status=m.InvoiceStatus.open.value, total_amount=Decimal("15000"),
        amount_paid=Decimal("0"), balance=Decimal("15000"), title="Security deposit",
    )
    db.session.add(dep_inv)
    db.session.flush()
    db.session.add(m.InvoiceLineItem(
        invoice_id=dep_inv.id, item="Security Deposit", quantity=Decimal("1"),
        unit_price=Decimal("15000"), amount=Decimal("15000"), category_id=cats["Rent"].id,
        subcategory="deposit", amount_paid=Decimal("0"), status="open",
    ))
    metered.balance = Decimal(str(metered.balance)) - Decimal("15000")
    db.session.flush()

    for mo in (m1, m2, m3):
        bill(metered, mo)
        rl = line_of(metered, "Rent", "current")
        if rl:
            pay(metered, rl.remaining, mo, mode="manual", manual=[{"line_item_id": rl.id, "amount": float(rl.remaining)}])

    for item, cat_name, prev, curr, rate in (
        ("water", "Water", 900, 940, 120), ("electricity", "Electricity", 600, 655, 30),
    ):
        reading = m.UtilityReading(
            landlord_id=shadow.id, property_id=green.id, unit_id=metered.unit_id, utility_item=item,
            category_id=cats[cat_name].id, previous_reading=Decimal(str(prev)),
            current_reading=Decimal(str(curr)), consumption=Decimal(str(curr - prev)),
            reading_month=m3.strftime("%Y-%m"),
        )
        db.session.add(reading)
        db.session.flush()
        amt = Decimal(str((curr - prev) * rate))
        util_inv = m.Invoice(
            invoice_number=gen_reference("INV"), landlord_id=shadow.id, tenant_id=metered.id,
            unit_id=metered.unit_id, property_id=green.id, invoice_type=m.InvoiceType.utility.value,
            issue_date=m3, status=m.InvoiceStatus.open.value, total_amount=amt,
            amount_paid=Decimal("0"), balance=amt, title=f"{cat_name} — {m3:%B %Y}",
        )
        db.session.add(util_inv)
        db.session.flush()
        db.session.add(m.InvoiceLineItem(
            invoice_id=util_inv.id, item=cat_name, description=f"{prev} to {curr}",
            quantity=Decimal("1"), unit_price=amt, amount=amt, category_id=cats[cat_name].id,
            subcategory="current", utility_reading_id=reading.id, amount_paid=Decimal("0"), status="open",
        ))
        reading.invoice_id = util_inv.id
        metered.balance = Decimal(str(metered.balance)) - amt
    db.session.flush()

    # ---- Brand-new tenant this month with only a current invoice ------------
    newcomer = make_tenant(palm_u["P3"], "Joyce", "Kariuki", "A10")
    bill(newcomer, m3)

    # ---- Operational garnish -------------------------------------------------
    _seed_operational_garnish(m, shadow, sunrise, sunrise_u, paid_up_specs[0][0].tenants[0] if paid_up_specs[0][0].tenants else None)


def _seed_operational_garnish(m, shadow, prop, units_by_name, sample_tenant):
    """Expenses, maintenance, message templates, comms log, notifications — see spec §4.1."""
    from services.communication_service import dispatch_message

    today = date.today()

    recurring = m.RecurringExpense(
        landlord_id=shadow.id, property_id=prop.id, unit_id=None,
        category=m.ExpenseCategory.security.value, amount=Decimal("8000.00"),
        payment_method="cash", notes="Monthly security guard fee.", day_of_month=1, is_active=True,
    )
    db.session.add(recurring)
    db.session.flush()

    for cat, amount, notes, rec in (
        (m.ExpenseCategory.security, "8000.00", "Security guard — monthly instance of recurring template.", recurring),
        (m.ExpenseCategory.garbage, "3500.00", "Garbage collection contract.", None),
        (m.ExpenseCategory.cleaning, "4200.00", "Common-area cleaning service.", None),
    ):
        db.session.add(m.Expense(
            landlord_id=shadow.id, property_id=prop.id, unit_id=None,
            category=cat.value, amount=Decimal(amount), payment_method="bank transfer",
            expense_date=today, status=m.ExpenseStatus.confirmed.value,
            notes=notes, recurring_expense_id=rec.id if rec else None,
        ))
    db.session.flush()

    first_unit = list(units_by_name.values())[0]
    db.session.add(m.MaintenanceRequest(
        landlord_id=shadow.id, property_id=prop.id, unit_id=first_unit.id,
        tenant_id=sample_tenant.id if sample_tenant else None,
        summary="Leaking kitchen tap", description="Cold water tap has been dripping for two days.",
        category=m.MaintenanceCategory.plumbing.value, status=m.MaintenanceStatus.open.value,
    ))
    db.session.add(m.MaintenanceRequest(
        landlord_id=shadow.id, property_id=prop.id, unit_id=list(units_by_name.values())[-1].id,
        tenant_id=None, summary="Faulty wiring in living room",
        description="Intermittent power loss reported by tenant.",
        category=m.MaintenanceCategory.electrical.value, status=m.MaintenanceStatus.in_progress.value,
    ))
    db.session.flush()

    db.session.add(m.MessageTemplate(
        landlord_id=shadow.id, name="Balance Reminder", channel=m.MessageChannel.sms.value,
        template_type=m.MessageTemplateType.balance_reminder.value,
        body=("Hi {tenant_name}, your current balance is KES {balance}. Please pay via Paybill, "
              "account: {account_number}. Thank you."),
    ))
    db.session.add(m.MessageTemplate(
        landlord_id=shadow.id, name="Invoice Reminder", channel=m.MessageChannel.email.value,
        template_type=m.MessageTemplateType.invoice_reminder.value,
        body="Dear {tenant_name}, invoice {invoice_number} for KES {amount} is due on {due_date}.",
    ))
    db.session.flush()

    # A couple of simulated comms log entries so the Communications page isn't
    # empty — dispatch_message() is already force-simulated for is_demo=True.
    if sample_tenant is not None:
        dispatch_message(
            landlord_id=shadow.id, tenant=sample_tenant, channel="sms",
            content="Hi, this is a reminder that your rent balance is due soon. — Demo landlord",
        )

    db.session.add(m.Notification(
        recipient_user_id=shadow.user_id, sender_user_id=None, landlord_id=shadow.id,
        category=m.NotificationCategory.new_maintenance_request.value,
        title="New maintenance request",
        body="A tenant reported a leaking kitchen tap.",
        link="/landlord/maintenance", is_read=False,
    ))
    db.session.flush()


# ---------------------------------------------------------------------------
# Wipe (for reset) — DEMO_MODE_SPEC.md §4.3
# ---------------------------------------------------------------------------

def _wipe_landlord_scoped_rows(shadow_id: int):
    """
    Delete every row scoped to shadow_id in FK-dependency order, keeping the
    shadow Landlord + its own stub User row (reset reseeds into them). Uses
    raw table deletes (not ORM bulk delete) so we don't need every model
    class imported here, and ordering matches models.py's actual FK graph.
    """
    from sqlalchemy import text

    # Tenant user ids must be captured BEFORE tenants are deleted (the users
    # row is only reachable via tenants.user_id once tenants are gone).
    tenant_user_ids = [
        row[0] for row in
        db.session.execute(
            text("SELECT user_id FROM tenants WHERE landlord_id = :lid AND user_id IS NOT NULL"),
            {"lid": shadow_id},
        ).fetchall()
    ]

    # Children of tenants/units/properties/invoices/payments first, then the
    # landlord-scoped parents, in FK-safe order (leaves -> roots).
    statements = [
        # Payment/invoice leaves
        "DELETE FROM payment_allocations WHERE payment_id IN (SELECT id FROM payments WHERE landlord_id = :lid)",
        "DELETE FROM bank_statement_transactions WHERE bank_statement_id IN "
        "(SELECT id FROM bank_statement_uploads WHERE landlord_id = :lid)",
        "DELETE FROM balance_rollovers WHERE landlord_id = :lid",
        "DELETE FROM credit_ledger WHERE landlord_id = :lid",
        "DELETE FROM mpesa_transactions WHERE landlord_id = :lid",
        "DELETE FROM copilot_messages WHERE landlord_id = :lid",
        "DELETE FROM payments WHERE landlord_id = :lid",
        "DELETE FROM invoice_line_items WHERE invoice_id IN (SELECT id FROM invoices WHERE landlord_id = :lid)",
        "DELETE FROM utility_readings WHERE landlord_id = :lid",
        "DELETE FROM invoices WHERE landlord_id = :lid",
        "DELETE FROM bank_statement_uploads WHERE landlord_id = :lid",
        # Tenant leaves
        "DELETE FROM tenant_documents WHERE tenant_id IN (SELECT id FROM tenants WHERE landlord_id = :lid)",
        "DELETE FROM tenant_unit_history WHERE tenant_id IN (SELECT id FROM tenants WHERE landlord_id = :lid)",
        "DELETE FROM tenant_messages WHERE landlord_id = :lid",
        "DELETE FROM otp_tokens WHERE user_id IN (SELECT user_id FROM tenants WHERE landlord_id = :lid)",
        # Communications / maintenance / expenses
        "DELETE FROM communication_logs WHERE landlord_id = :lid",
        "DELETE FROM maintenance_requests WHERE landlord_id = :lid",
        "DELETE FROM expenses WHERE landlord_id = :lid",
        "DELETE FROM recurring_expenses WHERE landlord_id = :lid",
        "DELETE FROM recurring_bills WHERE landlord_id = :lid",
        # Tenants (their user rows, captured above, are deleted after).
        "DELETE FROM tenants WHERE landlord_id = :lid",
        # Structure
        "DELETE FROM manager_assignments WHERE property_id IN (SELECT id FROM properties WHERE landlord_id = :lid)",
        "DELETE FROM team_member_property_access WHERE property_id IN (SELECT id FROM properties WHERE landlord_id = :lid)",
        "DELETE FROM units WHERE property_id IN (SELECT id FROM properties WHERE landlord_id = :lid)",
        "DELETE FROM properties WHERE landlord_id = :lid",
        "DELETE FROM property_groups WHERE landlord_id = :lid",
        # Catalogue / templates / notifications / audit
        "DELETE FROM charge_categories WHERE landlord_id = :lid",
        "DELETE FROM message_templates WHERE landlord_id = :lid",
        "DELETE FROM document_templates WHERE landlord_id = :lid",
        "DELETE FROM notifications WHERE landlord_id = :lid",
        "DELETE FROM audit_logs WHERE landlord_id = :lid",
        "DELETE FROM team_members WHERE landlord_id = :lid",
        "DELETE FROM backups WHERE landlord_id = :lid",
    ]
    for stmt in statements:
        db.session.execute(text(stmt), {"lid": shadow_id})

    if tenant_user_ids:
        db.session.execute(
            text("DELETE FROM users WHERE id = ANY(:user_ids)"),
            {"user_ids": tenant_user_ids},
        )
    db.session.flush()
