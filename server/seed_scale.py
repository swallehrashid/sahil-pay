"""
seed_scale.py — build a property-manager-sized estate for load and UX testing.

Models the real target client: one property management company that collects
every tenant's rent into its own paybill and remits each owner their share.

    1 property manager account
    100 properties          (one per owner landlord it manages)
    10 units per property   → 1,000 units
    ~1,000 tenants          (95% occupancy, plus a few multi-unit tenants)
    100 owner team members  (preset "owner", scoped to their own property)
    200 caretaker members   (preset "caretaker", 2 per 10 properties)
    N months of real billing + payments driven through the production engine

Billing and allocation go through the SAME code paths production uses
(tasks.invoice_tasks._run_monthly_billing_for_tenant + services.allocation_service),
so every rollover, credit, arrear and statement this produces is real — which is
the point: a fixture that fakes the ledger would prove nothing about performance
or correctness.

Usage:
    APP_ENV=development venv/bin/python seed_scale.py            # create (skips if present)
    APP_ENV=development venv/bin/python seed_scale.py --wipe     # delete and rebuild
    APP_ENV=development venv/bin/python seed_scale.py --months 3 --properties 20

NEVER point this at production. It refuses to run when APP_ENV=production.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

SCALE_EMAIL = "scale-pm@sahilpay.test"
SCALE_COMPANY = "Raa Property Management (Scale Test)"

FIRST_NAMES = [
    "Amina", "Brian", "Cynthia", "Daniel", "Esther", "Felix", "Grace", "Hassan",
    "Irene", "Joyce", "Kevin", "Lydia", "Moses", "Nancy", "Otieno", "Peter",
    "Quincy", "Ruth", "Samuel", "Teresa", "Umar", "Violet", "Wilson", "Yusuf",
]
LAST_NAMES = [
    "Otieno", "Kamau", "Wanjiru", "Mwangi", "Njeri", "Omondi", "Achieng", "Ali",
    "Chebet", "Kariuki", "Mutua", "Wafula", "Kiptoo", "Naliaka", "Barasa",
]
CITIES = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret"]
STREETS = ["Ngong Road", "Argwings Kodhek", "Kilimani Lane", "Thika Road", "Waiyaki Way"]


def _log(msg: str) -> None:
    print(f"[seed_scale] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

def wipe(landlord_id: int) -> None:
    """Delete every row scoped to the scale landlord, leaves-first."""
    from sqlalchemy import text
    from extensions import db

    _log("wiping existing scale estate…")

    # Capture every user row reachable only THROUGH the landlord before the
    # landlord-scoped deletes make them unreachable — including the manager's
    # own login, or a rebuild collides on its unique email.
    tenant_user_ids = [
        r[0] for r in db.session.execute(
            text("SELECT user_id FROM tenants WHERE landlord_id=:l AND user_id IS NOT NULL"),
            {"l": landlord_id},
        ).fetchall()
    ]
    team_user_ids = [
        r[0] for r in db.session.execute(
            text("SELECT user_id FROM team_members WHERE landlord_id=:l"), {"l": landlord_id},
        ).fetchall()
    ]
    manager_user_ids = [
        r[0] for r in db.session.execute(
            text("SELECT user_id FROM landlords WHERE id=:l"), {"l": landlord_id},
        ).fetchall()
    ]

    statements = [
        "DELETE FROM payment_allocations WHERE payment_id IN (SELECT id FROM payments WHERE landlord_id=:l)",
        "DELETE FROM balance_rollovers WHERE landlord_id=:l",
        "DELETE FROM credit_ledger WHERE landlord_id=:l",
        "DELETE FROM mpesa_transactions WHERE landlord_id=:l",
        "DELETE FROM copilot_messages WHERE landlord_id=:l",
        "DELETE FROM payments WHERE landlord_id=:l",
        "DELETE FROM invoice_line_items WHERE invoice_id IN (SELECT id FROM invoices WHERE landlord_id=:l)",
        "DELETE FROM utility_readings WHERE landlord_id=:l",
        "DELETE FROM invoices WHERE landlord_id=:l",
        "DELETE FROM owner_payouts WHERE landlord_id=:l",
        "DELETE FROM tenant_documents WHERE tenant_id IN (SELECT id FROM tenants WHERE landlord_id=:l)",
        "DELETE FROM tenant_unit_history WHERE tenant_id IN (SELECT id FROM tenants WHERE landlord_id=:l)",
        "DELETE FROM tenant_messages WHERE landlord_id=:l",
        "DELETE FROM otp_tokens WHERE user_id IN (SELECT user_id FROM tenants WHERE landlord_id=:l)",
        "DELETE FROM communication_logs WHERE landlord_id=:l",
        "DELETE FROM maintenance_requests WHERE landlord_id=:l",
        "DELETE FROM expenses WHERE landlord_id=:l",
        "DELETE FROM recurring_expenses WHERE landlord_id=:l",
        "DELETE FROM recurring_bills WHERE landlord_id=:l",
        "DELETE FROM tenants WHERE landlord_id=:l",
        "DELETE FROM manager_assignments WHERE property_id IN (SELECT id FROM properties WHERE landlord_id=:l)",
        "DELETE FROM team_member_property_access WHERE property_id IN (SELECT id FROM properties WHERE landlord_id=:l)",
        "DELETE FROM team_member_permissions WHERE team_member_id IN (SELECT id FROM team_members WHERE landlord_id=:l)",
        "DELETE FROM team_members WHERE landlord_id=:l",
        "DELETE FROM units WHERE property_id IN (SELECT id FROM properties WHERE landlord_id=:l)",
        "DELETE FROM properties WHERE landlord_id=:l",
        "DELETE FROM property_groups WHERE landlord_id=:l",
        "DELETE FROM charge_categories WHERE landlord_id=:l",
        "DELETE FROM message_templates WHERE landlord_id=:l",
        "DELETE FROM document_templates WHERE landlord_id=:l",
        "DELETE FROM notifications WHERE landlord_id=:l",
        "DELETE FROM audit_logs WHERE landlord_id=:l",
        "DELETE FROM backups WHERE landlord_id=:l",
        "DELETE FROM billing_transactions WHERE landlord_id=:l",
        "DELETE FROM subscriptions WHERE landlord_id=:l",
        "DELETE FROM automation_settings WHERE landlord_id=:l",
        "DELETE FROM landlord_settings WHERE landlord_id=:l",
        "DELETE FROM alert_settings WHERE landlord_id=:l",
        "DELETE FROM trial_configs WHERE landlord_id=:l",
        "DELETE FROM landlords WHERE id=:l",
    ]
    for stmt in statements:
        db.session.execute(text(stmt), {"l": landlord_id})

    for ids in (tenant_user_ids, team_user_ids, manager_user_ids):
        if ids:
            db.session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
    db.session.commit()
    _log("wipe complete")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(properties_count: int, units_per_property: int, months: int,
          caretakers: int, office_staff: int = 0) -> dict:
    from extensions import db
    import models as m
    from utils import hash_password, gen_reference
    from services.category_service import seed_default_categories
    from services.allocation_service import auto_allocate, apply_allocations, outstanding_line_items
    from tasks.invoice_tasks import _run_monthly_billing_for_tenant

    rng = random.Random(20260806)   # deterministic estate
    today = date.today()

    # ---- The property manager account -------------------------------------
    _log(f"creating property manager '{SCALE_COMPANY}'…")
    user = m.User(
        email=SCALE_EMAIL, phone="+254700111222",
        password_hash=hash_password("ScaleTest123!"),
        role=m.UserRole.property_manager.value,
        is_verified=True, is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    landlord = m.Landlord(
        user_id=user.id, company_name=SCALE_COMPANY, abbreviated_name="RAA",
        company_address="P.O. Box 12345-00100, Nairobi",
        currency="KES", timezone="Africa/Nairobi",
        account_type=m.AccountType.property_management.value,
        mpesa_type=m.MpesaType.paybill.value, mpesa_number="247247",
        default_tax_rate=Decimal("7.50"), sms_balance=100000,
        is_on_trial=False,
    )
    db.session.add(landlord)
    db.session.flush()
    db.session.add(m.LandlordSettings(landlord_id=landlord.id, sms_enabled=True, email_enabled=True))
    db.session.add(m.AutomationSettings(
        landlord_id=landlord.id, owner_reports_enabled=True, owner_reports_day=3,
    ))
    seed_default_categories(landlord.id)
    db.session.commit()

    cats = {c.name: c for c in m.ChargeCategory.query.filter_by(landlord_id=landlord.id).all()}
    rent_cat = cats["Rent"]

    # ---- Properties + units ------------------------------------------------
    _log(f"creating {properties_count} properties × {units_per_property} units…")
    t0 = time.time()
    properties = []
    for i in range(1, properties_count + 1):
        prop = m.Property(
            landlord_id=landlord.id,
            name=f"Block {i:03d} — {rng.choice(['Sunrise', 'Green Court', 'Palm', 'Acacia', 'Riverside'])}",
            number_of_units=units_per_property,
            city=rng.choice(CITIES), street_name=rng.choice(STREETS),
            water_rate=Decimal("120"), electricity_rate=Decimal("30"),
            tax_rate=Decimal("7.50"),
            # Phase 2: the manager's commission on rent collected.
            commission_rate=Decimal("10.00"),
        )
        db.session.add(prop)
        properties.append(prop)
    db.session.flush()

    units = []
    for prop in properties:
        for u in range(1, units_per_property + 1):
            units.append(m.Unit(
                property_id=prop.id, name=f"{prop.name.split('—')[0].strip()}-{u:02d}",
                rent_amount=Decimal(str(rng.choice([8000, 10000, 12000, 15000, 20000]))),
                is_occupied=False,
            ))
    db.session.add_all(units)
    db.session.commit()
    _log(f"  … {len(properties)} properties, {len(units)} units in {time.time()-t0:.1f}s")

    # ---- Tenants -----------------------------------------------------------
    # 95% occupancy. A handful of tenants deliberately hold units in several
    # properties (the multi-unit case) — same person, separate account numbers.
    _log("creating tenants…")
    t0 = time.time()
    occupied = [u for u in units if rng.random() < 0.95]
    tenants = []
    multi_unit_phones = [f"+2547{rng.randint(10_000_000, 99_999_999)}" for _ in range(5)]

    for idx, unit in enumerate(occupied, start=1):
        fn = rng.choice(FIRST_NAMES)
        ln = rng.choice(LAST_NAMES)
        # every ~60th tenant reuses one of the multi-unit identities
        if idx % 60 == 0 and multi_unit_phones:
            phone = rng.choice(multi_unit_phones)
            fn, ln = "Multi", f"Unit{multi_unit_phones.index(phone)+1}"
        else:
            phone = f"+2547{rng.randint(10_000_000, 99_999_999)}"

        move_in = today.replace(day=1) - relativedelta(months=months + rng.randint(0, 6))
        tenant = m.Tenant(
            landlord_id=landlord.id, unit_id=unit.id,
            first_name=fn, last_name=ln,
            phone=phone, email=f"tenant{idx}@scale.sahilpay.test",
            account_number=f"RAA-{idx:05d}",
            deposit_amount=unit.rent_amount, deposit_paid=unit.rent_amount,
            deposit_returned=Decimal("0.00"), balance=Decimal("0.00"),
            lease_start_date=move_in, lease_expiry_date=move_in + relativedelta(years=1),
            move_in_date=move_in,
        )
        unit.is_occupied = True
        db.session.add(tenant)
        tenants.append(tenant)
        if idx % 250 == 0:
            db.session.flush()
    db.session.commit()

    for t in tenants:
        db.session.add(m.TenantUnitHistory(
            tenant_id=t.id, unit_id=t.unit_id, moved_in_at=t.move_in_date,
        ))
    db.session.commit()
    _log(f"  … {len(tenants)} tenants in {time.time()-t0:.1f}s")

    # ---- Team members: owners + caretakers ---------------------------------
    _log(f"creating {properties_count} owner logins + {caretakers} caretakers…")
    t0 = time.time()
    from services.team_preset_service import apply_preset_permissions

    def make_member(username, preset, property_ids, seq):
        u = m.User(
            email=f"{username}@scale.sahilpay.test",
            phone=f"+2547{rng.randint(10_000_000, 99_999_999)}",
            password_hash=hash_password("ScaleTest123!"),
            role=m.UserRole.team_member.value, is_verified=True, is_active=True,
        )
        db.session.add(u)
        db.session.flush()
        tm = m.TeamMember(
            user_id=u.id, landlord_id=landlord.id, username=username,
            first_name=preset.title(), last_name=f"{seq}",
            role="viewer" if preset == "owner" else "editor",
            preset=preset, property_access_all=False, is_active=True,
        )
        db.session.add(tm)
        db.session.flush()
        apply_preset_permissions(tm, preset)
        for pid in property_ids:
            db.session.add(m.TeamMemberPropertyAccess(team_member_id=tm.id, property_id=pid))
        return tm

    for i, prop in enumerate(properties, start=1):
        make_member(f"owner{i:03d}", "owner", [prop.id], i)
        if i % 50 == 0:
            db.session.flush()
    db.session.commit()

    # Caretakers cover a run of properties each.
    per_caretaker = max(1, properties_count // max(caretakers, 1))
    for i in range(1, caretakers + 1):
        start = ((i - 1) * per_caretaker) % properties_count
        block = properties[start:start + per_caretaker] or [properties[0]]
        make_member(f"caretaker{i:03d}", "caretaker", [p.id for p in block], i)
        if i % 50 == 0:
            db.session.flush()
    db.session.commit()

    # Office staff. A managing agent is not only owners and caretakers: the
    # people who actually touch money and tenants every day are accountants and
    # secretaries, and they hold the widest permissions in the building. Leaving
    # them out of a scale fixture means the permission matrix is never exercised
    # at the level where a mistake is expensive.
    for i in range(1, office_staff + 1):
        preset = "accountant" if i % 2 else "secretary"
        make_member(f"{preset}{i:03d}", preset, [p.id for p in properties], i)
        if i % 10 == 0:
            db.session.flush()
    db.session.commit()
    _log(f"  … team members in {time.time()-t0:.1f}s")

    # ---- Billing + payments through the real engine ------------------------
    _log(f"running {months} months of billing + payments through the production engine…")
    t0 = time.time()
    month_starts = [today.replace(day=1) - relativedelta(months=n) for n in range(months - 1, -1, -1)]

    for mi, month in enumerate(month_starts, start=1):
        billed = 0
        for tenant in tenants:
            _run_monthly_billing_for_tenant(landlord, tenant, month, month, None)
            billed += 1
            if billed % 200 == 0:
                db.session.flush()
        db.session.commit()

        # Payment behaviour spread so tenant scores are meaningful:
        #   60% pay in the first 5 days (score 100)
        #   20% pay days 6–15   (90/80)
        #   10% pay days 16–28  (70/60)
        #   10% don't pay at all this month (arrears roll over)
        paid = 0
        for tenant in tenants:
            roll = rng.random()
            if roll < 0.60:
                day = rng.randint(1, 5)
            elif roll < 0.80:
                day = rng.randint(6, 15)
            elif roll < 0.90:
                day = rng.randint(16, 28)
            else:
                continue

            due = sum((li.remaining for li in outstanding_line_items(tenant)), Decimal("0"))
            if due <= 0:
                continue
            when = month.replace(day=min(day, 28))
            payment = m.Payment(
                payment_ref=gen_reference("PMT"), landlord_id=landlord.id,
                tenant_id=tenant.id, unit_id=tenant.unit_id,
                property_id=tenant.unit.property_id, amount=due,
                payment_date=when, status=m.PaymentStatus.confirmed.value,
                source=m.PaymentSource.mpesa.value, payment_method="M-Pesa",
            )
            db.session.add(payment)
            db.session.flush()
            rows = auto_allocate(tenant, payment.amount, landlord, ref_date=when)
            apply_allocations(payment, tenant, rows, landlord.id)
            paid += 1
            if paid % 200 == 0:
                db.session.flush()
        db.session.commit()
        _log(f"  … month {mi}/{months} ({month:%b %Y}): billed {billed}, paid {paid}")

    _log(f"  … billing complete in {time.time()-t0:.1f}s")

    # ---- Expenses + owner payouts ------------------------------------------
    _log("adding expenses and owner payouts…")
    for prop in properties:
        for month in month_starts:
            db.session.add(m.Expense(
                landlord_id=landlord.id, property_id=prop.id,
                category=rng.choice(["security", "garbage", "cleaning", "maintenance"]),
                amount=Decimal(str(rng.choice([3000, 5000, 8000]))),
                payment_method="bank transfer", expense_date=month.replace(day=rng.randint(1, 27)),
                status=m.ExpenseStatus.confirmed.value, notes="Scale fixture expense.",
            ))
            db.session.add(m.OwnerPayout(
                landlord_id=landlord.id, property_id=prop.id,
                amount=Decimal(str(rng.randint(40_000, 120_000))),
                payout_date=month.replace(day=28), period=month.strftime("%Y-%m"),
                method="bank", reference=f"PAYOUT-{prop.id}-{month:%Y%m}",
            ))
    db.session.commit()

    # ---- Subscription (so the billing page is meaningful) -------------------
    from services.billing_service import recompute_subscription
    recompute_subscription(landlord)
    db.session.commit()

    return {
        "landlord_id": landlord.id,
        "properties": len(properties),
        "units": len(units),
        "tenants": len(tenants),
        "team_members": properties_count + caretakers + office_staff,
        "months": months,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a property-manager-scale estate.")
    parser.add_argument("--wipe", action="store_true", help="delete an existing scale estate first")
    parser.add_argument("--properties", type=int, default=100)
    parser.add_argument("--units", type=int, default=10, help="units per property")
    parser.add_argument("--months", type=int, default=4, help="months of billing history")
    parser.add_argument("--caretakers", type=int, default=200)
    parser.add_argument("--office", type=int, default=20,
                        help="accountants + secretaries with account-wide access")
    args = parser.parse_args()

    if (os.environ.get("APP_ENV") or "").lower() == "production":
        sys.exit("[seed_scale] refusing to run against production.")

    from app import create_app
    from extensions import db

    app = create_app()
    with app.app_context():
        from models import Landlord, User

        existing_user = User.query.filter_by(email=SCALE_EMAIL).first()
        existing = Landlord.query.filter_by(user_id=existing_user.id).first() if existing_user else None

        if existing and args.wipe:
            wipe(existing.id)
            existing = None
        elif existing:
            _log(f"scale estate already present (landlord #{existing.id}). Use --wipe to rebuild.")
            return

        # An interrupted run can leave the manager's user row behind with no
        # landlord attached. Nothing else can reach it, and it would collide on
        # the unique email, so clear it before rebuilding.
        orphan = User.query.filter_by(email=SCALE_EMAIL).first()
        if orphan is not None:
            _log("removing orphaned scale user from an interrupted run…")
            db.session.delete(orphan)
            db.session.commit()

        t0 = time.time()
        stats = build(args.properties, args.units, args.months, args.caretakers,
                      office_staff=args.office)
        _log(f"DONE in {time.time()-t0:.1f}s — {stats}")
        _log(f"Sign in as: {SCALE_EMAIL} / ScaleTest123!")
        _log("Owner login example: owner001@scale.sahilpay.test / ScaleTest123!")
        _log("Caretaker login example: caretaker001@scale.sahilpay.test / ScaleTest123!")


if __name__ == "__main__":
    main()
