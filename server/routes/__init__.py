"""
routes/__init__.py — SahilPay Blueprint Registry

Call register_blueprints(app) once inside create_app() and every
blueprint is mounted at the correct prefix. Adding a new blueprint
means two lines here: import + register. Nothing else changes.
"""

from .auth_routes             import auth_bp
from .otp_routes              import otp_bp
from .twofa_routes            import twofa_bp
from .landlord_dashboard_routes import dashboard_bp
from .property_routes         import property_bp
from .unit_routes             import unit_bp
from .property_group_routes   import group_bp
from .tenant_routes           import tenant_bp
from .tenant_import_routes    import tenant_import_bp
from .bulk_import_routes      import bulk_import_bp
from .invoice_queue_routes    import invoice_queue_bp
from .invoice_routes          import invoice_bp
from .charge_category_routes  import charge_category_bp
from .payment_routes          import payment_bp, receipts_bp
from .expense_routes          import expense_bp
from .owner_payout_routes     import owner_payout_bp
from .utility_routes          import utility_bp
from .maintenance_routes      import maintenance_bp
from .report_routes           import report_bp
from .communication_routes    import comms_bp
from .document_routes         import document_bp
from .settings_routes         import settings_bp
from .demo_routes             import demo_bp
from .team_routes             import team_bp
from .billing_routes          import billing_bp
from .mpesa_routes            import mpesa_bp
from .audit_routes            import audit_bp
from .teammember_routes       import teammember_bp
from .tenant_portal_routes    import tenant_portal_bp
from .admin_routes            import admin_bp
from .admin_pricing_routes    import admin_pricing_bp
from .admin_sms_routes        import admin_sms_bp
from .admin_trial_routes      import admin_trial_bp
from .admin_impersonation_routes import admin_impersonation_bp
from .notification_routes     import notification_bp
from .tenant_message_routes   import tenant_message_bp
from .public_routes           import public_bp
from .webhook_routes          import webhook_bp
from .admin_billing_routes    import admin_billing_bp, admin_billing_c2b_bp
from .affiliate_routes        import affiliate_bp
from .admin_affiliate_routes  import admin_affiliate_bp
from .copilot_routes          import copilot_bp
from .admin_copilot_routes    import admin_copilot_bp
from .etims_routes            import etims_bp
from .preference_routes       import preference_bp
from .allocation_routes       import allocation_bp
from .penalty_routes          import penalty_bp
from .lease_routes            import lease_bp
from .tutorial_routes         import tutorial_bp
from .admin_tutorial_routes   import admin_tutorial_bp


def register_blueprints(app):
    """Mount every blueprint. Called once from create_app()."""

    # ── Auth ──────────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)               # /api/auth
    app.register_blueprint(otp_bp)                # /api/otp
    app.register_blueprint(twofa_bp)              # /api/auth/2fa

    # ── Landlord / PM portal ──────────────────────────────────────────────────
    app.register_blueprint(dashboard_bp)          # /api/dashboard
    app.register_blueprint(property_bp)           # /api/properties
    app.register_blueprint(unit_bp)               # /api/units
    app.register_blueprint(group_bp)              # /api/property-groups
    app.register_blueprint(tenant_bp)             # /api/tenants
    app.register_blueprint(tenant_import_bp)      # /api/tenants/import
    app.register_blueprint(bulk_import_bp)        # /api/imports
    app.register_blueprint(invoice_queue_bp)      # /api/invoice-queue
    app.register_blueprint(invoice_bp)            # /api/invoices
    app.register_blueprint(charge_category_bp)    # /api/charge-categories
    app.register_blueprint(payment_bp)            # /api/payments
    app.register_blueprint(receipts_bp)           # /api/receipts (public SMS receipt link)
    app.register_blueprint(expense_bp)            # /api/expenses
    app.register_blueprint(owner_payout_bp)       # /api/owner-payouts
    app.register_blueprint(utility_bp)            # /api/utilities
    app.register_blueprint(maintenance_bp)        # /api/maintenance
    app.register_blueprint(report_bp)             # /api/reports
    app.register_blueprint(comms_bp)              # /api/communications
    app.register_blueprint(document_bp)           # /api/documents
    app.register_blueprint(settings_bp)           # /api/settings
    app.register_blueprint(demo_bp)               # /api/demo
    app.register_blueprint(team_bp)               # /api/team
    app.register_blueprint(billing_bp)            # /api/billing
    app.register_blueprint(mpesa_bp)              # /api/mpesa
    app.register_blueprint(audit_bp)              # /api/audit
    app.register_blueprint(etims_bp)              # /api/etims + /api/reports/kra-monthly
    app.register_blueprint(allocation_bp)         # /api/payments/review-queue, /api/payouts, …
    app.register_blueprint(penalty_bp)            # /api/properties/<id>/penalty-policy, /api/reports/penalties
    app.register_blueprint(lease_bp)              # /api/leases, /api/tenants/<id>/leases, /api/portal/lease

    # ── Team Member portal (thin — session / permissions only) ─────────────────
    app.register_blueprint(teammember_bp)         # /api/team-member

    # ── Tenant self-service portal ─────────────────────────────────────────────
    app.register_blueprint(tenant_portal_bp)      # /api/portal

    # ── System Admin portal ────────────────────────────────────────────────────
    app.register_blueprint(admin_bp)              # /api/admin
    app.register_blueprint(admin_pricing_bp)      # /api/admin/pricing
    app.register_blueprint(admin_sms_bp)          # /api/admin/sms
    app.register_blueprint(admin_trial_bp)        # /api/admin/trials
    app.register_blueprint(admin_impersonation_bp) # /api/admin/impersonation
    app.register_blueprint(admin_billing_bp)      # /api/admin/billing-transactions
    app.register_blueprint(admin_billing_c2b_bp)  # /api/admin/billing/c2b-payments
    app.register_blueprint(admin_affiliate_bp)    # /api/admin/affiliates
    app.register_blueprint(admin_copilot_bp)      # /api/admin/copilot
    app.register_blueprint(admin_tutorial_bp)     # /api/admin/tutorial-*

    # ── Affiliate portal (self-registration + authenticated portal) ────────────
    app.register_blueprint(affiliate_bp)          # /api/affiliate

    # ── Notifications (every role) ─────────────────────────────────────────────
    app.register_blueprint(notification_bp)       # /api/notifications
    app.register_blueprint(tenant_message_bp)     # /api/tenant-messages

    # ── Help & Tutorials (read-only, every signed-in role) ─────────────────────
    app.register_blueprint(tutorial_bp)           # /api/tutorials

    # ── Per-user UI preferences (every role) ───────────────────────────────────
    app.register_blueprint(preference_bp)         # /api/preferences

    # ── Public marketing site (unauthenticated) ────────────────────────────────
    app.register_blueprint(public_bp)             # /api/public

    # ── Provider webhooks (unauthenticated — Daraja callbacks) ─────────────────
    app.register_blueprint(webhook_bp)            # /api/webhooks

    # ── Co-Pilot SMS forwarder (device-token authenticated, not JWT) ───────────
    app.register_blueprint(copilot_bp)            # /api/copilot