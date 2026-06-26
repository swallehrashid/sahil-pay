"""
SahilPay — seed.py
===================
Idempotent demo-data seeder.  Safe to run multiple times — rows are looked
up by their natural key before insertion; nothing is duplicated.

Populates a complete vertical slice:
  Platform        → TrialConfig (global), Packages (3 tiers)
  System Admin    → users + system_admins
  Landlord        → users + landlords + LandlordSettings +
                    AutomationSettings + Subscription
  Properties      → PropertyGroup + Property + 3 Units
  Tenancy         → 2 Tenants + TenantUnitHistory
  Financial loop  → paid Invoice (T1) + open Invoice (T2)
                    + Payment + PaymentAllocation
  Operations      → UtilityReading + Expense + MaintenanceRequest +
                    MessageTemplate
  Team member     → users + team_members + TeamMemberPermissions +
                    TeamMemberPropertyAccess

Usage
-----
    python seed.py

    # Or from a Flask shell:
    from seed import seed
    seed()
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal

# ---------------------------------------------------------------------------
# Bootstrap the Flask app context before importing anything that needs it.
# ---------------------------------------------------------------------------
from app import create_app
from extensions import db

app = create_app()


def _first_of_next_month(today: date = None) -> date:
    """Return the 1st of the month following *today*."""
    if today is None:
        today = date.today()
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def _first_of_this_month(today: date = None) -> date:
    if today is None:
        today = date.today()
    return date(today.year, today.month, 1)


def _get_or_create(session, model, lookup_kwargs: dict, create_kwargs: dict = None):
    """
    Fetch a row by *lookup_kwargs*; if absent create it with
    {**lookup_kwargs, **create_kwargs}.  Returns (instance, created: bool).
    """
    instance = session.query(model).filter_by(**lookup_kwargs).first()
    if instance is not None:
        return instance, False
    merged = {**(lookup_kwargs or {}), **(create_kwargs or {})}
    instance = model(**merged)
    session.add(instance)
    session.flush()   # assign PK without committing
    return instance, True


# ---------------------------------------------------------------------------
# Main seed function
# ---------------------------------------------------------------------------

def seed() -> None:
    """
    Populate the database with demo data.
    Re-entrant: safe to call multiple times without duplicating rows.
    All changes are committed in a single transaction.
    """
    import models as m
    from utils import gen_reference, hash_password, month_str

    today = date.today()
    now = datetime.utcnow()
    trial_days = app.config["DEFAULT_TRIAL_DAYS"]

    print("\n─── SahilPay seed starting ───\n")

    try:
        # ==================================================================
        # PLATFORM LAYER
        # ==================================================================

        # ------------------------------------------------------------------
        # Global TrialConfig  (scope="global", landlord_id=NULL)
        # ------------------------------------------------------------------
        trial_cfg, created = _get_or_create(
            db.session,
            m.TrialConfig,
            lookup_kwargs={"scope": m.TrialScope.global_scope.value, "landlord_id": None},
            create_kwargs={
                "duration_days": trial_days,
                "is_active": True,
            },
        )
        print(f"  {'Created' if created else 'Found  '} TrialConfig  (global, {trial_days} days)")

        # ------------------------------------------------------------------
        # Tiered Packages  (Starter / Growth / Scale)
        # ------------------------------------------------------------------
        package_specs = [
            {
                "name": "Starter",
                "min_units": 20,
                "max_units": 50,
                "price_per_unit": Decimal("50.00"),
                "flat_price": None,
                "is_active": True,
            },
            {
                "name": "Growth",
                "min_units": 50,
                "max_units": 70,
                "price_per_unit": Decimal("40.00"),
                "flat_price": None,
                "is_active": True,
            },
            {
                "name": "Scale",
                "min_units": 70,
                "max_units": 100,
                "price_per_unit": Decimal("30.00"),
                "flat_price": None,
                "is_active": True,
            },
        ]
        packages: dict[str, m.Package] = {}
        for spec in package_specs:
            pkg, created = _get_or_create(
                db.session,
                m.Package,
                lookup_kwargs={"name": spec["name"]},
                create_kwargs={k: v for k, v in spec.items() if k != "name"},
            )
            packages[spec["name"]] = pkg
            print(f"  {'Created' if created else 'Found  '} Package      '{pkg.name}'")

        # ==================================================================
        # SYSTEM ADMIN
        # ==================================================================

        admin_user, created = _get_or_create(
            db.session,
            m.User,
            lookup_kwargs={"email": "admin@sahilpay.test"},
            create_kwargs={
                "role": m.UserRole.system_admin.value,
                "password_hash": hash_password("Admin@123"),
                "is_verified": True,
                "is_active": True,
            },
        )
        print(f"  {'Created' if created else 'Found  '} User         admin@sahilpay.test")

        _get_or_create(
            db.session,
            m.SystemAdmin,
            lookup_kwargs={"user_id": admin_user.id},
            create_kwargs={"first_name": "Platform", "last_name": "Admin"},
        )

        # ==================================================================
        # LANDLORD (demo paying customer)
        # ==================================================================

        landlord_user, created = _get_or_create(
            db.session,
            m.User,
            lookup_kwargs={"email": "landlord@sahilpay.test"},
            create_kwargs={
                "phone": "+254700000001",
                "role": m.UserRole.landlord.value,
                "password_hash": hash_password("Landlord@123"),
                "is_verified": True,
                "is_active": True,
            },
        )
        print(f"  {'Created' if created else 'Found  '} User         landlord@sahilpay.test")

        landlord, created = _get_or_create(
            db.session,
            m.Landlord,
            lookup_kwargs={"company_name": "Acme Properties Ltd"},
            create_kwargs={
                "user_id": landlord_user.id,
                "abbreviated_name": "Acme",
                "currency": "KES",
                "timezone": "Africa/Nairobi",
                "account_type": m.AccountType.landlord.value,
                "mpesa_type": m.MpesaType.paybill.value,
                "mpesa_number": "123456",
                "default_account_number": "ACME",
                "default_tax_rate": Decimal("7.50"),
                "sms_balance": 500,
                "is_on_trial": True,
                "trial_ends_at": now + timedelta(days=trial_days),
                "package_id": packages["Growth"].id,
                "per_unit_price": None,
                "agent_code": "ACME-AGENT-001",
            },
        )
        print(f"  {'Created' if created else 'Found  '} Landlord     Acme Properties Ltd")

        # 1:1 children — create only if absent

        # LandlordSettings
        ls_exists = db.session.query(m.LandlordSettings).filter_by(landlord_id=landlord.id).first()
        if ls_exists is None:
            db.session.add(m.LandlordSettings(
                landlord_id=landlord.id,
                sms_enabled=True,
                whatsapp_enabled=False,
                email_enabled=True,
                low_sms_balance_threshold=50,
            ))
            db.session.flush()
            print("  Created       LandlordSettings")

        # AutomationSettings
        as_exists = db.session.query(m.AutomationSettings).filter_by(landlord_id=landlord.id).first()
        if as_exists is None:
            db.session.add(m.AutomationSettings(
                landlord_id=landlord.id,
                auto_generate_recurring_invoices=True,
                auto_generate_recurring_bills=True,
                alert_on_new_tenant=True,
                auto_send_payment_acknowledgments=True,
                monthly_reminders_enabled=True,
                monthly_reminder_day=1,
                lease_expiry_notifications=True,
                lease_expiry_range_days=30,
            ))
            db.session.flush()
            print("  Created       AutomationSettings")

        # Subscription  (unit_count seeded as 3 — matches units created below)
        sub_exists = db.session.query(m.Subscription).filter_by(landlord_id=landlord.id).first()
        if sub_exists is None:
            subscription_cost = packages["Growth"].price_per_unit * 3  # 3 units × 40.00
            db.session.add(m.Subscription(
                landlord_id=landlord.id,
                plan=m.SubscriptionPlan.monthly.value,
                unit_count=3,
                subscription_cost=subscription_cost,
                billing_cycle=m.BillingCycle.monthly.value,
                discount_rate=Decimal("0.00"),
                amount_due=Decimal("0.00"),
                next_billing_date=_first_of_next_month(today),
                status=m.SubscriptionStatus.trial.value,
            ))
            db.session.flush()
            print(f"  Created       Subscription     (trial, KES {subscription_cost}/mo)")

        # ==================================================================
        # PROPERTY STRUCTURE
        # ==================================================================

        pg, created = _get_or_create(
            db.session,
            m.PropertyGroup,
            lookup_kwargs={"landlord_id": landlord.id, "name": "Nairobi Portfolio"},
        )
        print(f"  {'Created' if created else 'Found  '} PropertyGroup 'Nairobi Portfolio'")

        prop, created = _get_or_create(
            db.session,
            m.Property,
            lookup_kwargs={"landlord_id": landlord.id, "name": "Riverside Apartments"},
            create_kwargs={
                "property_group_id": pg.id,
                "number_of_units": 3,
                "city": "Nairobi",
                "street_name": "Riverside Dr",
                "water_rate": Decimal("100.00"),
                "electricity_rate": Decimal("25.00"),
                "tax_rate": Decimal("7.50"),
                "is_deleted": False,
            },
        )
        print(f"  {'Created' if created else 'Found  '} Property     'Riverside Apartments'")

        # 3 Units: A1 (occupied), A2 (occupied), A3 (vacant)
        unit_specs = [
            {"name": "A1", "rent_amount": Decimal("25000.00"), "is_occupied": True},
            {"name": "A2", "rent_amount": Decimal("25000.00"), "is_occupied": True},
            {"name": "A3", "rent_amount": Decimal("25000.00"), "is_occupied": False},
        ]
        units: dict[str, m.Unit] = {}
        for spec in unit_specs:
            unit, created = _get_or_create(
                db.session,
                m.Unit,
                lookup_kwargs={"property_id": prop.id, "name": spec["name"]},
                create_kwargs={
                    "rent_amount": spec["rent_amount"],
                    "tax_rate": None,      # inherits property tax_rate
                    "is_occupied": spec["is_occupied"],
                    "is_deleted": False,
                },
            )
            units[spec["name"]] = unit
            occupancy = "occupied" if spec["is_occupied"] else "vacant "
            print(f"  {'Created' if created else 'Found  '} Unit         {spec['name']} ({occupancy})")

        # ==================================================================
        # TENANCY
        # ==================================================================

        tenant_specs = [
            {
                "phone": "+254711000001",
                "first_name": "James",
                "last_name": "Mwangi",
                "email": "james.mwangi@tenant.test",
                "unit_name": "A1",
                "account_number": "ACME-T001",
            },
            {
                "phone": "+254711000002",
                "first_name": "Amina",
                "last_name": "Hassan",
                "email": "amina.hassan@tenant.test",
                "unit_name": "A2",
                "account_number": "ACME-T002",
            },
        ]
        tenants: dict[str, m.Tenant] = {}
        move_in = date(today.year, today.month, 1)

        for tspec in tenant_specs:
            unit = units[tspec["unit_name"]]

            # Create a linked User for OTP login (password_hash=NULL for tenants)
            t_user, _ = _get_or_create(
                db.session,
                m.User,
                lookup_kwargs={"phone": tspec["phone"], "role": m.UserRole.tenant.value},
                create_kwargs={
                    "email": tspec["email"],
                    "password_hash": None,      # OTP-only — no password
                    "is_verified": False,       # verified on first OTP login
                    "is_active": True,
                },
            )

            tenant, created = _get_or_create(
                db.session,
                m.Tenant,
                lookup_kwargs={"phone": tspec["phone"]},
                create_kwargs={
                    "user_id": t_user.id,
                    "landlord_id": landlord.id,
                    "unit_id": unit.id,
                    "first_name": tspec["first_name"],
                    "last_name": tspec["last_name"],
                    "email": tspec["email"],
                    "account_number": tspec["account_number"],
                    "deposit_amount": Decimal("25000.00"),
                    "deposit_paid": Decimal("25000.00"),
                    "deposit_returned": Decimal("0.00"),
                    "balance": Decimal("0.00"),     # updated below per invoice state
                    "lease_start_date": move_in,
                    "lease_expiry_date": date(today.year + 1, today.month, 1),
                    "move_in_date": move_in,
                    "is_deleted": False,
                },
            )
            tenants[tspec["phone"]] = tenant
            print(f"  {'Created' if created else 'Found  '} Tenant       {tspec['first_name']} {tspec['last_name']}")

            # TenantUnitHistory — current occupancy (moved_out_at=NULL)
            hist_exists = db.session.query(m.TenantUnitHistory).filter_by(
                tenant_id=tenant.id,
                unit_id=unit.id,
                moved_out_at=None,
            ).first()
            if hist_exists is None:
                db.session.add(m.TenantUnitHistory(
                    tenant_id=tenant.id,
                    unit_id=unit.id,
                    moved_in_at=move_in,
                    moved_out_at=None,
                ))

        db.session.flush()
        tenant1 = tenants["+254711000001"]   # James — will get PAID invoice
        tenant2 = tenants["+254711000002"]   # Amina — will get OPEN invoice

        # ==================================================================
        # FINANCIAL LOOP
        # ==================================================================

        month_label = today.strftime("%B %Y")        # e.g. "June 2026"
        issue_date = _first_of_this_month(today)
        due_date = date(today.year, today.month, 5)

        # ------------------------------------------------------------------
        # Tenant 1 — PAID rent invoice + confirmed payment
        # ------------------------------------------------------------------
        inv1_num = gen_reference("INV")
        # Check existence by unique (landlord_id, invoice_number)
        # Use execution_options(include_deleted=True) in case of soft-delete
        inv1 = (
            db.session.query(m.Invoice)
            .execution_options(include_deleted=True)
            .filter_by(landlord_id=landlord.id, tenant_id=tenant1.id)
            .filter(m.Invoice.status == m.InvoiceStatus.paid.value)
            .first()
        )
        if inv1 is None:
            inv1 = m.Invoice(
                invoice_number=inv1_num,
                landlord_id=landlord.id,
                tenant_id=tenant1.id,
                unit_id=units["A1"].id,
                property_id=prop.id,
                invoice_type=m.InvoiceType.rent.value,
                issue_date=issue_date,
                due_date=due_date,
                status=m.InvoiceStatus.paid.value,
                total_amount=Decimal("25000.00"),
                amount_paid=Decimal("25000.00"),
                balance=Decimal("0.00"),
                title=f"Rent — {month_label}",
                is_deleted=False,
            )
            db.session.add(inv1)
            db.session.flush()

            line1 = m.InvoiceLineItem(
                invoice_id=inv1.id,
                item="Rent",
                description=f"Monthly rent for {month_label}",
                quantity=Decimal("1"),
                unit_price=Decimal("25000.00"),
                amount=Decimal("25000.00"),
            )
            db.session.add(line1)
            db.session.flush()

            print(f"  Created       Invoice      {inv1.invoice_number} (paid, James)")

            # Payment
            pmt1_ref = gen_reference("PMT")
            pmt1 = m.Payment(
                payment_ref=pmt1_ref,
                landlord_id=landlord.id,
                tenant_id=tenant1.id,
                unit_id=units["A1"].id,
                property_id=prop.id,
                amount=Decimal("25000.00"),
                payment_date=issue_date,
                status=m.PaymentStatus.confirmed.value,
                source=m.PaymentSource.mpesa.value,
                payment_method="M-Pesa",
                mpesa_reference="ABC123XYZ",
                till_number="123456",
                is_deleted=False,
            )
            db.session.add(pmt1)
            db.session.flush()
            print(f"  Created       Payment      {pmt1.payment_ref} (M-Pesa, James)")

            # PaymentAllocation (M:N link between payment and invoice)
            alloc1 = m.PaymentAllocation(
                payment_id=pmt1.id,
                invoice_id=inv1.id,
                amount_allocated=Decimal("25000.00"),
            )
            db.session.add(alloc1)
            db.session.flush()
            print("  Created       PaymentAllocation (pmt1 → inv1)")
        else:
            print(f"  Found         Invoice      (paid, James) — skipping payment")

        # ------------------------------------------------------------------
        # Tenant 2 — OPEN (unpaid) rent invoice — creates arrears
        # ------------------------------------------------------------------
        inv2 = (
            db.session.query(m.Invoice)
            .execution_options(include_deleted=True)
            .filter_by(landlord_id=landlord.id, tenant_id=tenant2.id)
            .filter(m.Invoice.status == m.InvoiceStatus.open.value)
            .first()
        )
        if inv2 is None:
            inv2_num = gen_reference("INV")
            inv2 = m.Invoice(
                invoice_number=inv2_num,
                landlord_id=landlord.id,
                tenant_id=tenant2.id,
                unit_id=units["A2"].id,
                property_id=prop.id,
                invoice_type=m.InvoiceType.rent.value,
                issue_date=issue_date,
                due_date=due_date,
                status=m.InvoiceStatus.open.value,
                total_amount=Decimal("25000.00"),
                amount_paid=Decimal("0.00"),
                balance=Decimal("25000.00"),
                title=f"Rent — {month_label}",
                is_deleted=False,
            )
            db.session.add(inv2)
            db.session.flush()

            line2 = m.InvoiceLineItem(
                invoice_id=inv2.id,
                item="Rent",
                description=f"Monthly rent for {month_label}",
                quantity=Decimal("1"),
                unit_price=Decimal("25000.00"),
                amount=Decimal("25000.00"),
            )
            db.session.add(line2)
            db.session.flush()

            # Reflect arrears on the tenant record
            tenant2.balance = Decimal("-25000.00")   # negative = owes money
            db.session.add(tenant2)

            print(f"  Created       Invoice      {inv2.invoice_number} (open/arrears, Amina)")
        else:
            print(f"  Found         Invoice      (open, Amina) — skipping")

        # ==================================================================
        # OPERATIONS SAMPLER
        # ==================================================================

        # UtilityReading — water for unit A1 this month
        ur_exists = db.session.query(m.UtilityReading).filter_by(
            landlord_id=landlord.id,
            unit_id=units["A1"].id,
            utility_item=m.UtilityItem.water.value,
            reading_month=month_str(today),
        ).first()
        if ur_exists is None:
            ur = m.UtilityReading(
                landlord_id=landlord.id,
                property_id=prop.id,
                unit_id=units["A1"].id,
                utility_item=m.UtilityItem.water.value,
                previous_reading=Decimal("100.00"),
                current_reading=Decimal("112.00"),
                consumption=Decimal("12.00"),
                reading_month=month_str(today),
                invoice_id=None,   # not yet linked to an invoice
            )
            db.session.add(ur)
            db.session.flush()
            print("  Created       UtilityReading  (water, A1)")

        # Expense — security at property level
        exp_exists = (
            db.session.query(m.Expense)
            .execution_options(include_deleted=True)
            .filter_by(
                landlord_id=landlord.id,
                property_id=prop.id,
                category=m.ExpenseCategory.security.value,
                expense_date=issue_date,
            ).first()
        )
        if exp_exists is None:
            exp = m.Expense(
                landlord_id=landlord.id,
                property_id=prop.id,
                unit_id=None,
                category=m.ExpenseCategory.security.value,
                amount=Decimal("8000.00"),
                payment_method="cash",
                expense_date=issue_date,
                status=m.ExpenseStatus.confirmed.value,
                notes="Monthly security guard fee.",
                is_deleted=False,
            )
            db.session.add(exp)
            db.session.flush()
            print("  Created       Expense         (security, KES 8,000)")

        # MaintenanceRequest — plumbing in A2 (Amina's unit)
        maint_exists = db.session.query(m.MaintenanceRequest).filter_by(
            landlord_id=landlord.id,
            unit_id=units["A2"].id,
            summary="Leaking kitchen tap",
        ).first()
        if maint_exists is None:
            maint = m.MaintenanceRequest(
                landlord_id=landlord.id,
                property_id=prop.id,
                unit_id=units["A2"].id,
                tenant_id=tenant2.id,
                summary="Leaking kitchen tap",
                description="Cold water tap in kitchen has been dripping for two days.",
                category=m.MaintenanceCategory.plumbing.value,
                status=m.MaintenanceStatus.open.value,
                image_url=None,
                expense_id=None,
            )
            db.session.add(maint)
            db.session.flush()
            print("  Created       MaintenanceRequest  (plumbing, A2)")

        # MessageTemplate — balance reminder SMS
        mt_exists = db.session.query(m.MessageTemplate).filter_by(
            landlord_id=landlord.id,
            name="Balance Reminder",
        ).first()
        if mt_exists is None:
            mt = m.MessageTemplate(
                landlord_id=landlord.id,
                name="Balance Reminder",
                channel=m.MessageChannel.sms.value,
                template_type=m.MessageTemplateType.balance_reminder.value,
                body=(
                    "Hi {tenant_name}, your current balance is KES {balance}. "
                    "Please pay via Paybill 123456, account: {account_number}. "
                    "Thank you — Acme Properties."
                ),
            )
            db.session.add(mt)
            db.session.flush()
            print("  Created       MessageTemplate  (Balance Reminder SMS)")

        # ==================================================================
        # TEAM MEMBER  (exercises the permission matrix)
        # ==================================================================

        caretaker_user, created = _get_or_create(
            db.session,
            m.User,
            lookup_kwargs={"email": "caretaker@sahilpay.test"},
            create_kwargs={
                "role": m.UserRole.team_member.value,
                "password_hash": hash_password("Caretaker@123"),
                "is_verified": True,
                "is_active": True,
            },
        )
        print(f"  {'Created' if created else 'Found  '} User         caretaker@sahilpay.test")

        caretaker_tm, created = _get_or_create(
            db.session,
            m.TeamMember,
            lookup_kwargs={"user_id": caretaker_user.id},
            create_kwargs={
                "landlord_id": landlord.id,
                "username": "caretaker1",
                "first_name": "David",
                "last_name": "Otieno",
                "phone": "+254722000001",
                "role": m.TeamMemberRole.editor.value,
                "property_access_all": False,
                "is_active": True,
            },
        )
        print(f"  {'Created' if created else 'Found  '} TeamMember   caretaker1")

        # Permission matrix — one row per PermissionModule
        # (spec §5: can_edit=True forces can_view=True)
        permission_grants = {
            m.PermissionModule.payments.value:       (True, True),    # view + edit
            m.PermissionModule.invoices.value:       (True, True),
            m.PermissionModule.utilities.value:      (True, True),
            m.PermissionModule.unit_utilities.value: (True, True),
            m.PermissionModule.tenants.value:        (True, True),
            m.PermissionModule.units.value:          (True, False),   # view only
            m.PermissionModule.properties.value:     (True, False),   # view only
            m.PermissionModule.messages.value:       (True, True),
        }
        for module_val, (can_view, can_edit) in permission_grants.items():
            perm_exists = db.session.query(m.TeamMemberPermission).filter_by(
                team_member_id=caretaker_tm.id,
                module=module_val,
            ).first()
            if perm_exists is None:
                db.session.add(m.TeamMemberPermission(
                    team_member_id=caretaker_tm.id,
                    module=module_val,
                    can_view=can_view,
                    can_edit=can_edit,
                ))

        # Property access — scoped to Riverside Apartments only
        pa_exists = db.session.query(m.TeamMemberPropertyAccess).filter_by(
            team_member_id=caretaker_tm.id,
            property_id=prop.id,
        ).first()
        if pa_exists is None:
            db.session.add(m.TeamMemberPropertyAccess(
                team_member_id=caretaker_tm.id,
                property_id=prop.id,
            ))
        db.session.flush()
        print("  Created/found  TeamMemberPermissions + PropertyAccess")

        # ==================================================================
        # Commit everything in one transaction
        # ==================================================================
        db.session.commit()
        print("\n─── Seed committed successfully ───\n")

    except Exception as exc:
        db.session.rollback()
        print(f"\n✗ Seed failed — rolled back.  Error: {exc}")
        raise

    # ------------------------------------------------------------------
    # Print login credentials
    # ------------------------------------------------------------------
    _print_credentials()


def _print_credentials() -> None:
    """Print a summary of seeded accounts for developer reference."""
    width = 70
    print("=" * width)
    print("  SEEDED ACCOUNTS — use these to log in")
    print("=" * width)
    print(f"  {'Role':<18}  {'Email / Phone':<35}  Password")
    print("-" * width)
    print(f"  {'SYSTEM ADMIN':<18}  {'admin@sahilpay.test':<35}  Admin@123")
    print(f"  {'LANDLORD':<18}  {'landlord@sahilpay.test':<35}  Landlord@123")
    print(f"  {'TEAM MEMBER':<18}  {'caretaker@sahilpay.test':<35}  Caretaker@123")
    print(f"  {'TENANT (OTP)':<18}  {'+254711000001 / +254711000002':<35}  POST /api/otp/request")
    print("=" * width)
    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        # db.create_all() is acceptable here for local bootstrap.
        # Production should use: flask db upgrade
        db.create_all()
        seed()