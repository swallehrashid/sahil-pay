"""
seed_production.py — the ONLY data a fresh production database starts with.

Deliberately NOT seed.py. seed.py creates a full demo estate (landlords,
tenants, units, invoices, payments, team members, affiliates, a demo shadow)
which must never exist in production. This script inserts only:

  * TrialConfig            — the global free-trial window
  * AffiliateProgramConfig — commission/withholding defaults
  * Package x3             — Starter / Growth / Scale subscription tiers
                             (a 4th, "Custom", is inserted by its own migration)
  * SmsParserTemplate x12  — Co-pilot bank/M-Pesa parser presets
  * SystemAdmin            — the platform owner's login

Several of these (AffiliateProgramConfig, the parser templates, the Custom
package) are ALSO inserted by data migrations, so on a freshly-migrated database
this script will report most of them as already present and only fill the gaps.
That is expected — the point is that the end state is correct either way.

Everything else (landlords, their tenants, units, charge categories) is created
through the app when a real client is onboarded.

Usage (on the server, as the sahilpay user):

    cd /var/www/sahilpay/app/server
    APP_ENV=production venv/bin/python seed_production.py

Idempotent: re-running will not duplicate rows. It inserts only what's missing,
so it is safe to run against a database that already has some presets.

The admin password is read from ADMIN_PASSWORD in the environment. It is never
hardcoded here — this file is committed to a public repository.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

from app import create_app
from extensions import db


def _admin_credentials() -> tuple[str, str]:
    """Admin email/password from env. Refuses to invent a default password."""
    email = os.environ.get("ADMIN_EMAIL", "sahilpayke@gmail.com").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not password:
        sys.exit(
            "ADMIN_PASSWORD is not set.\n"
            "Run it inline so the password never lands in your shell history:\n"
            "    ADMIN_PASSWORD='your-password' venv/bin/python seed_production.py\n"
        )
    if len(password) < 10:
        sys.exit("ADMIN_PASSWORD must be at least 10 characters.")
    return email, password


# The Co-pilot parser presets. Kept identical to seed.py's set and to
# migrations/versions/c1a2b3d4e5f6_copilot_bank_preset_templates.py so a
# production database and a dev one parse the same SMS the same way.
SMS_PARSER_TEMPLATES = [
    ("M-Pesa C2B (received from)", "MPESA",
     "{ref} Confirmed. {*}Ksh{amount} received from {name} {phone} on {*}",
     "QCA1B2C3D4 Confirmed. Ksh1,500.00 received from JOHN DOE 254712345678 on 1/6/25 at 10:34 AM",
     100),
    ("M-Pesa paybill with account", "MPESA",
     "{ref} Confirmed.{*}Ksh{amount}{*}received from {name} {phone}{*}for account {account}{*}",
     "QCA1B2C3D5 Confirmed. Ksh1,500.00 received from JOHN DOE 254712345678 for account A12 on 1/6/25 at 10:34 AM",
     90),
    ("M-Pesa till (buy goods received)", "MPESA",
     "{ref} Confirmed. {*}Ksh{amount}{*}received from {name} {phone}{*}",
     "RJK5X9PLMN Confirmed. Ksh2,000.00 received from JAMES MWANGI 254711000001 for till on 22/7/26",
     95),
    ("KCB credit alert", "KCB",
     "{*}KES {amount} received from {name} to your account {account}, Ref {ref}{*}",
     "Dear Customer, KES 15,000.00 received from JANE WANJIKU to your account A12, Ref FT2312345678 on 01-06-2025.",
     100),
    ("Equity credit alert", "EQUITY BANK",
     "{*}received KES {amount} from {name}. Ref: {ref}{*}",
     "You have received KES 10,000.00 from PETER OTIENO. Ref: EQ12345678. Available balance is KES 25,000.00.",
     100),
    ("Co-op Bank credit", "CO-OP BANK",
     "{*}received Ksh{amount} from {name} to your account {account}. Ref {ref}{*}",
     "Dear customer, you have received Ksh2,500.00 from MARY ATIENO to your account ACME-T001. Ref CO123456AB. Thank you.",
     100),
    ("NCBA credit", "NCBA",
     "{*}credited with KES {amount} on {*} from {name}. Ref {ref}{*}",
     "Your account has been credited with KES 4,000.00 on 22/07 from JOHN KAMAU. Ref NC789012CD available balance KES 9,000.",
     100),
    ("Absa credit", "ABSA",
     "{*}received KES {amount} from {name} to account {account}. Ref {ref}{*}",
     "Absa: You have received KES 6,300.00 from PETER O to account ACME-T003. Ref AB456789EF on 22/07/2026.",
     100),
    ("Family Bank credit", "FAMILY BANK",
     "{*}KES {amount} received from {name} to your account {account}, Ref {ref}{*}",
     "FamilyBank: KES 1,200.00 received from GRACE W to your account ACME-T004, Ref FB321654GH. Bal KES 3,000.",
     100),
    ("DTB credit", "DTB",
     "{*}received KES {amount} from {name}. Ref {ref}{*}",
     "DTB: You have received KES 7,700.00 from BRIAN K. Ref DT147258IJ. Thank you for banking with DTB.",
     100),
    ("Stanbic credit", "STANBIC",
     "{*}credited KES {amount} from {name}. Ref {ref}{*}",
     "Stanbic: Your account credited KES 5,500.00 from AMINA H. Ref ST963852KL on 22 Jul.",
     100),
    ("I&M credit", "I&M",
     "{*}received KES {amount} from {name} to your account {account} Ref {ref}{*}",
     "I&M Bank: received KES 8,800.00 from DIANA A to your account ACME-T005 Ref IM852741MN.",
     100),
]

PACKAGE_SPECS = [
    {"name": "Starter", "min_units": 1,  "max_units": 20,   "price_per_unit": Decimal("50.00")},
    {"name": "Growth",  "min_units": 21, "max_units": 70,   "price_per_unit": Decimal("40.00")},
    {"name": "Scale",   "min_units": 71, "max_units": None, "price_per_unit": Decimal("30.00")},
]


def seed_presets(app) -> None:
    import models as m
    from utils import hash_password

    admin_email, admin_password = _admin_credentials()
    created: list[str] = []
    skipped: list[str] = []

    # --- Global trial window -------------------------------------------------
    existing_trial = m.TrialConfig.query.filter_by(
        scope=m.TrialScope.global_scope.value, landlord_id=None
    ).first()
    if existing_trial is None:
        db.session.add(m.TrialConfig(
            scope=m.TrialScope.global_scope.value, landlord_id=None,
            duration_days=app.config["DEFAULT_TRIAL_DAYS"], is_active=True,
        ))
        created.append(f"TrialConfig ({app.config['DEFAULT_TRIAL_DAYS']} days)")
    else:
        skipped.append("TrialConfig")

    # --- Affiliate programme defaults ---------------------------------------
    if m.AffiliateProgramConfig.query.first() is None:
        db.session.add(m.AffiliateProgramConfig(
            default_commission_rate=Decimal("40.00"), default_commission_months=4,
            min_withdrawal=Decimal("500.00"), wht_rate=Decimal("5.00"),
            fee_type="percent", fee_value=Decimal("3.00"),
            attribution_grace_days=7, is_program_active=True,
        ))
        created.append("AffiliateProgramConfig (40% / 4 months)")
    else:
        skipped.append("AffiliateProgramConfig")

    # --- Subscription packages ----------------------------------------------
    for spec in PACKAGE_SPECS:
        if m.Package.query.filter_by(name=spec["name"]).first() is None:
            db.session.add(m.Package(
                name=spec["name"], min_units=spec["min_units"], max_units=spec["max_units"],
                price_per_unit=spec["price_per_unit"], flat_price=None, is_active=True,
            ))
            created.append(f"Package {spec['name']}")
        else:
            skipped.append(f"Package {spec['name']}")

    # --- Co-pilot SMS parser presets ----------------------------------------
    for name, sender_id, template_text, sample_text, priority in SMS_PARSER_TEMPLATES:
        if m.SmsParserTemplate.query.filter_by(name=name, sender_id=sender_id).first() is None:
            db.session.add(m.SmsParserTemplate(
                name=name, sender_id=sender_id, template_text=template_text,
                sample_text=sample_text, is_active=True, priority=priority,
            ))
            created.append(f"Parser template {name}")
        else:
            skipped.append(f"Parser template {name}")

    # --- Platform owner admin ------------------------------------------------
    admin_user = m.User.query.filter_by(email=admin_email).first()
    if admin_user is None:
        admin_user = m.User(
            email=admin_email, role=m.UserRole.system_admin.value,
            password_hash=hash_password(admin_password),
            is_verified=True, is_active=True,
        )
        db.session.add(admin_user)
        db.session.flush()
        db.session.add(m.SystemAdmin(
            user_id=admin_user.id, first_name="Sahil", last_name="Pay",
        ))
        created.append(f"System admin {admin_email}")
    else:
        # Re-running resets the password to whatever ADMIN_PASSWORD now holds,
        # which doubles as the account-recovery path.
        admin_user.password_hash = hash_password(admin_password)
        admin_user.role = m.UserRole.system_admin.value
        admin_user.is_active = True
        admin_user.is_verified = True
        if m.SystemAdmin.query.filter_by(user_id=admin_user.id).first() is None:
            db.session.add(m.SystemAdmin(
                user_id=admin_user.id, first_name="Sahil", last_name="Pay",
            ))
        created.append(f"System admin {admin_email} (password reset)")

    db.session.commit()

    print("\n─── Production presets seeded ───")
    for item in created:
        print(f"  + {item}")
    for item in skipped:
        print(f"  = {item} (already present, left alone)")

    # --- Safety report: prove no tenant-facing data exists -------------------
    counts = {
        "landlords":    m.Landlord.query.count(),
        "tenants":      m.Tenant.query.count(),
        "units":        m.Unit.query.count(),
        "properties":   m.Property.query.count(),
        "team members": m.TeamMember.query.count(),
        "affiliates":   m.Affiliate.query.count(),
        "invoices":     m.Invoice.query.count(),
        "payments":     m.Payment.query.count(),
    }
    print("\n─── Occupancy check (all should be 0 on a fresh launch) ───")
    for label, n in counts.items():
        flag = "" if n == 0 else "   <-- NOT EMPTY"
        print(f"  {label:<14} {n}{flag}")
    print(f"\n  admins: {m.SystemAdmin.query.count()}   packages: {m.Package.query.count()}"
          f"   parser templates: {m.SmsParserTemplate.query.count()}")
    print("\nDone. Log in at /login with the admin email above.\n")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        seed_presets(app)
