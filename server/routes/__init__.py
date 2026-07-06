"""
routes/__init__.py — SahilPay Blueprint Registry

Call register_blueprints(app) once inside create_app() and every
blueprint is mounted at the correct prefix. Adding a new blueprint
means two lines here: import + register. Nothing else changes.
"""

from .auth_routes             import auth_bp
from .otp_routes              import otp_bp
from .landlord_dashboard_routes import dashboard_bp
from .property_routes         import property_bp
from .unit_routes             import unit_bp
from .property_group_routes   import group_bp
from .tenant_routes           import tenant_bp
from .invoice_routes          import invoice_bp
from .payment_routes          import payment_bp
from .expense_routes          import expense_bp
from .utility_routes          import utility_bp
from .maintenance_routes      import maintenance_bp
from .report_routes           import report_bp
from .communication_routes    import comms_bp
from .document_routes         import document_bp
from .settings_routes         import settings_bp
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


def register_blueprints(app):
    """Mount every blueprint. Called once from create_app()."""

    # ── Auth ──────────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)               # /api/auth
    app.register_blueprint(otp_bp)                # /api/otp

    # ── Landlord / PM portal ──────────────────────────────────────────────────
    app.register_blueprint(dashboard_bp)          # /api/dashboard
    app.register_blueprint(property_bp)           # /api/properties
    app.register_blueprint(unit_bp)               # /api/units
    app.register_blueprint(group_bp)              # /api/property-groups
    app.register_blueprint(tenant_bp)             # /api/tenants
    app.register_blueprint(invoice_bp)            # /api/invoices
    app.register_blueprint(payment_bp)            # /api/payments
    app.register_blueprint(expense_bp)            # /api/expenses
    app.register_blueprint(utility_bp)            # /api/utilities
    app.register_blueprint(maintenance_bp)        # /api/maintenance
    app.register_blueprint(report_bp)             # /api/reports
    app.register_blueprint(comms_bp)              # /api/communications
    app.register_blueprint(document_bp)           # /api/documents
    app.register_blueprint(settings_bp)           # /api/settings
    app.register_blueprint(team_bp)               # /api/team
    app.register_blueprint(billing_bp)            # /api/billing
    app.register_blueprint(mpesa_bp)              # /api/mpesa
    app.register_blueprint(audit_bp)              # /api/audit

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

    # ── Notifications (every role) ─────────────────────────────────────────────
    app.register_blueprint(notification_bp)       # /api/notifications
    app.register_blueprint(tenant_message_bp)     # /api/tenant-messages

    # ── Public marketing site (unauthenticated) ────────────────────────────────
    app.register_blueprint(public_bp)             # /api/public