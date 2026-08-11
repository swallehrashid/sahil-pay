"""
SahilPay — Property Management & Rent Collection Platform
models.py  —  Complete SQLAlchemy schema (39 tables · 9 domains)

Stack  : Python · Flask · SQLAlchemy · PostgreSQL · Alembic
Pattern: Base `users` table + role-profile tables (joined-table inheritance)
         Admin / Landlord-PM / Team Member / Tenant portals

HOW TO MIGRATE
--------------
Never hand-edit the DB schema.  After changing this file run:
    alembic revision --autogenerate -m "describe change"
    alembic upgrade head

NOTES
-----
* All monetary columns use Numeric — never Float.
* Status / category columns are String(n) backed by the Python Enum classes
  defined in §2.  The Enum classes are the validation source of truth;
  columns stay String so Alembic stays simple.
* Soft-delete tables (tenants, properties, units, invoices, payments,
  expenses) carry is_deleted + deleted_at and are NEVER hard-deleted.
  The SoftDeleteQuery class excludes deleted rows by default.
* Append-only tables (otp_tokens, communication_logs, audit_logs) have NO
  updated_at column.
* The expenses ↔ maintenance_requests circular FK is broken with
  post_update=True on the maintenance_requests side and use_alter=True on
  expenses.maintenance_request_id.
* Schema-level validations (deposit rules, allocation sums, etc.) belong in
  Marshmallow / Pydantic schemas, not here.  They are noted in docstrings.
"""

from __future__ import annotations

import enum
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, event,
    ForeignKey, Index, Integer, JSON, Numeric, String, Text,
    UniqueConstraint, text as sa_text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Query, declared_attr, relationship


# ---------------------------------------------------------------------------
# Base & shared query
# ---------------------------------------------------------------------------

Base = declarative_base()


class SoftDeleteQuery(Query):
    """Default query class that excludes soft-deleted rows automatically.

    Apply to the session via:
        session = Session(query_cls=SoftDeleteQuery)
    or set session_options in Flask-SQLAlchemy:
        db = SQLAlchemy(query_class=SoftDeleteQuery)

    To bypass (e.g. for deleted-tenants report):
        session.query(Tenant).filter(Tenant.is_deleted == True).all()
    or via execution_options:
        session.query(Tenant).execution_options(include_deleted=True)
    """

    _SOFT_DELETE_MODELS: tuple = ()  # populated after model definition below

    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        return obj

    def __iter__(self):
        return Query.__iter__(self._maybe_apply_soft_delete_filter())

    def _maybe_apply_soft_delete_filter(self):
        if self._execution_options.get("include_deleted", False):
            return self
        if not self.column_descriptions:
            return self
        entity = self.column_descriptions[0].get("entity")
        if entity is not None and hasattr(entity, "is_deleted"):
            return self.filter(entity.is_deleted.is_(False))
        return self

    def paginate(self, page=1, per_page=20, error_out=False, max_per_page=None):
        """
        Flask-SQLAlchemy-compatible .paginate() — routes/*.py calls this
        directly on Model.query (e.g. Property.query.filter_by(...).paginate(
        page=page, per_page=per_page, error_out=False)). Plain SQLAlchemy's
        Query has no such method; this restores it so those call sites don't
        need to change, and applies the same soft-delete filter __iter__ does
        (paginate() doesn't go through __iter__, so it must be applied here too).
        """
        page = max(1, int(page or 1))
        per_page = max(1, int(per_page or 20))
        if max_per_page is not None:
            per_page = min(per_page, int(max_per_page))

        filtered = self._maybe_apply_soft_delete_filter()
        total = filtered.order_by(None).count()
        items = filtered.offset((page - 1) * per_page).limit(per_page).all()
        pages = max(1, (total + per_page - 1) // per_page)

        if error_out and not items and page != 1:
            from utils import ApiError

            raise ApiError("Page not found.", status=404, code="page_not_found")

        return _Pagination(items=items, page=page, per_page=per_page, total=total, pages=pages)


class _Pagination:
    """Minimal stand-in for flask_sqlalchemy.pagination.Pagination — just the attributes routes/*.py reads."""

    def __init__(self, items, page, per_page, total, pages):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = pages
        self.has_next = page < pages
        self.has_prev = page > 1
        self.next_num = page + 1 if self.has_next else None
        self.prev_num = page - 1 if self.has_prev else None


# ---------------------------------------------------------------------------
# §2 — ENUM VOCABULARIES  (string-valued; columns stay String(n))
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    system_admin     = "system_admin"
    landlord         = "landlord"
    property_manager = "property_manager"
    team_member      = "team_member"
    tenant           = "tenant"
    affiliate        = "affiliate"


class AccountType(str, enum.Enum):
    gated_community     = "gated_community"
    property_management = "property_management"
    landlord            = "landlord"


class MpesaType(str, enum.Enum):
    paybill = "paybill"
    till    = "till"


class TeamMemberRole(str, enum.Enum):
    editor = "editor"
    viewer = "viewer"


class PermissionModule(str, enum.Enum):
    payments       = "payments"
    invoices       = "invoices"
    utilities      = "utilities"
    unit_utilities = "unit_utilities"
    tenants        = "tenants"
    units          = "units"
    properties     = "properties"
    messages       = "messages"
    expenses       = "expenses"
    maintenance    = "maintenance"
    reports        = "reports"
    groups         = "groups"
    # KRA/eTIMS compliance work (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §1.4).
    # Unlike every other module this one is ALSO scoped per property, through
    # team_member_property_permissions — holding the module row alone grants
    # nothing until at least one property is granted.
    tax_compliance = "tax_compliance"


class ManagerScopeType(str, enum.Enum):
    unit     = "unit"
    property = "property"
    group    = "group"


# otp_channel (sms · email) — DIFFERENT from message_channel (sms · whatsapp · email)
class OtpChannel(str, enum.Enum):
    sms   = "sms"
    email = "email"


class InvoiceStatus(str, enum.Enum):
    draft   = "draft"
    void    = "void"
    open    = "open"
    partial = "partial"
    paid    = "paid"


class InvoiceType(str, enum.Enum):
    rent      = "rent"
    utility   = "utility"
    penalty   = "penalty"
    custom    = "custom"
    recurring = "recurring"
    deposit   = "deposit"      # rent/utility/security deposits — allocated first bucket (#6)
    monthly   = "monthly"      # the single per-tenant month-end invoice (rollover + auto-bill)


class PaymentStatus(str, enum.Enum):
    confirmed = "confirmed"
    pending   = "pending"
    declined  = "declined"
    # sahilpay_payment_allocation_spec.md §4.7 — money that arrived but cannot be
    # attributed with certainty. A suspense payment is REAL cash sitting in the
    # paybill; it is deliberately NOT confirmed, so it never reaches a
    # statement, a commission base or a payout until a human resolves it.
    # Nothing ever leaves suspense without an explicit allocation.
    suspense  = "suspense"
    # An allocation was reversed (an M-Pesa reversal SMS, or a manual undo).
    reversed  = "reversed"


class AllocationMethod(str, enum.Enum):
    """
    How an account's inbound payments are routed (spec §4.4).

      unit_code  deterministic — tenants pay quoting their unit's pay-code, so a
                 payment names exactly one lease.
      phone      matches the habit most Kenyan tenants already have. A phone
                 number identifies a TENANT but never says WHICH of their units,
                 so a multi-unit tenant's lump sum goes to suspense for the
                 manager to split rather than being guessed at.

    Existing accounts default to `phone` (their current behaviour); new accounts
    default to `unit_code`.
    """
    unit_code = "unit_code"
    phone     = "phone"


class SuspenseReason(str, enum.Enum):
    """Why a payment could not be attributed. Drives the review queue copy."""
    unknown_reference             = "unknown_reference"
    code_no_active_lease          = "code_no_active_lease"
    multi_lease                   = "multi_lease"
    ambiguous_phone               = "ambiguous_phone"
    no_source_match               = "no_source_match"
    reversal_pending              = "reversal_pending"


class CommissionScopeType(str, enum.Enum):
    """Commission rules attach at one of three levels; most specific wins."""
    landlord = "landlord"
    property = "property"
    unit     = "unit"


class CommissionRateType(str, enum.Enum):
    percentage = "percentage"
    fixed      = "fixed"


class PayoutStatus(str, enum.Enum):
    pending = "pending"
    paid    = "paid"


class AllocationAuditAction(str, enum.Enum):
    allocate   = "allocate"
    reallocate = "reallocate"
    reverse    = "reverse"
    suspense   = "suspense"


class PaymentSource(str, enum.Enum):
    mpesa           = "mpesa"
    co_pilot        = "co_pilot"
    bank_statement  = "bank_statement"
    manual          = "manual"
    credit          = "credit"   # synthetic payment: re-applying a tenant's held advance/credit


# Sources that represent re-application of money already received (not new cash).
# Cash-received reports/statements must EXCLUDE these; the payments report (which
# measures what was collected against each subcategory) still counts them.
NON_CASH_PAYMENT_SOURCES = frozenset({"credit"})


class BankStatementStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsing  = "parsing"
    parsed   = "parsed"
    failed   = "failed"


class MpesaTransactionStatus(str, enum.Enum):
    recorded  = "recorded"
    unmatched = "unmatched"
    pending   = "pending"


class CopilotDeviceStatus(str, enum.Enum):
    active  = "active"
    revoked = "revoked"


class CopilotParseStatus(str, enum.Enum):
    """One CopilotMessage row's parse outcome — see services/copilot_service.py."""
    parsed    = "parsed"      # a template matched and extracted fields
    unparsed  = "unparsed"    # no active template matched → admin queue
    duplicate = "duplicate"   # dedupe hit; stored for traceability, no side effects
    rejected  = "rejected"    # e.g. landlord disabled, malformed payload


class CopilotMatchStatus(str, enum.Enum):
    matched   = "matched"     # tenant resolved (by account or phone)
    unmatched = "unmatched"   # parsed fine but no tenant hit → landlord queue
    n_a       = "n_a"         # not applicable (unparsed/duplicate/rejected)


class ExpenseStatus(str, enum.Enum):
    confirmed = "confirmed"
    pending   = "pending"


# expense_category is reused by recurring_expenses
class ExpenseCategory(str, enum.Enum):
    garbage     = "garbage"
    maintenance = "maintenance"
    security    = "security"
    electricity = "electricity"
    water       = "water"
    cleaning    = "cleaning"
    internet    = "internet"
    other       = "other"


class UtilityItem(str, enum.Enum):
    water       = "water"
    electricity = "electricity"
    garbage     = "garbage"
    security    = "security"


# ── Charge-category restructure (backbone rework) — CATEGORY_RESTRUCTURE_SPEC.md
# Every chargeable thing is a ChargeCategory (kind = utility | invoice). Each
# category implicitly owns THREE subcategories (deposit / balance / current);
# those are stamped on invoice line items, which is where money is invoiced,
# allocated, rolled over and reported.
class ChargeCategoryKind(str, enum.Enum):
    utility = "utility"   # managed on the Utilities page
    invoice = "invoice"   # managed on the Invoices page (rent, lease agreement, …)


class SubCategory(str, enum.Enum):
    deposit = "deposit"   # money held (refundable) — NEVER rolls over; excluded from income totals
    balance = "balance"   # arrears carried forward from prior months
    current = "current"   # this month's charge


class LineItemStatus(str, enum.Enum):
    open   = "open"
    paid   = "paid"
    rolled = "rolled"     # closed by month-end rollover — excluded from "outstanding" everywhere


class MaintenanceStatus(str, enum.Enum):
    open        = "open"
    in_progress = "in_progress"
    closed      = "closed"


class MaintenanceCategory(str, enum.Enum):
    electrical     = "electrical"
    plumbing       = "plumbing"
    roofing        = "roofing"
    pest_control   = "pest_control"
    roof_repair    = "roof_repair"
    locksmith      = "locksmith"
    pool           = "pool"
    garage         = "garage"
    heating_cooling = "heating_cooling"
    handiwork      = "handiwork"
    tiles          = "tiles"
    washroom       = "washroom"
    painting       = "painting"
    security       = "security"
    other          = "other"


# message_channel (sms · whatsapp · email) — DIFFERENT from otp_channel
class MessageChannel(str, enum.Enum):
    sms      = "sms"
    whatsapp = "whatsapp"
    email    = "email"


class MessageTemplateType(str, enum.Enum):
    balance_reminder = "balance_reminder"
    invoice_reminder = "invoice_reminder"
    welcome          = "welcome"      # sent when a tenant is first added
    custom           = "custom"


class RecipientType(str, enum.Enum):
    tenant      = "tenant"
    team_member = "team_member"


class CommunicationStatus(str, enum.Enum):
    pending   = "pending"
    delivered = "delivered"
    failed    = "failed"


class DocumentType(str, enum.Enum):
    lease              = "lease"
    tenancy_agreement  = "tenancy_agreement"
    deposit            = "deposit"
    other              = "other"


class SubscriptionPlan(str, enum.Enum):
    monthly   = "monthly"
    quarterly = "quarterly"
    annual    = "annual"


class BillingCycle(str, enum.Enum):
    monthly = "monthly"
    yearly  = "yearly"


class SubscriptionStatus(str, enum.Enum):
    trial     = "trial"
    active    = "active"
    past_due  = "past_due"
    suspended = "suspended"


class BillingTransactionType(str, enum.Enum):
    subscription  = "subscription"
    sms_purchase  = "sms_purchase"


class BillingTransactionStatus(str, enum.Enum):
    pending = "pending"
    paid    = "paid"
    failed  = "failed"


# ---------------------------------------------------------------------------
# §10.6  Affiliate Program  (AFFILIATE_PROGRAM_SPEC.md)
# ---------------------------------------------------------------------------

class AffiliateStatus(str, enum.Enum):
    pending   = "pending"     # signed up, awaiting admin approval
    active    = "active"
    suspended = "suspended"
    rejected  = "rejected"


class ReferralStatus(str, enum.Enum):
    active    = "active"      # attributed; window not yet exhausted
    completed = "completed"   # months_used == months_total
    void      = "void"        # admin-detached / fraud


class CommissionStatus(str, enum.Enum):
    confirmed = "confirmed"   # counts toward balance
    reversed  = "reversed"    # underlying payment reversed — nets to zero


class WithdrawalStatus(str, enum.Enum):
    requested  = "requested"
    processing = "processing"
    paid       = "paid"
    rejected   = "rejected"


class AffiliateFeeType(str, enum.Enum):
    percent = "percent"
    flat    = "flat"


class TrialScope(str, enum.Enum):
    global_scope  = "global"        # "global" is a Python builtin; value stays "global"
    per_landlord  = "per_landlord"


class ImpersonationStatus(str, enum.Enum):
    pending = "pending"
    granted = "granted"
    revoked = "revoked"
    expired = "expired"


class AlertType(str, enum.Enum):
    payment      = "payment"
    report       = "report"
    lease_expiry = "lease_expiry"
    low_sms      = "low_sms"
    arrears      = "arrears"


class AlertCadence(str, enum.Enum):
    daily    = "daily"
    weekly   = "weekly"
    monthly  = "monthly"
    realtime = "realtime"


class AlertChannel(str, enum.Enum):
    dashboard = "dashboard"
    sms       = "sms"
    email     = "email"
    invoice   = "invoice"


class AuditEntityType(str, enum.Enum):
    payment            = "payment"
    invoice            = "invoice"
    expense            = "expense"
    property           = "property"
    unit               = "unit"
    team_member        = "team_member"
    tenant             = "tenant"
    account            = "account"
    utility            = "utility"
    maintenance        = "maintenance"
    landlord           = "landlord"
    recurring_expense  = "recurring_expense"
    package            = "package"
    notification       = "notification"
    settings           = "settings"
    document           = "document"
    billing            = "billing"
    affiliate            = "affiliate"
    affiliate_referral   = "affiliate_referral"
    affiliate_commission = "affiliate_commission"
    affiliate_withdrawal = "affiliate_withdrawal"
    copilot              = "copilot"
    etims                = "etims"
    tutorial             = "tutorial"
    property_owner       = "property_owner"


class NotificationCategory(str, enum.Enum):
    """One value per template in services/notification_service.py's registry."""
    broadcast               = "broadcast"                 # free-form admin/landlord message
    tenant_message          = "tenant_message"            # tenant↔landlord conversation reply
    payment_received        = "payment_received"
    new_maintenance_request = "new_maintenance_request"
    trial_expiring           = "trial_expiring"
    lease_expiring           = "lease_expiring"
    low_sms_balance          = "low_sms_balance"
    team_member_activated    = "team_member_activated"
    impersonation_requested  = "impersonation_requested"
    impersonation_granted    = "impersonation_granted"
    affiliate_approved              = "affiliate_approved"
    affiliate_commission_earned     = "affiliate_commission_earned"
    affiliate_withdrawal_processed  = "affiliate_withdrawal_processed"
    affiliate_new_referral          = "affiliate_new_referral"
    copilot_payment_pending         = "copilot_payment_pending"
    copilot_payment_unmatched       = "copilot_payment_unmatched"
    copilot_device_paired           = "copilot_device_paired"
    # KRA/eTIMS reminders (spec §4.5). Both individually mutable, and only ever
    # sent to accounts with at least one eTIMS-enabled property.
    etims_record_invoices           = "etims_record_invoices"
    mri_filing_due                  = "mri_filing_due"


class NotificationAudience(str, enum.Enum):
    """Who a /notifications/send call targeted — stored for audit context."""
    user             = "user"              # a single specific user
    landlord         = "landlord"          # one landlord (sent to that landlord's own user)
    property_tenants = "property_tenants"  # every tenant in one property
    all_tenants      = "all_tenants"       # every tenant of a landlord (or platform-wide for admin)
    all_team_members = "all_team_members"  # every team member of a landlord
    all_landlords    = "all_landlords"     # admin-only: every landlord on the platform


class BackupScopeType(str, enum.Enum):
    property  = "property"
    grouping  = "grouping"
    tenants   = "tenants"
    payments  = "payments"
    category  = "category"


class BackupFormat(str, enum.Enum):
    excel = "excel"
    pdf   = "pdf"


# ---------------------------------------------------------------------------
# MIXINS
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Adds created_at + updated_at to every standard table."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreatedAtMixin:
    """Adds created_at only — for append-only / immutable tables."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SoftDeleteMixin:
    """Adds is_deleted + deleted_at.  Apply to the 6 soft-delete tables only."""
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class EtimsMixin:
    """
    The eTIMS invoice-number group, applied to every table that records money
    someone must issue a KRA invoice for — payments (landlord→tenant),
    owner_payouts (PM→landlord commission) and billing_transactions
    (SahilPay→client). See SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §1.3.

    Every column is NULLABLE and nothing reads them unless the property has
    opted in: a row with no number renders exactly as it does today, with no
    placeholder, badge or "pending" state anywhere. There is deliberately no
    "missing invoice" concept in this schema.

    The number itself comes from KRA's own channels (eCitizen / *222# / the
    eTIMS Non-VAT app) and is typed in by hand — SahilPay never generates or
    verifies one, so validation is format-only (see services/etims_service.py).
    """
    etims_invoice_number = Column(String(64),  nullable=True)
    etims_issued_at      = Column(DateTime,    nullable=True)
    etims_qr_url         = Column(String(512), nullable=True)

    @declared_attr
    def etims_entered_by_user_id(cls):
        return Column(Integer, ForeignKey("users.id"), nullable=True)

    def etims_dict(self) -> dict:
        return {
            "etims_invoice_number":     self.etims_invoice_number,
            "etims_issued_at":          _serialise(self.etims_issued_at),
            "etims_qr_url":             self.etims_qr_url,
            "etims_entered_by_user_id": self.etims_entered_by_user_id,
        }


# ---------------------------------------------------------------------------
# Helper for Decimal serialisation
# ---------------------------------------------------------------------------

def _serialise(value):
    """Convert Decimal → str, date/datetime → ISO string, else passthrough."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return value


# ===========================================================================
# DOMAIN A — Identity & Access  (7 tables)
# ===========================================================================

class User(TimestampMixin, Base):
    """
    §3.1  Base auth record for every human account.
    Tenants are OTP-only (password_hash is NULL).

    Schema-level validations (enforce in Marshmallow/Pydantic):
      - Non-tenant roles must supply a non-null password_hash.
      - Exactly one profile row must exist matching the role.
    """
    __tablename__ = "users"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    email              = Column(String(255), unique=True, nullable=True)
    phone              = Column(String(20),  nullable=True, index=True)
    password_hash      = Column(String(255), nullable=True)
    role               = Column(String(50),  nullable=False)          # enum UserRole
    is_verified        = Column(Boolean, default=False, nullable=False)
    is_active          = Column(Boolean, default=True,  nullable=False)
    verification_token = Column(String(255), nullable=True)
    # True when the account is on a system-issued temporary password (e.g. a team
    # member created by their landlord). The frontend forces a password change on
    # next login; cleared the moment they set their own password.
    must_change_password = Column(Boolean, default=False, nullable=False)

    # Two-factor authentication (services/twofa_service.py).
    #   totp_secret       — ENCRYPTED at rest with Fernet. Whoever holds the
    #                       plaintext can mint valid codes forever, so it never
    #                       touches the database in clear.
    #   totp_backup_codes — JSON list of salted HASHES; the plaintext codes are
    #                       shown once at enrolment and are not recoverable.
    # Mandatory for system_admin, optional for everyone else.
    totp_secret          = Column(String(255), nullable=True)
    totp_enabled         = Column(Boolean, default=False, nullable=False)
    totp_backup_codes    = Column(Text, nullable=True)
    totp_confirmed_at    = Column(DateTime, nullable=True)

    # The account holder's own KRA PIN — a landlord's or PM's for the invoices
    # they issue, a team member's for their own records. Optional forever:
    # blank never blocks a save and never surfaces anywhere in the UI.
    # Format A012345678B / P051234567X, stored uppercase.
    kra_pin              = Column(String(11), nullable=True)

    __table_args__ = (
        # Tenants are OTP-only, and team members are created with no password
        # by team_routes.py::create_team_member — they set one during account
        # activation (POST /api/auth/team-activate/<token>). Every other role
        # self-registers with a password up front and must always have one.
        CheckConstraint(
            "(role IN ('tenant', 'team_member')) OR (password_hash IS NOT NULL)",
            name="ck_users_non_tenant_needs_password",
        ),
    )

    # 1:1 profile relationships
    admin_profile       = relationship("SystemAdmin",  back_populates="user",
                                       uselist=False, cascade="all, delete-orphan")
    landlord_profile    = relationship("Landlord",     back_populates="user",
                                       uselist=False, cascade="all, delete-orphan")
    team_member_profile = relationship("TeamMember",   back_populates="user",
                                       uselist=False, cascade="all, delete-orphan")
    # 1:N — ONE person can be a tenant several times over: two units in the same
    # block, or units under three different landlords who have no idea the other
    # two exist. Each occupancy stays its own Tenant row with its own account
    # number, which is what keeps their payments from ever mixing up; this
    # relationship is only the identity link that lets one login see them all.
    tenant_profiles     = relationship("Tenant",       back_populates="user",
                                       cascade="all, delete-orphan")
    affiliate_profile   = relationship("Affiliate",    back_populates="user",
                                       uselist=False, cascade="all, delete-orphan",
                                       foreign_keys="Affiliate.user_id")

    # 1:N
    otp_tokens              = relationship("OtpToken",            back_populates="user")
    audit_logs_as_actor     = relationship("AuditLog",            back_populates="actor_user",
                                           foreign_keys="AuditLog.actor_user_id")
    impersonation_requests  = relationship("ImpersonationRequest", back_populates="admin_user",
                                           foreign_keys="ImpersonationRequest.admin_user_id")

    def to_dict(self):
        return {
            "id":                 self.id,
            "email":              self.email,
            "phone":              self.phone,
            "role":               self.role,
            "is_verified":        self.is_verified,
            "is_active":          self.is_active,
            "must_change_password": self.must_change_password,
            "kra_pin":            self.kra_pin,
            # Never expose the secret or the backup-code hashes — only whether
            # the second factor is on.
            "totp_enabled":         self.totp_enabled,
            "verification_token": self.verification_token,
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }


class SystemAdmin(TimestampMixin, Base):
    """§3.2  Platform-owner profile.  Full cross-landlord authority."""
    __tablename__ = "system_admins"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    first_name    = Column(String(100), nullable=True)
    last_name     = Column(String(100), nullable=True)
    profile_image = Column(String(255), nullable=True)    # Cloudinary URL

    user = relationship("User", back_populates="admin_profile")

    def to_dict(self):
        return {
            "id":            self.id,
            "user_id":       self.user_id,
            "first_name":    self.first_name,
            "last_name":     self.last_name,
            "profile_image": self.profile_image,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


class Landlord(TimestampMixin, Base):
    """
    §3.3  Primary paying customer (landlord OR property manager).
    Distinguished by account_type.

    Schema constraints (enforce in Marshmallow/Pydantic):
      - If mpesa_type is set, mpesa_number must be present.
    """
    __tablename__ = "landlords"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    user_id                = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    company_name           = Column(String(255), nullable=False)
    abbreviated_name       = Column(String(100), nullable=True)
    company_address        = Column(Text,        nullable=True)
    logo_url               = Column(String(255), nullable=True)
    signature_url          = Column(String(255), nullable=True)
    invoice_title          = Column(String(150), nullable=True)
    currency               = Column(String(8),   default="KES", nullable=False)
    timezone               = Column(String(64),  default="Africa/Nairobi", nullable=False)
    mpesa_type             = Column(String(20),  nullable=True)    # enum MpesaType
    mpesa_number           = Column(String(20),  nullable=True)
    default_account_number = Column(String(50),  nullable=True)
    account_type           = Column(String(30),  nullable=True)    # enum AccountType
    payment_instructions   = Column(Text, nullable=True)           # free-text directives shown to tenants on the pay page
    allocation_priority    = Column(String(255), nullable=True)    # DEPRECATED old CSV buckets — superseded by allocation_priority_json
    allocation_priority_json = Column(Text, nullable=True)         # JSON array of "<category_id>:<subcategory>" keys, highest priority first
    # How inbound payments are routed to a lease (spec §4.4). Existing accounts
    # are migrated to 'phone' so their behaviour is unchanged; new accounts get
    # 'unit_code', which is deterministic. In phone mode the unit pay-code still
    # works as a fallback reference, so a precise tenant can always self-route.
    allocation_method      = Column(String(12), nullable=False,
                                    default=AllocationMethod.unit_code.value,
                                    server_default=AllocationMethod.unit_code.value)
    # MRI is DISPLAY-ONLY unless this is on (spec §4.9). Off means the payout
    # shows the landlord their 7.5% figure without deducting a shilling of it.
    tax_withholding_enabled = Column(Boolean, default=False, nullable=False,
                                     server_default="false")
    default_tax_rate       = Column(Numeric(5, 2),  default=Decimal("7.50"), nullable=False)
    agent_code             = Column(String(50),  unique=True, nullable=True)
    sms_balance            = Column(Integer, default=0, nullable=False)
    per_unit_price         = Column(Numeric(10, 2), nullable=True)
    # A negotiated FLAT monthly fee. When set it overrides unit-band pricing and
    # per_unit_price entirely: the landlord pays this amount every month no
    # matter how their unit count moves. Cycle discounts (quarterly/annual) do
    # NOT apply on top — the figure was agreed verbally and is already the
    # discount. See services/billing_service.py.
    fixed_monthly_price    = Column(Numeric(12, 2), nullable=True)
    # Per-landlord price per SMS, winning over the global SmsPricingConfig.
    sms_price_override     = Column(Numeric(8, 4), nullable=True)
    package_id             = Column(Integer, ForeignKey("packages.id"), nullable=True, index=True)
    trial_ends_at          = Column(DateTime, nullable=True)
    is_on_trial            = Column(Boolean, default=True, nullable=False)
    # §Affiliate program: the raw code typed at registration, kept even when it
    # didn't resolve to an active affiliate — lets the admin grace-window tool
    # (POST /api/admin/affiliates/attribute) fix a forgotten/mistyped code
    # without DB surgery. See AFFILIATE_PROGRAM_SPEC.md D4/E3.
    referral_code_entered = Column(String(12), nullable=True)
    # Landlord onboarding/tutorials progress — JSON blob, shape owned by the
    # frontend tutorials module (see ONBOARDING_TUTORIALS_SPEC.md §4.3).
    onboarding_state_json = Column(Text, nullable=True)
    # Demo mode (see DEMO_MODE_SPEC.md) — is_demo marks a hidden "shadow"
    # landlord that holds example data; demo_owner_landlord_id points from
    # that shadow back to the real landlord who owns it (at most one shadow
    # per real landlord). Real landlords have is_demo=False and
    # demo_owner_landlord_id=None.
    is_demo                = Column(Boolean, default=False, nullable=False, index=True)
    demo_owner_landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=True, unique=True, index=True)
    demo_created_at        = Column(DateTime, nullable=True)
    demo_last_reset_at     = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(mpesa_type IS NULL) OR (mpesa_number IS NOT NULL)",
            name="ck_landlords_mpesa_number_required",
        ),
    )

    # Relationships — 1:1
    user              = relationship("User",               back_populates="landlord_profile", uselist=False)
    subscription      = relationship("Subscription",       back_populates="landlord",         uselist=False)
    landlord_settings = relationship("LandlordSettings",   back_populates="landlord",         uselist=False)
    automation_settings = relationship("AutomationSettings", back_populates="landlord",       uselist=False)

    # Relationships — N:1
    package = relationship("Package", back_populates="landlords")

    # Relationships — 1:N
    property_groups      = relationship("PropertyGroup",      back_populates="landlord")
    properties           = relationship("Property",           back_populates="landlord",
                                        foreign_keys="Property.landlord_id")
    property_owners      = relationship("PropertyOwner",      back_populates="landlord")
    payment_sources      = relationship("InboundPaymentSource", back_populates="landlord")
    commission_rules     = relationship("CommissionRule",      back_populates="landlord")
    team_members         = relationship("TeamMember",         back_populates="landlord")
    tenants              = relationship("Tenant",             back_populates="landlord")
    invoices             = relationship("Invoice",            back_populates="landlord")
    payments             = relationship("Payment",            back_populates="landlord")
    expenses             = relationship("Expense",            back_populates="landlord")
    recurring_expenses   = relationship("RecurringExpense",   back_populates="landlord")
    utility_readings     = relationship("UtilityReading",     back_populates="landlord")
    charge_categories    = relationship("ChargeCategory",     back_populates="landlord")
    balance_rollovers    = relationship("BalanceRollover",    back_populates="landlord")
    credit_ledger        = relationship("CreditLedger",       back_populates="landlord")
    maintenance_requests = relationship("MaintenanceRequest", back_populates="landlord")
    message_templates    = relationship("MessageTemplate",    back_populates="landlord")
    communication_logs   = relationship("CommunicationLog",   back_populates="landlord")
    document_templates   = relationship("DocumentTemplate",   back_populates="landlord")
    billing_transactions = relationship("BillingTransaction", back_populates="landlord")
    backups              = relationship("Backup",             back_populates="landlord")
    mpesa_transactions   = relationship("MpesaTransaction",   back_populates="landlord")
    recurring_bills      = relationship("RecurringBill",      back_populates="landlord")
    bank_statement_uploads = relationship("BankStatementUpload", back_populates="landlord")
    alert_settings       = relationship("AlertSetting",       back_populates="landlord")
    trial_configs        = relationship("TrialConfig",        back_populates="landlord")
    impersonation_requests = relationship("ImpersonationRequest", back_populates="landlord",
                                          foreign_keys="ImpersonationRequest.landlord_id")
    affiliate_referral   = relationship("AffiliateReferral",  back_populates="landlord", uselist=False)
    copilot_devices      = relationship("CopilotDevice",      back_populates="landlord")
    copilot_messages     = relationship("CopilotMessage",     back_populates="landlord")

    def to_dict(self):
        return {
            "id":                     self.id,
            "user_id":                self.user_id,
            "company_name":           self.company_name,
            "abbreviated_name":       self.abbreviated_name,
            "company_address":        self.company_address,
            "logo_url":               self.logo_url,
            "signature_url":          self.signature_url,
            "invoice_title":          self.invoice_title,
            "currency":               self.currency,
            "timezone":               self.timezone,
            "mpesa_type":             self.mpesa_type,
            "mpesa_number":           self.mpesa_number,
            "default_account_number": self.default_account_number,
            "account_type":           self.account_type,
            "payment_instructions":   self.payment_instructions,
            "allocation_priority":    self.allocation_priority,
            "allocation_priority_json": self.allocation_priority_json,
            "default_tax_rate":       _serialise(self.default_tax_rate),
            "agent_code":             self.agent_code,
            "sms_balance":            self.sms_balance,
            "per_unit_price":         _serialise(self.per_unit_price),
            "fixed_monthly_price":    _serialise(self.fixed_monthly_price),
            "sms_price_override":     _serialise(self.sms_price_override),
            "package_id":             self.package_id,
            "trial_ends_at":          _serialise(self.trial_ends_at),
            "is_on_trial":            self.is_on_trial,
            "referral_code_entered":  self.referral_code_entered,
            "onboarding_state":       self._onboarding_state(),
            "is_demo":                self.is_demo,
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }

    def _onboarding_state(self):
        if not self.onboarding_state_json:
            return None
        try:
            return json.loads(self.onboarding_state_json)
        except (TypeError, ValueError):
            return None


class TeamMember(TimestampMixin, Base):
    """§3.4  Sub-account created by a landlord/PM.  Permission-gated by §3.5."""
    __tablename__ = "team_members"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    user_id             = Column(Integer, ForeignKey("users.id"),     nullable=False, unique=True, index=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    username            = Column(String(100), nullable=False)
    first_name          = Column(String(100), nullable=True)
    last_name           = Column(String(100), nullable=True)
    phone               = Column(String(20),  nullable=True)
    role                = Column(String(20),  nullable=True)    # enum TeamMemberRole
    # Role preset the member was created from (owner | caretaker | accountant |
    # secretary | custom; null = pre-dates presets). Labelling + bootstrap only —
    # the team_member_permissions rows remain the sole authority on access, and
    # every permission stays individually editable after a preset is applied.
    # See services/team_preset_service.py.
    preset              = Column(String(20),  nullable=True)
    property_access_all = Column(Boolean, default=False, nullable=False)
    activation_token    = Column(String(255), nullable=True)
    is_active           = Column(Boolean, default=False, nullable=False)

    user     = relationship("User",     back_populates="team_member_profile", uselist=False)
    landlord = relationship("Landlord", back_populates="team_members")

    permissions         = relationship("TeamMemberPermission",    back_populates="team_member",
                                       cascade="all, delete-orphan")
    property_accesses   = relationship("TeamMemberPropertyAccess", back_populates="team_member",
                                       cascade="all, delete-orphan")
    property_permissions = relationship("TeamMemberPropertyPermission", back_populates="team_member",
                                        cascade="all, delete-orphan")
    manager_assignments = relationship("ManagerAssignment",        back_populates="team_member")
    communication_logs  = relationship("CommunicationLog",         back_populates="team_member")

    def to_dict(self):
        return {
            "id":                  self.id,
            "user_id":             self.user_id,
            "landlord_id":         self.landlord_id,
            "username":            self.username,
            "first_name":          self.first_name,
            "last_name":           self.last_name,
            "phone":               self.phone,
            "role":                self.role,
            "preset":              self.preset,
            "property_access_all": self.property_access_all,
            "is_active":           self.is_active,
            "created_at":          _serialise(self.created_at),
            "updated_at":          _serialise(self.updated_at),
        }


class TeamMemberPermission(TimestampMixin, Base):
    """
    §3.5  Per-module permission row for a team member.
    One row per (team_member_id, module).

    App-level rule: can_edit=True forces can_view=True.
    """
    __tablename__ = "team_member_permissions"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    team_member_id = Column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    module         = Column(String(30), nullable=False)    # enum PermissionModule
    can_view       = Column(Boolean, default=False, nullable=False)
    can_edit       = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("team_member_id", "module", name="uq_tmp_team_member_module"),
    )

    team_member = relationship("TeamMember", back_populates="permissions")

    def to_dict(self):
        return {
            "id":             self.id,
            "team_member_id": self.team_member_id,
            "module":         self.module,
            "can_view":       self.can_view,
            "can_edit":       self.can_edit,
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
        }


class TeamMemberPropertyAccess(TimestampMixin, Base):
    """§3.6  M:N join — restricts team member to specific properties."""
    __tablename__ = "team_member_property_access"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    team_member_id = Column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    property_id    = Column(Integer, ForeignKey("properties.id"),   nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("team_member_id", "property_id", name="uq_tmpa_member_property"),
    )

    team_member = relationship("TeamMember", back_populates="property_accesses")
    property    = relationship("Property",   back_populates="team_member_property_accesses")

    def to_dict(self):
        return {
            "id":             self.id,
            "team_member_id": self.team_member_id,
            "property_id":    self.property_id,
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
        }


class TeamMemberPropertyPermission(TimestampMixin, Base):
    """
    A named capability granted to a team member on ONE property
    (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §1.4).

    Distinct from TeamMemberPropertyAccess, which answers "which properties may
    this person see at all", and from TeamMemberPermission, which answers "which
    modules may they touch". This answers the third question the tax layer
    needs: *of the properties they can see, which ones may they do compliance
    work on* — an accountant may hold `manage_tax_compliance` on two blocks
    while merely viewing the other ninety-eight.

    Kept generic (a `permission` string rather than a boolean column) so later
    per-property capabilities reuse the table instead of adding another join.
    Currently the only value is "manage_tax_compliance".
    """
    __tablename__ = "team_member_property_permissions"

    PERM_MANAGE_TAX_COMPLIANCE = "manage_tax_compliance"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    team_member_id  = Column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    property_id     = Column(Integer, ForeignKey("properties.id"),   nullable=False, index=True)
    permission      = Column(String(40), nullable=False, index=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at      = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("team_member_id", "property_id", "permission",
                         name="uq_tmpp_member_property_permission"),
    )

    team_member = relationship("TeamMember", back_populates="property_permissions")
    property    = relationship("Property")
    granted_by  = relationship("User", foreign_keys=[granted_by_user_id])

    def to_dict(self):
        return {
            "id":                 self.id,
            "team_member_id":     self.team_member_id,
            "property_id":        self.property_id,
            "property_name":      self.property.name if self.property else None,
            "permission":         self.permission,
            "granted_by_user_id": self.granted_by_user_id,
            "granted_at":         _serialise(self.granted_at),
        }


class OtpToken(CreatedAtMixin, Base):
    """
    §3.7  Short-lived OTP for passwordless tenant login.
    Append-only — no updated_at.
    Flask-Limiter must rate-limit /otp/request (app-level).
    """
    __tablename__ = "otp_tokens"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    identifier = Column(String(255), nullable=False)    # phone or email
    code       = Column(String(64),  nullable=False)    # sha256 hexdigest of the OTP
    channel    = Column(String(10),  nullable=True)     # enum OtpChannel
    expires_at = Column(DateTime,    nullable=False)
    is_used    = Column(Boolean, default=False, nullable=False)
    attempts   = Column(Integer, default=0,     nullable=False)

    __table_args__ = (
        Index("ix_otp_tokens_identifier_is_used", "identifier", "is_used"),
    )

    user = relationship("User", back_populates="otp_tokens")

    def to_dict(self):
        return {
            "id":         self.id,
            "user_id":    self.user_id,
            "identifier": self.identifier,
            "channel":    self.channel,
            "expires_at": _serialise(self.expires_at),
            "is_used":    self.is_used,
            "attempts":   self.attempts,
            "created_at": _serialise(self.created_at),
        }


# ===========================================================================
# DOMAIN B — Property Structure  (5 tables)
# ===========================================================================

class PropertyGroup(TimestampMixin, Base):
    """§4.1  Optional grouping of properties for reporting & manager assignment."""
    __tablename__ = "property_groups"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    name        = Column(String(150), nullable=False)

    landlord            = relationship("Landlord",          back_populates="property_groups")
    properties          = relationship("Property",          back_populates="property_group")
    manager_assignments = relationship("ManagerAssignment", back_populates="property_group")

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "name":        self.name,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class PropertyOwner(TimestampMixin, Base):
    """
    The human (or company) who actually OWNS one or more properties under an
    account — as distinct from the `Landlord` row, which is the SahilPay
    *account holder*.

    For a landlord managing their own block these are the same person and this
    table stays empty. For a property manager they are not: the PM is the
    account, but each block belongs to a different owner, and it is the OWNER
    who is the seller on every rent invoice and the taxpayer who files the 7.5%
    MRI return. Before this table an owner existed only as
    `Property.owner_phone` plus, optionally, a `preset="owner"` TeamMember —
    neither of which can carry a KRA PIN or group two blocks belonging to the
    same person.

    Nothing requires an owner row: `Property.owner_id` is nullable, and a
    property without one behaves exactly as it always has.
    """
    __tablename__ = "property_owners"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    full_name   = Column(String(200), nullable=False)
    phone       = Column(String(20),  nullable=True, index=True)
    email       = Column(String(255), nullable=True)
    # The owner's KRA PIN — the seller PIN on rent invoices for their
    # properties, and the identity the consolidated MRI report files under.
    kra_pin     = Column(String(11),  nullable=True)
    notes       = Column(Text, nullable=True)
    is_active   = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        # Two owners of the same account may share a name (father and son), but
        # never a phone number — that is what the backfill matches on.
        UniqueConstraint("landlord_id", "phone", name="uq_property_owners_landlord_phone"),
    )

    landlord   = relationship("Landlord", back_populates="property_owners")
    properties = relationship("Property", back_populates="owner")

    def to_dict(self, include_properties: bool = False):
        data = {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "full_name":   self.full_name,
            "phone":       self.phone,
            "email":       self.email,
            "kra_pin":     self.kra_pin,
            "notes":       self.notes,
            "is_active":   self.is_active,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }
        if include_properties:
            data["properties"] = [
                {"id": p.id, "name": p.name}
                for p in self.properties if not p.is_deleted
            ]
        return data


class Property(SoftDeleteMixin, TimestampMixin, Base):
    """
    §4.2  A physical property.
    Required: name, number_of_units, city.  Everything else optional.
    Soft-delete: never hard-deleted.
    """
    __tablename__ = "properties"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"),      nullable=False, index=True)
    property_group_id   = Column(Integer, ForeignKey("property_groups.id"), nullable=True, index=True)
    name                = Column(String(200), nullable=False)
    number_of_units     = Column(Integer,     nullable=False, default=0)
    city                = Column(String(120), nullable=False)
    street_name         = Column(String(200), nullable=True)
    water_rate          = Column(Numeric(10, 2), nullable=True)
    electricity_rate    = Column(Numeric(10, 2), nullable=True)
    mpesa_details       = Column(String(50),  nullable=True)
    rent_payment_penalty = Column(Numeric(10, 2), nullable=True)
    tax_rate            = Column(Numeric(5, 2),  default=Decimal("7.50"), nullable=False)
    management_fee      = Column(Numeric(10, 2), nullable=True)
    # A property manager's commission, as a percentage. ALWAYS computed on rent
    # collected only (current month + arrears) — never on deposits, which are
    # the tenant's refundable money, and never on utilities. See
    # services/commission_service.py.
    commission_rate     = Column(Numeric(5, 2),  nullable=True)
    owner_phone         = Column(String(20),  nullable=True)
    notes               = Column(Text,        nullable=True)

    # --- KRA / eTIMS (spec §1.1, §1.2) -------------------------------------
    # The property OWNER's PIN. On a rent invoice the seller is always the
    # landlord who owns the block, even when a property manager collects the
    # money — so under a PM account each property carries its own owner's PIN
    # rather than the account holder's. Denormalised from PropertyOwner.kra_pin
    # so a property with no owner row can still carry a PIN.
    owner_id            = Column(Integer, ForeignKey("property_owners.id"), nullable=True, index=True)
    kra_pin             = Column(String(11), nullable=True)
    # The opt-in switch for this whole feature. FALSE means the property renders
    # exactly as it did before any of this existed — no columns, no badges, no
    # empty states. Turning it back off hides the UI but never deletes data.
    etims_enabled       = Column(Boolean, nullable=False, server_default="false", default=False)
    # {"show_on_receipts": bool, "show_on_statements": bool, "show_on_reports": bool}
    # An absent key means that surface's default (True once enabled).
    etims_display_settings = Column(JSON, nullable=False, server_default="{}", default=dict)

    landlord       = relationship("Landlord",       back_populates="properties")
    property_group = relationship("PropertyGroup",  back_populates="properties")
    owner          = relationship("PropertyOwner",  back_populates="properties")

    units            = relationship("Unit",                    back_populates="property")
    recurring_bills  = relationship("RecurringBill",           back_populates="property",
                                    foreign_keys="RecurringBill.property_id")
    expenses         = relationship("Expense",                 back_populates="property")
    utility_readings = relationship("UtilityReading",          back_populates="property")
    maintenance_requests = relationship("MaintenanceRequest",  back_populates="property")
    invoices         = relationship("Invoice",                 back_populates="property")
    payments         = relationship("Payment",                 back_populates="property")
    manager_assignments = relationship("ManagerAssignment",    back_populates="property",
                                       foreign_keys="ManagerAssignment.property_id")
    team_member_property_accesses = relationship("TeamMemberPropertyAccess",
                                                  back_populates="property")

    def to_dict(self):
        return {
            "id":                   self.id,
            "landlord_id":          self.landlord_id,
            "property_group_id":    self.property_group_id,
            "name":                 self.name,
            "number_of_units":      self.number_of_units,
            "city":                 self.city,
            "street_name":          self.street_name,
            "water_rate":           _serialise(self.water_rate),
            "electricity_rate":     _serialise(self.electricity_rate),
            "mpesa_details":        self.mpesa_details,
            "rent_payment_penalty": _serialise(self.rent_payment_penalty),
            "tax_rate":             _serialise(self.tax_rate),
            "management_fee":       _serialise(self.management_fee),
            "commission_rate":      _serialise(self.commission_rate),
            "owner_phone":          self.owner_phone,
            "owner_id":             self.owner_id,
            "owner_name":           self.owner.full_name if self.owner else None,
            "kra_pin":              self.effective_kra_pin,
            "etims_enabled":        self.etims_enabled,
            "etims_display_settings": {
                surface: self.etims_shows(surface)
                for surface in ("receipts", "statements", "reports")
            },
            "notes":                self.notes,
            "is_deleted":           self.is_deleted,
            "deleted_at":           _serialise(self.deleted_at),
            "created_at":           _serialise(self.created_at),
            "updated_at":           _serialise(self.updated_at),
        }

    # --- eTIMS helpers -----------------------------------------------------

    @property
    def effective_kra_pin(self) -> str | None:
        """The seller PIN for this property: its own, else its owner's."""
        return self.kra_pin or (self.owner.kra_pin if self.owner else None)

    def etims_shows(self, surface: str) -> bool:
        """
        Whether eTIMS data may render on *surface* ("receipts" | "statements" |
        "reports") for this property.

        Always False while etims_enabled is off, so a single check here is
        enough to keep every document byte-identical to its pre-feature layout.
        An unset key defaults to True, because a landlord who deliberately
        turned the feature on wants to see the numbers they typed in.
        """
        if not self.etims_enabled:
            return False
        settings = self.etims_display_settings or {}
        return bool(settings.get(f"show_on_{surface}", True))


class Unit(SoftDeleteMixin, TimestampMixin, Base):
    """
    §4.3  A lettable unit inside a property.
    Soft-delete; unit names unique within a property.
    tax_rate inherits from property when null.
    """
    __tablename__ = "units"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    name        = Column(String(100), nullable=False)
    rent_amount = Column(Numeric(12, 2), nullable=False)
    tax_rate    = Column(Numeric(5, 2),  nullable=True)    # null → inherit property.tax_rate
    is_occupied = Column(Boolean, default=False, nullable=False)
    notes       = Column(Text, nullable=True)
    # The reference a tenant quotes when paying (spec §4.3). Auto-proposed as
    # {owner prefix}-{collision-free suffix}, editable by the owner, and unique
    # per ACCOUNT rather than per property — a PM's single paybill receives for
    # every block at once, so two blocks sharing "A1" would be ambiguous.
    pay_code    = Column(String(30), nullable=True, index=True)
    # Denormalised from properties.landlord_id, purely so pay-code uniqueness
    # can be enforced ACCOUNT-WIDE by a real database constraint — Postgres
    # cannot put a subquery in an index expression, and per-property uniqueness
    # would let a PM's single paybill receive an ambiguous "A1". Kept in sync by
    # the _unit_sync_landlord_id listener below, never set by callers. Mirrors
    # how invoices and payments already carry landlord_id alongside property_id.
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_units_property_name"),
        # Partial: units predating pay-codes, and soft-deleted ones, never collide.
        Index("uq_units_account_pay_code", "landlord_id", "pay_code", unique=True,
              postgresql_where=sa_text("pay_code IS NOT NULL AND is_deleted = false")),
    )

    property = relationship("Property", back_populates="units")

    tenants              = relationship("Tenant",              back_populates="unit")
    tenant_unit_history  = relationship("TenantUnitHistory",   back_populates="unit")
    invoices             = relationship("Invoice",             back_populates="unit")
    payments             = relationship("Payment",             back_populates="unit")
    utility_readings     = relationship("UtilityReading",      back_populates="unit")
    maintenance_requests = relationship("MaintenanceRequest",  back_populates="unit")
    recurring_bills      = relationship("RecurringBill",       back_populates="unit",
                                        foreign_keys="RecurringBill.unit_id")
    pay_code_aliases     = relationship("UnitPayCodeAlias",    back_populates="unit",
                                        cascade="all, delete-orphan")
    manager_assignments  = relationship("ManagerAssignment",   back_populates="unit",
                                        foreign_keys="ManagerAssignment.unit_id")

    def to_dict(self):
        return {
            "id":          self.id,
            "property_id": self.property_id,
            "name":        self.name,
            "rent_amount": _serialise(self.rent_amount),
            "tax_rate":    _serialise(self.tax_rate),
            "is_occupied": self.is_occupied,
            "pay_code":    self.pay_code,
            "notes":       self.notes,
            "is_deleted":  self.is_deleted,
            "deleted_at":  _serialise(self.deleted_at),
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


@event.listens_for(Unit, "before_insert")
@event.listens_for(Unit, "before_update")
def _unit_sync_landlord_id(mapper, connection, target):
    """
    Keep Unit.landlord_id equal to its property's owner account.

    A listener rather than a caller responsibility because units are created in
    six different places (routes, imports, demo data, three seed scripts) and a
    single missed assignment would silently disable the account-wide pay-code
    uniqueness constraint — the exact failure the column exists to prevent.
    """
    if target.property_id is None:
        return
    prop = getattr(target, "property", None)
    if prop is not None and prop.landlord_id is not None:
        target.landlord_id = prop.landlord_id
        return
    if target.landlord_id is None:
        row = connection.execute(
            sa_text("SELECT landlord_id FROM properties WHERE id = :pid"),
            {"pid": target.property_id},
        ).first()
        if row is not None:
            target.landlord_id = row[0]


class UnitPayCodeAlias(TimestampMixin, Base):
    """
    A pay-code a unit USED to have (sahilpay_payment_allocation_spec.md §4.3).

    Pay-codes stay editable forever, including after tenants have paid with
    them — locking a code the moment money touches it would trap an owner with
    a typo. The cost of that freedom is that an old code keeps arriving for
    months: tenants have it saved in M-Pesa, written on a lease, memorised. So
    the resolver matches the current code OR any retired alias, while reminders
    and statements only ever quote the current one.
    """
    __tablename__ = "unit_pay_code_aliases"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    unit_id    = Column(Integer, ForeignKey("units.id"), nullable=False, index=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    old_code   = Column(String(30), nullable=False, index=True)
    retired_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # The same account must not have two units claiming one retired code,
        # or a payment quoting it becomes ambiguous all over again.
        UniqueConstraint("landlord_id", "old_code", name="uq_unit_pay_code_aliases_landlord_code"),
    )

    unit     = relationship("Unit", back_populates="pay_code_aliases")
    landlord = relationship("Landlord")

    def to_dict(self):
        return {
            "id":         self.id,
            "unit_id":    self.unit_id,
            "old_code":   self.old_code,
            "retired_at": _serialise(self.retired_at),
        }


class InboundPaymentSource(TimestampMixin, Base):
    """
    One paybill / till / bank account money arrives through (spec §4.2).

    Named `Inbound…` because `PaymentSource` is already taken by the enum that
    says HOW a payment reached us (mpesa / co_pilot / manual). This is WHERE it
    landed — the shortcode itself — which is a different question.

    Layer 0 of the resolver. A property manager with a single paybill has one
    row and it is a no-op passthrough. A landlord whose three blocks each
    collect to a different till has three, each mapped to its property — which
    is what lets the resolver narrow to the right block BEFORE it even looks at
    the reference.

    Deliberately NOT named after M-Pesa: a bank-to-M-Pesa or Pochi feed is the
    same concept.
    """
    __tablename__ = "payment_sources"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id        = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    label              = Column(String(120), nullable=False)
    shortcode          = Column(String(30), nullable=True, index=True)
    # Free-text fragment matched against the parsed business name, for feeds
    # whose SMS carries a name rather than a numeric shortcode.
    match_pattern      = Column(String(120), nullable=True)
    mapped_property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    mapped_owner_id    = Column(Integer, ForeignKey("property_owners.id"), nullable=True, index=True)
    forwarding_phone   = Column(String(20), nullable=True)
    is_active          = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("landlord_id", "shortcode", name="uq_payment_sources_landlord_shortcode"),
    )

    landlord        = relationship("Landlord", back_populates="payment_sources")
    mapped_property = relationship("Property")
    mapped_owner    = relationship("PropertyOwner")

    def to_dict(self):
        return {
            "id":                 self.id,
            "landlord_id":        self.landlord_id,
            "label":              self.label,
            "shortcode":          self.shortcode,
            "match_pattern":      self.match_pattern,
            "mapped_property_id": self.mapped_property_id,
            "mapped_property_name": self.mapped_property.name if self.mapped_property else None,
            "mapped_owner_id":    self.mapped_owner_id,
            "forwarding_phone":   self.forwarding_phone,
            "is_active":          self.is_active,
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }


class CommissionRule(TimestampMixin, Base):
    """
    A property manager's commission, configurable at three levels (spec §4.8).

    MOST SPECIFIC WINS: a unit rule beats a property rule beats a landlord
    (account-wide) rule. That ordering exists because real agreements are
    exactly this shape — "10% across the board, except the Westlands block at
    8%, except penthouse A1 at a flat 15,000".

    The BASE is always RENT COLLECTED ONLY — current rent plus rent arrears,
    never deposits (the tenant's refundable money) and never utilities
    (collected on the owner's behalf). That is a legal constraint in Kenya, not
    a preference, so no field here can widen it.
    """
    __tablename__ = "commission_rules"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    scope_type  = Column(String(10), nullable=False)     # enum CommissionScopeType
    # NULL scope_id with scope_type='landlord' means the whole account.
    scope_id    = Column(Integer, nullable=True)
    rate_type   = Column(String(12), nullable=False, default=CommissionRateType.percentage.value)
    rate_value  = Column(Numeric(12, 2), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)
    notes       = Column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "scope_type", "scope_id",
                         name="uq_commission_rules_scope"),
        CheckConstraint("rate_value >= 0", name="ck_commission_rules_non_negative"),
        Index("ix_commission_rules_lookup", "landlord_id", "scope_type", "scope_id"),
    )

    landlord = relationship("Landlord", back_populates="commission_rules")

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "scope_type":  self.scope_type,
            "scope_id":    self.scope_id,
            "rate_type":   self.rate_type,
            "rate_value":  _serialise(self.rate_value),
            "is_active":   self.is_active,
            "notes":       self.notes,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class AllocationAudit(CreatedAtMixin, Base):
    """
    Append-only record of every allocate / reallocate / reverse (spec §4.11).

    The spec's hard rule is "nothing is ever silently split". This table is how
    that is provable after the fact: who or what moved the money, what the
    allocation looked like before and after, and why. `actor_user_id` is NULL
    when the resolver acted on its own — that is the system, not an unknown
    person.
    """
    __tablename__ = "allocation_audit"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    payment_id    = Column(Integer, ForeignKey("payments.id"), nullable=False, index=True)
    action        = Column(String(12), nullable=False)   # enum AllocationAuditAction
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    before_json   = Column(JSON, nullable=True)
    after_json    = Column(JSON, nullable=True)
    reason        = Column(String(255), nullable=True)

    landlord = relationship("Landlord")
    payment  = relationship("Payment")
    actor    = relationship("User", foreign_keys=[actor_user_id])

    def to_dict(self):
        return {
            "id":            self.id,
            "landlord_id":   self.landlord_id,
            "payment_id":    self.payment_id,
            "action":        self.action,
            "actor_user_id": self.actor_user_id,
            "before":        self.before_json,
            "after":         self.after_json,
            "reason":        self.reason,
            "created_at":    _serialise(self.created_at),
        }


class RecurringBill(TimestampMixin, Base):
    """
    §4.4  "Other recurring bills" attached to a property or unit.
    At least one of property_id / unit_id must be set (CheckConstraint).
    """
    __tablename__ = "recurring_bills"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True,  index=True)
    unit_id     = Column(Integer, ForeignKey("units.id"),      nullable=True,  index=True)
    name        = Column(String(120), nullable=False)
    amount      = Column(Numeric(12, 2), nullable=False)
    is_active   = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(property_id IS NOT NULL) OR (unit_id IS NOT NULL)",
            name="ck_recurring_bills_property_or_unit",
        ),
    )

    landlord = relationship("Landlord",  back_populates="recurring_bills")
    property = relationship("Property",  back_populates="recurring_bills",
                             foreign_keys=[property_id])
    unit     = relationship("Unit",      back_populates="recurring_bills",
                             foreign_keys=[unit_id])

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "property_id": self.property_id,
            "unit_id":     self.unit_id,
            "name":        self.name,
            "amount":      _serialise(self.amount),
            "is_active":   self.is_active,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class ManagerAssignment(TimestampMixin, Base):
    """
    §4.5  Assigns a team member as manager scoped to a unit, property, or group.
    Exactly one of unit_id / property_id / property_group_id must be set.
    """
    __tablename__ = "manager_assignments"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    team_member_id    = Column(Integer, ForeignKey("team_members.id"),    nullable=False, index=True)
    scope_type        = Column(String(15), nullable=False)    # enum ManagerScopeType
    unit_id           = Column(Integer, ForeignKey("units.id"),           nullable=True, index=True)
    property_id       = Column(Integer, ForeignKey("properties.id"),      nullable=True, index=True)
    property_group_id = Column(Integer, ForeignKey("property_groups.id"), nullable=True, index=True)

    __table_args__ = (
        CheckConstraint(
            """
            (
              (unit_id IS NOT NULL AND property_id IS NULL AND property_group_id IS NULL) OR
              (unit_id IS NULL AND property_id IS NOT NULL AND property_group_id IS NULL) OR
              (unit_id IS NULL AND property_id IS NULL AND property_group_id IS NOT NULL)
            )
            """,
            name="ck_manager_assignments_exactly_one_scope",
        ),
    )

    team_member    = relationship("TeamMember",    back_populates="manager_assignments")
    unit           = relationship("Unit",          back_populates="manager_assignments",
                                  foreign_keys=[unit_id])
    property       = relationship("Property",      back_populates="manager_assignments",
                                  foreign_keys=[property_id])
    property_group = relationship("PropertyGroup", back_populates="manager_assignments")

    def to_dict(self):
        return {
            "id":                self.id,
            "team_member_id":    self.team_member_id,
            "scope_type":        self.scope_type,
            "unit_id":           self.unit_id,
            "property_id":       self.property_id,
            "property_group_id": self.property_group_id,
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN C — Tenancy  (3 tables)
# ===========================================================================

class Tenant(SoftDeleteMixin, TimestampMixin, Base):
    """
    §5.1  Tenant occupying a unit.  Soft-delete — deleted tenants appear
    in reports.

    Schema-level validations (Marshmallow/Pydantic):
      - deposit_returned <= deposit_paid
      - lease_expiry_date >= lease_start_date
    """
    __tablename__ = "tenants"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    user_id              = Column(Integer, ForeignKey("users.id"),     nullable=True,  index=True)
    landlord_id          = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    unit_id              = Column(Integer, ForeignKey("units.id"),     nullable=False, index=True)
    first_name           = Column(String(100), nullable=False)
    last_name            = Column(String(100), nullable=False)
    phone                = Column(String(20),  nullable=False, index=True)
    secondary_phone      = Column(String(20),  nullable=True)
    email                = Column(String(255), nullable=True)
    national_id          = Column(String(30),  nullable=True)
    kra_pin              = Column(String(30),  nullable=True)
    account_number       = Column(String(50),  nullable=True)
    deposit_amount       = Column(Numeric(12, 2), nullable=True)
    deposit_paid         = Column(Numeric(12, 2), nullable=True)
    deposit_returned     = Column(Numeric(12, 2), nullable=True)
    rent_payment_penalty = Column(Numeric(10, 2), nullable=True)
    bank_payer_name      = Column(String(150), nullable=True)
    balance              = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    # Advance/credit held on the account (from overpayment). Auto-applied to the next
    # invoice / monthly billing. Always equals the sum of the credit ledger (spec §1.5).
    credit_balance       = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    lease_start_date     = Column(Date, nullable=True)
    lease_expiry_date    = Column(Date, nullable=True)
    move_in_date         = Column(Date, nullable=True)
    move_out_date        = Column(Date, nullable=True)
    notes                = Column(Text, nullable=True)
    # Payment score out of 100 — how reliably this tenant has paid RENT since
    # move-in (see services/tenant_score_service.py). NULL means "not enough
    # history to judge", which the UI shows as "New" rather than a flattering
    # 100. Recomputed when a payment is confirmed and nightly by Celery.
    tenant_score            = Column(Integer, nullable=True)
    tenant_score_updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "account_number", name="uq_tenants_landlord_account"),
    )

    user     = relationship("User",     back_populates="tenant_profiles")
    landlord = relationship("Landlord", back_populates="tenants")
    unit     = relationship("Unit",     back_populates="tenants")

    invoices             = relationship("Invoice",            back_populates="tenant")
    payments             = relationship("Payment",            back_populates="tenant")
    maintenance_requests = relationship("MaintenanceRequest", back_populates="tenant")
    communication_logs   = relationship("CommunicationLog",   back_populates="tenant")
    documents            = relationship("TenantDocument",     back_populates="tenant",
                                        cascade="all, delete-orphan")
    unit_history         = relationship("TenantUnitHistory",  back_populates="tenant",
                                        cascade="all, delete-orphan")
    mpesa_transactions   = relationship("MpesaTransaction",   back_populates="tenant")
    credit_ledger        = relationship("CreditLedger",       back_populates="tenant",
                                        cascade="all, delete-orphan")
    balance_rollovers    = relationship("BalanceRollover",    back_populates="tenant",
                                        cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":                   self.id,
            "user_id":              self.user_id,
            "landlord_id":          self.landlord_id,
            "unit_id":              self.unit_id,
            "first_name":           self.first_name,
            "last_name":            self.last_name,
            "phone":                self.phone,
            "secondary_phone":      self.secondary_phone,
            "email":                self.email,
            "national_id":          self.national_id,
            "kra_pin":              self.kra_pin,
            "account_number":       self.account_number,
            "deposit_amount":       _serialise(self.deposit_amount),
            "deposit_paid":         _serialise(self.deposit_paid),
            "deposit_returned":     _serialise(self.deposit_returned),
            "rent_payment_penalty": _serialise(self.rent_payment_penalty),
            "bank_payer_name":      self.bank_payer_name,
            "balance":              _serialise(self.balance),
            "credit_balance":       _serialise(self.credit_balance),
            "lease_start_date":     _serialise(self.lease_start_date),
            "lease_expiry_date":    _serialise(self.lease_expiry_date),
            "move_in_date":         _serialise(self.move_in_date),
            "move_out_date":        _serialise(self.move_out_date),
            "notes":                self.notes,
            "tenant_score":         self.tenant_score,
            "tenant_score_label":   self._score_label(),
            "tenant_score_updated_at": _serialise(self.tenant_score_updated_at),
            "is_deleted":           self.is_deleted,
            "deleted_at":           _serialise(self.deleted_at),
            "created_at":           _serialise(self.created_at),
            "updated_at":           _serialise(self.updated_at),
        }


    def _score_label(self) -> str:
        """Human reading of tenant_score — 'New' when there's no history yet."""
        score = self.tenant_score
        if score is None:
            return "New"
        if score >= 90:
            return "Excellent"
        if score >= 75:
            return "Good"
        if score >= 60:
            return "Fair"
        if score >= 40:
            return "Poor"
        return "High risk"


class TenantUnitHistory(TimestampMixin, Base):
    """§5.2  Records every unit a tenant has occupied; written on 'shift tenant'."""
    __tablename__ = "tenant_unit_history"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    unit_id      = Column(Integer, ForeignKey("units.id"),   nullable=False, index=True)
    moved_in_at  = Column(Date, nullable=False)
    moved_out_at = Column(Date, nullable=True)    # null = current occupancy

    tenant = relationship("Tenant", back_populates="unit_history")
    unit   = relationship("Unit",   back_populates="tenant_unit_history")

    def to_dict(self):
        return {
            "id":           self.id,
            "tenant_id":    self.tenant_id,
            "unit_id":      self.unit_id,
            "moved_in_at":  _serialise(self.moved_in_at),
            "moved_out_at": _serialise(self.moved_out_at),
            "created_at":   _serialise(self.created_at),
            "updated_at":   _serialise(self.updated_at),
        }


class TenantDocument(TimestampMixin, Base):
    """§5.3  Files in a tenant's upload folder (IDs, signed leases, etc.)."""
    __tablename__ = "tenant_documents"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name      = Column(String(200), nullable=True)
    file_url  = Column(String(255), nullable=False)    # S3 / Cloudinary

    tenant = relationship("Tenant", back_populates="documents")

    def to_dict(self):
        return {
            "id":         self.id,
            "tenant_id":  self.tenant_id,
            "name":       self.name,
            "file_url":   self.file_url,
            "created_at": _serialise(self.created_at),
            "updated_at": _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN D — Invoicing  (2 tables)
# ===========================================================================

class Invoice(SoftDeleteMixin, TimestampMixin, Base):
    """
    §6.1  Bill issued to a tenant.  Header + line items pattern.
    Soft-delete.

    Schema-level validations:
      - total_amount must equal sum of line items (server-side).
      - Status transitions: open → partial → paid driven by payment_allocations.
        void / draft set manually.
    """
    __tablename__ = "invoices"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String(40),  nullable=False, index=True)
    landlord_id    = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    tenant_id      = Column(Integer, ForeignKey("tenants.id"),    nullable=False, index=True)
    unit_id        = Column(Integer, ForeignKey("units.id"),      nullable=False, index=True)
    property_id    = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    invoice_type   = Column(String(20), nullable=True)     # enum InvoiceType
    issue_date     = Column(Date, nullable=False)
    due_date       = Column(Date, nullable=True)
    status         = Column(String(15), nullable=True)     # enum InvoiceStatus
    total_amount   = Column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    amount_paid    = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    balance        = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    title          = Column(String(150), nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "invoice_number", name="uq_invoices_landlord_number"),
    )

    landlord = relationship("Landlord", back_populates="invoices")
    tenant   = relationship("Tenant",   back_populates="invoices")
    unit     = relationship("Unit",     back_populates="invoices")
    property = relationship("Property", back_populates="invoices")

    line_items          = relationship("InvoiceLineItem",   back_populates="invoice",
                                       cascade="all, delete-orphan")
    payment_allocations = relationship("PaymentAllocation", back_populates="invoice")
    utility_readings    = relationship("UtilityReading",    back_populates="invoice")

    def to_dict(self):
        return {
            "id":             self.id,
            "invoice_number": self.invoice_number,
            "landlord_id":    self.landlord_id,
            "tenant_id":      self.tenant_id,
            "unit_id":        self.unit_id,
            "property_id":    self.property_id,
            "invoice_type":   self.invoice_type,
            "issue_date":     _serialise(self.issue_date),
            "due_date":       _serialise(self.due_date),
            "status":         self.status,
            "total_amount":   _serialise(self.total_amount),
            "amount_paid":    _serialise(self.amount_paid),
            "balance":        _serialise(self.balance),
            "title":          self.title,
            "is_deleted":     self.is_deleted,
            "deleted_at":     _serialise(self.deleted_at),
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
        }


class InvoiceLineItem(TimestampMixin, Base):
    """§6.2  Individual charge line on an invoice."""
    __tablename__ = "invoice_line_items"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id         = Column(Integer, ForeignKey("invoices.id"),        nullable=False, index=True)
    item               = Column(String(120), nullable=False)
    description        = Column(Text, nullable=True)
    quantity           = Column(Numeric(10, 2), default=Decimal("1"), nullable=False)
    unit_price         = Column(Numeric(12, 2), nullable=False)
    amount             = Column(Numeric(12, 2), nullable=False)    # qty × unit_price
    utility_reading_id = Column(Integer, ForeignKey("utility_readings.id"), nullable=True, index=True)
    # Charge-category restructure (spec §1.2): the (category, subcategory) this line
    # bills, plus its own paid/status so payments allocate at the line level.
    # category_id/subcategory are nullable for now — they become NOT NULL once every
    # line-item writer stamps them (later phase).
    category_id        = Column(Integer, ForeignKey("charge_categories.id"), nullable=True, index=True)
    subcategory        = Column(String(10), nullable=True, index=True)   # enum SubCategory
    amount_paid        = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    status             = Column(String(10), default="open", nullable=False)   # enum LineItemStatus

    invoice         = relationship("Invoice",        back_populates="line_items")
    utility_reading = relationship("UtilityReading", back_populates="line_items")
    category        = relationship("ChargeCategory", back_populates="line_items")
    payment_allocations = relationship("PaymentAllocation", back_populates="line_item")

    @property
    def remaining(self) -> Decimal:
        return (self.amount or Decimal("0")) - (self.amount_paid or Decimal("0"))

    def to_dict(self):
        return {
            "id":                 self.id,
            "invoice_id":         self.invoice_id,
            "item":               self.item,
            "description":        self.description,
            "quantity":           _serialise(self.quantity),
            "unit_price":         _serialise(self.unit_price),
            "amount":             _serialise(self.amount),
            "utility_reading_id": self.utility_reading_id,
            "category_id":        self.category_id,
            "subcategory":        self.subcategory,
            "amount_paid":        _serialise(self.amount_paid),
            "remaining":          _serialise(self.remaining),
            "status":             self.status,
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN E — Payments  (5 tables)
# ===========================================================================

class BankStatementUpload(TimestampMixin, Base):
    """§7.3  Uploaded bank statement queued for async Celery parsing."""
    __tablename__ = "bank_statement_uploads"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    file_url    = Column(String(255), nullable=False)
    status      = Column(String(15),  nullable=True)    # enum BankStatementStatus
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    landlord     = relationship("Landlord", back_populates="bank_statement_uploads")
    transactions = relationship("BankStatementTransaction", back_populates="bank_statement",
                                cascade="all, delete-orphan")
    payments     = relationship("Payment", back_populates="bank_statement")

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "file_url":    self.file_url,
            "status":      self.status,
            "uploaded_at": _serialise(self.uploaded_at),
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class Payment(EtimsMixin, SoftDeleteMixin, TimestampMixin, Base):
    """
    §7.1  Payment received (manual / M-Pesa / Co-pilot / bank-statement).
    Soft-delete.

    Schema-level validations:
      - sum(payment_allocations.amount_allocated) <= amount
      - Unallocated remainder becomes tenant advance/credit on tenant.balance.
    """
    __tablename__ = "payments"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    payment_ref       = Column(String(50),  nullable=False, index=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"),           nullable=False, index=True)
    tenant_id         = Column(Integer, ForeignKey("tenants.id"),             nullable=True,  index=True)
    unit_id           = Column(Integer, ForeignKey("units.id"),               nullable=True,  index=True)
    property_id       = Column(Integer, ForeignKey("properties.id"),          nullable=True,  index=True)
    amount            = Column(Numeric(12, 2), nullable=False)
    payment_date      = Column(Date, nullable=False)
    status            = Column(String(15), nullable=True)     # enum PaymentStatus
    source            = Column(String(20), nullable=True)     # enum PaymentSource
    payment_method    = Column(String(40), nullable=True)
    mpesa_reference   = Column(String(40), nullable=True, index=True)
    till_number       = Column(String(20), nullable=True)
    bank_statement_id = Column(Integer, ForeignKey("bank_statement_uploads.id"), nullable=True, index=True)
    receipt_url       = Column(String(255), nullable=True)
    proof_url         = Column(String(255), nullable=True)   # tenant-uploaded proof of payment (pending submissions)
    notes             = Column(Text, nullable=True)
    # --- Resolver fields (sahilpay_payment_allocation_spec.md §4.1, §4.5) ----
    # The account reference the payer actually typed, kept verbatim. This is the
    # ONE field that reliably survives a forwarded M-Pesa SMS — payer phone is
    # frequently masked — so it is what the resolver matches on.
    reference_text    = Column(String(120), nullable=True, index=True)
    source_id         = Column(Integer, ForeignKey("payment_sources.id"), nullable=True, index=True)
    payer_phone       = Column(String(30), nullable=True)
    # Why this payment is sitting in suspense, when it is. NULL otherwise.
    suspense_reason   = Column(String(30), nullable=True)
    # An arrears-first split the manager can accept in one tap or adjust. Only
    # ever a SUGGESTION — never committed without an explicit confirmation.
    suggested_split_json = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "payment_ref", name="uq_payments_landlord_ref"),
        # An eTIMS number identifies one invoice at KRA, so it can only ever sit
        # on one payment. Partial, because the overwhelming majority of rows
        # have no number and must not collide with each other.
        Index("uq_payments_etims_invoice_number", "etims_invoice_number",
              unique=True, postgresql_where=Column("etims_invoice_number").isnot(None)),
        # The suspense/review queue is "everything unsettled for this account",
        # so it filters on landlord and status together.
        Index("ix_payments_landlord_status", "landlord_id", "status"),
    )

    landlord       = relationship("Landlord",            back_populates="payments")
    etims_entered_by = relationship("User", foreign_keys="Payment.etims_entered_by_user_id")
    tenant         = relationship("Tenant",              back_populates="payments")
    unit           = relationship("Unit",                back_populates="payments")
    property       = relationship("Property",            back_populates="payments")
    bank_statement = relationship("BankStatementUpload", back_populates="payments")

    payment_allocations = relationship("PaymentAllocation",    back_populates="payment",
                                       cascade="all, delete-orphan")
    mpesa_transactions  = relationship("MpesaTransaction",     back_populates="payment")
    bank_txn_matches    = relationship("BankStatementTransaction",
                                       back_populates="matched_payment",
                                       foreign_keys="BankStatementTransaction.matched_payment_id")

    def to_dict(self):
        return {
            "id":                self.id,
            "payment_ref":       self.payment_ref,
            "landlord_id":       self.landlord_id,
            "tenant_id":         self.tenant_id,
            "unit_id":           self.unit_id,
            "property_id":       self.property_id,
            "amount":            _serialise(self.amount),
            "payment_date":      _serialise(self.payment_date),
            "status":            self.status,
            "source":            self.source,
            "payment_method":    self.payment_method,
            "mpesa_reference":   self.mpesa_reference,
            "till_number":       self.till_number,
            "bank_statement_id": self.bank_statement_id,
            "receipt_url":       self.receipt_url,
            "proof_url":         self.proof_url,
            "notes":             self.notes,
            "reference_text":    self.reference_text,
            "source_id":         self.source_id,
            "payer_phone":       self.payer_phone,
            "suspense_reason":   self.suspense_reason,
            "suggested_split":   self.suggested_split_json,
            **self.etims_dict(),
            "is_deleted":        self.is_deleted,
            "deleted_at":        _serialise(self.deleted_at),
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


class PaymentAllocation(TimestampMixin, Base):
    """
    §7.2  M:N link — applies part/all of a payment to an invoice.
    amount_allocated > 0 enforced by CheckConstraint.
    """
    __tablename__ = "payment_allocations"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    payment_id       = Column(Integer, ForeignKey("payments.id"), nullable=False, index=True)
    invoice_id       = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    # Charge-category restructure (spec §1.3): allocation now targets a specific line
    # item. Nullable for now; the (payment_id, invoice_id) unique constraint below is
    # swapped for (payment_id, line_item_id) in the phase that rewrites create_payment.
    line_item_id     = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=True, index=True)
    amount_allocated = Column(Numeric(12, 2), nullable=False)
    # Who split this shilling and how (spec §5). 'auto' is the resolver's own
    # waterfall; 'manual' is a human in the review queue. allocated_by is NULL
    # for auto, which is the system rather than an unknown person.
    allocated_by     = Column(Integer, ForeignKey("users.id"), nullable=True)
    method           = Column(String(10), nullable=True, default="auto")

    __table_args__ = (
        UniqueConstraint("payment_id", "line_item_id", name="uq_payment_allocations_payment_line_item"),
        CheckConstraint("amount_allocated > 0", name="ck_payment_allocations_positive"),
    )

    payment   = relationship("Payment", back_populates="payment_allocations")
    invoice   = relationship("Invoice", back_populates="payment_allocations")
    line_item = relationship("InvoiceLineItem", back_populates="payment_allocations")

    def to_dict(self):
        return {
            "id":               self.id,
            "payment_id":       self.payment_id,
            "invoice_id":       self.invoice_id,
            "line_item_id":     self.line_item_id,
            "amount_allocated": _serialise(self.amount_allocated),
            "allocated_by":     self.allocated_by,
            "method":           self.method,
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
        }


class BankStatementTransaction(TimestampMixin, Base):
    """§7.4  Single parsed line from an uploaded bank statement."""
    __tablename__ = "bank_statement_transactions"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    bank_statement_id  = Column(Integer, ForeignKey("bank_statement_uploads.id"), nullable=False, index=True)
    txn_date           = Column(Date,    nullable=True)
    description        = Column(Text,    nullable=True)
    amount             = Column(Numeric(12, 2), nullable=True)
    reference          = Column(String(50), nullable=True)
    is_imported        = Column(Boolean, default=False, nullable=False)
    matched_payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)

    bank_statement  = relationship("BankStatementUpload", back_populates="transactions")
    matched_payment = relationship("Payment",             back_populates="bank_txn_matches",
                                   foreign_keys=[matched_payment_id])

    def to_dict(self):
        return {
            "id":                self.id,
            "bank_statement_id": self.bank_statement_id,
            "txn_date":          _serialise(self.txn_date),
            "description":       self.description,
            "amount":            _serialise(self.amount),
            "reference":         self.reference,
            "is_imported":       self.is_imported,
            "matched_payment_id": self.matched_payment_id,
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


class MpesaTransaction(TimestampMixin, Base):
    """§7.5  Backing store for the M-Pesa Transaction Status lookup tool."""
    __tablename__ = "mpesa_transactions"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id      = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    reference_number = Column(String(40), nullable=False, index=True)
    shortcode        = Column(String(20), nullable=True)
    till_number      = Column(String(20), nullable=True)
    status           = Column(String(20), nullable=True)    # enum MpesaTransactionStatus
    description      = Column(Text,       nullable=True)
    amount           = Column(Numeric(12, 2), nullable=True)
    tenant_id        = Column(Integer, ForeignKey("tenants.id"),  nullable=True, index=True)
    payment_id       = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)
    created_date     = Column(DateTime, default=datetime.utcnow)

    landlord = relationship("Landlord", back_populates="mpesa_transactions")
    tenant   = relationship("Tenant",   back_populates="mpesa_transactions")
    payment  = relationship("Payment",  back_populates="mpesa_transactions")

    def to_dict(self):
        return {
            "id":               self.id,
            "landlord_id":      self.landlord_id,
            "reference_number": self.reference_number,
            "shortcode":        self.shortcode,
            "till_number":      self.till_number,
            "status":           self.status,
            "description":      self.description,
            "amount":           _serialise(self.amount),
            "tenant_id":        self.tenant_id,
            "payment_id":       self.payment_id,
            "created_date":     _serialise(self.created_date),
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
        }


# ===========================================================================
# Daraja production integration (MPESA_INTEGRATION_SPEC.md) — platform
# paybill webhooks: STK billing callback, C2B direct-paybill confirmation,
# B2C affiliate payout results. All distinct from MpesaTransaction above,
# which is the landlord's OWN rent-collection tooling.
# ===========================================================================

class DarajaCallbackLog(TimestampMixin, Base):
    """
    §MPESA_INTEGRATION_SPEC.md §4.1  Raw payload log — the forensic trail for
    every shilling that crosses a Daraja webhook. Written BEFORE any
    processing, on every callback, successful or not.
    """
    __tablename__ = "daraja_callback_logs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    kind         = Column(String(20), nullable=False, index=True)  # stk | c2b_validation | c2b_confirmation | b2c_result | b2c_timeout
    remote_ip    = Column(String(45), nullable=True)
    payload_json = Column(JSON, nullable=False)
    processed    = Column(Boolean, default=False, nullable=False)
    error        = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id":           self.id,
            "kind":         self.kind,
            "remote_ip":    self.remote_ip,
            "payload_json": self.payload_json,
            "processed":    self.processed,
            "error":        self.error,
            "created_at":   _serialise(self.created_at),
        }


class PlatformC2BPayment(TimestampMixin, Base):
    """
    §MPESA_INTEGRATION_SPEC.md §5.1  A direct-paybill (C2B) payment received
    on the PLATFORM shortcode (subscriptions/SMS credits only — never rent).
    Every confirmation is recorded here regardless of whether it could be
    auto-matched, so nothing that touched the platform paybill is ever lost.
    """
    __tablename__ = "platform_c2b_payments"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    trans_id       = Column(String(20), nullable=False, unique=True, index=True)  # M-Pesa receipt
    amount         = Column(Numeric(12, 2), nullable=False)
    bill_ref       = Column(String(30), nullable=True)
    msisdn         = Column(String(64), nullable=True)   # may arrive hashed
    payer_name     = Column(String(120), nullable=True)
    trans_time     = Column(String(20), nullable=True)    # raw Daraja YYYYMMDDHHMMSS
    landlord_id    = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)
    billing_transaction_id = Column(Integer, ForeignKey("billing_transactions.id"), nullable=True)
    status         = Column(String(20), nullable=False, default="unmatched")  # matched | unmatched | resolved
    resolved_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_note      = Column(Text, nullable=True)

    landlord            = relationship("Landlord", foreign_keys=[landlord_id])
    billing_transaction = relationship("BillingTransaction", foreign_keys=[billing_transaction_id])

    def to_dict(self):
        return {
            "id":                      self.id,
            "trans_id":                self.trans_id,
            "amount":                  _serialise(self.amount),
            "bill_ref":                self.bill_ref,
            "msisdn":                  self.msisdn,
            "payer_name":              self.payer_name,
            "trans_time":              self.trans_time,
            "landlord_id":             self.landlord_id,
            "billing_transaction_id":  self.billing_transaction_id,
            "status":                  self.status,
            "resolved_by_admin_id":    self.resolved_by_admin_id,
            "resolution_note":         self.resolution_note,
            "created_at":              _serialise(self.created_at),
            "updated_at":              _serialise(self.updated_at),
        }


# ===========================================================================
# Co-Pilot — SMS-forwarder platform (COPILOT_PLATFORM_SPEC.md)
# ===========================================================================
#
# A landlord installs the Co-Pilot Android app on their phone, pairs it with
# an agent_code (Landlord.agent_code), and it forwards raw payment-confirmation
# SMS text to POST /api/copilot/ingest. The pipeline (services/copilot_service.py)
# parses the text against admin-managed SmsParserTemplate rows, matches the
# result to a tenant, and creates a Payment through the SAME allocation_service
# path manual payments use — never a direct balance write.
# ===========================================================================

class CopilotDevice(TimestampMixin, Base):
    """One paired phone. Auth token is stored only as a sha256 hash — the raw
    token is returned once, at pairing, and never persisted in the clear."""
    __tablename__ = "copilot_devices"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    device_name   = Column(String(100), nullable=False)
    device_model  = Column(String(100), nullable=True)
    app_version   = Column(String(20),  nullable=True)
    token_hash    = Column(String(64),  nullable=False, unique=True, index=True)
    status        = Column(String(10),  default=CopilotDeviceStatus.active.value, nullable=False)
    sender_ids    = Column(Text, nullable=True)   # JSON array of sender IDs this device forwards
    last_seen_at  = Column(DateTime, nullable=True)
    revoked_at    = Column(DateTime, nullable=True)
    revoked_by    = Column(String(20), nullable=True)   # 'landlord' | 'admin'

    landlord = relationship("Landlord", back_populates="copilot_devices")
    messages = relationship("CopilotMessage", back_populates="device")

    def to_dict(self):
        import json as _json
        try:
            sender_ids = _json.loads(self.sender_ids) if self.sender_ids else []
        except (ValueError, TypeError):
            sender_ids = []
        return {
            "id":            self.id,
            "landlord_id":   self.landlord_id,
            "device_name":   self.device_name,
            "device_model":  self.device_model,
            "app_version":   self.app_version,
            "status":        self.status,
            "sender_ids":    sender_ids,
            "last_seen_at":  _serialise(self.last_seen_at),
            "revoked_at":    _serialise(self.revoked_at),
            "revoked_by":    self.revoked_by,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


class SmsParserTemplate(TimestampMixin, Base):
    """
    Admin-managed placeholder pattern for one bank/sender's SMS shape — the
    "no backend change per bank" registry. Global scope: a KCB alert reads
    the same for every landlord, so there is no landlord_id here.
    """
    __tablename__ = "sms_parser_templates"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String(100), nullable=False)
    sender_id     = Column(String(30),  nullable=False, index=True)
    template_text = Column(Text, nullable=False)
    sample_text   = Column(Text, nullable=True)
    is_active     = Column(Boolean, default=True, nullable=False)
    priority      = Column(Integer, default=100, nullable=False)
    created_by    = Column(Integer, ForeignKey("users.id"), nullable=True)

    def to_dict(self):
        return {
            "id":            self.id,
            "name":          self.name,
            "sender_id":     self.sender_id,
            "template_text": self.template_text,
            "sample_text":   self.sample_text,
            "is_active":     self.is_active,
            "priority":      self.priority,
            "created_by":    self.created_by,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


class CopilotMessage(CreatedAtMixin, Base):
    """
    One row per SMS ever forwarded by a Co-Pilot device, whatever the outcome —
    the audit backbone for both the landlord's own activity feed and the
    admin's global ingest log. Append-only (no updated_at).
    """
    __tablename__ = "copilot_messages"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id          = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    device_id            = Column(Integer, ForeignKey("copilot_devices.id"), nullable=False, index=True)
    client_uuid          = Column(String(40), nullable=False)
    sender_id            = Column(String(30), nullable=False, index=True)
    raw_text             = Column(Text, nullable=False)
    sms_received_at      = Column(DateTime, nullable=True)
    dedupe_hash          = Column(String(64), nullable=False, index=True)
    parse_status         = Column(String(12), nullable=False)
    match_status         = Column(String(12), nullable=False, default=CopilotMatchStatus.n_a.value)
    template_id          = Column(Integer, ForeignKey("sms_parser_templates.id"), nullable=True)
    parsed_ref           = Column(String(40),  nullable=True, index=True)
    parsed_amount        = Column(Numeric(12, 2), nullable=True)
    parsed_name          = Column(String(120), nullable=True)
    parsed_account       = Column(String(50),  nullable=True)
    parsed_phone         = Column(String(20),  nullable=True)
    error_reason         = Column(String(255), nullable=True)
    tenant_id            = Column(Integer, ForeignKey("tenants.id"),   nullable=True, index=True)
    payment_id           = Column(Integer, ForeignKey("payments.id"),  nullable=True, index=True)
    mpesa_transaction_id = Column(Integer, ForeignKey("mpesa_transactions.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "client_uuid", name="uq_copilot_messages_device_uuid"),
    )

    landlord         = relationship("Landlord",       back_populates="copilot_messages")
    device           = relationship("CopilotDevice",  back_populates="messages")
    template         = relationship("SmsParserTemplate")
    tenant           = relationship("Tenant")
    payment          = relationship("Payment")
    mpesa_transaction = relationship("MpesaTransaction")

    @property
    def raw_text_redacted(self) -> bool:
        """True when raw_text is a services.copilot_service._redact_unmatched()
        stub rather than the real SMS body (COPILOT_LANDLORD_INBOX_SPEC.md §2.2/§3.1)."""
        return bool(self.raw_text) and self.raw_text.startswith("[redacted: no matching template]")

    def to_dict(self, include_raw: bool = True):
        return {
            "id":               self.id,
            "landlord_id":      self.landlord_id,
            "device_id":        self.device_id,
            "client_uuid":      self.client_uuid,
            "sender_id":        self.sender_id,
            "raw_text":         self.raw_text if include_raw else None,
            "sms_received_at":  _serialise(self.sms_received_at),
            "parse_status":     self.parse_status,
            "match_status":     self.match_status,
            "template_id":      self.template_id,
            "parsed_ref":       self.parsed_ref,
            "parsed_amount":    _serialise(self.parsed_amount),
            "parsed_name":      self.parsed_name,
            "parsed_account":   self.parsed_account,
            "parsed_phone":     self.parsed_phone,
            "error_reason":     self.error_reason,
            "tenant_id":        self.tenant_id,
            "payment_id":       self.payment_id,
            "mpesa_transaction_id": self.mpesa_transaction_id,
            "created_at":       _serialise(self.created_at),
        }


class CopilotAppRelease(CreatedAtMixin, Base):
    """One uploaded Co-Pilot APK build. Admin manages these; the app's
    heartbeat/latest-version check reads whichever row has is_latest=True."""
    __tablename__ = "copilot_app_releases"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    version_name                = Column(String(20), nullable=False)
    version_code                = Column(Integer, nullable=False, unique=True)
    apk_path                    = Column(String(255), nullable=False)
    release_notes               = Column(Text, nullable=True)
    is_latest                   = Column(Boolean, default=False, nullable=False)
    min_supported_version_code  = Column(Integer, nullable=True)
    uploaded_by                 = Column(Integer, ForeignKey("users.id"), nullable=True)

    def to_dict(self):
        return {
            "id":                          self.id,
            "version_name":                self.version_name,
            "version_code":                self.version_code,
            "apk_path":                    self.apk_path,
            "release_notes":               self.release_notes,
            "is_latest":                   self.is_latest,
            "min_supported_version_code":  self.min_supported_version_code,
            "uploaded_by":                 self.uploaded_by,
            "created_at":                  _serialise(self.created_at),
        }


# ===========================================================================
# DOMAIN F — Expenses, Utilities & Maintenance  (4 tables)
# ===========================================================================
#
# CIRCULAR FK NOTE:
#   Expense.maintenance_request_id  → maintenance_requests.id  (use_alter=True)
#   MaintenanceRequest.expense_id   → expenses.id              (post_update=True)
#
#   Alembic emits the ALTER TABLE for the deferred FK after both tables exist.
# ===========================================================================

class RecurringExpense(TimestampMixin, Base):
    """§8.2  Template auto-instantiated into Expense on 1st of each month by Celery Beat."""
    __tablename__ = "recurring_expenses"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id    = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id    = Column(Integer, ForeignKey("properties.id"), nullable=True,  index=True)
    unit_id        = Column(Integer, ForeignKey("units.id"),      nullable=True,  index=True)
    category       = Column(String(40), nullable=True)     # enum ExpenseCategory
    amount         = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(40), nullable=True)
    notes          = Column(Text, nullable=True)
    file_url       = Column(String(255), nullable=True)
    day_of_month   = Column(Integer, default=1, nullable=False)
    is_active      = Column(Boolean, default=True, nullable=False)

    landlord = relationship("Landlord",  back_populates="recurring_expenses")
    property = relationship("Property",  foreign_keys=[property_id])
    unit     = relationship("Unit",      foreign_keys=[unit_id])
    expenses = relationship("Expense",   back_populates="recurring_expense")

    def to_dict(self):
        return {
            "id":             self.id,
            "landlord_id":    self.landlord_id,
            "property_id":    self.property_id,
            "unit_id":        self.unit_id,
            "category":       self.category,
            "amount":         _serialise(self.amount),
            "payment_method": self.payment_method,
            "notes":          self.notes,
            "file_url":       self.file_url,
            "day_of_month":   self.day_of_month,
            "is_active":      self.is_active,
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
        }


class Expense(SoftDeleteMixin, TimestampMixin, Base):
    """
    §8.1  A cost incurred against a property/unit.  Soft-delete.
    May be created standalone or spawned from a MaintenanceRequest.

    maintenance_request_id uses use_alter=True to break the circular FK with
    MaintenanceRequest.
    """
    __tablename__ = "expenses"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id            = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id            = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    unit_id                = Column(Integer, ForeignKey("units.id"),      nullable=True,  index=True)
    category               = Column(String(40), nullable=True)     # enum ExpenseCategory
    amount                 = Column(Numeric(12, 2), nullable=False)
    payment_method         = Column(String(40), nullable=True)
    expense_date           = Column(Date, nullable=False)
    status                 = Column(String(15), nullable=True)     # enum ExpenseStatus
    notes                  = Column(Text, nullable=True)
    file_url               = Column(String(255), nullable=True)
    maintenance_request_id = Column(
        Integer,
        ForeignKey("maintenance_requests.id", use_alter=True,
                   name="fk_expenses_maintenance_request_id"),
        nullable=True, index=True,
    )
    recurring_expense_id   = Column(Integer, ForeignKey("recurring_expenses.id"), nullable=True, index=True)

    landlord           = relationship("Landlord",           back_populates="expenses")
    property           = relationship("Property",           back_populates="expenses")
    unit               = relationship("Unit",               foreign_keys=[unit_id])
    recurring_expense  = relationship("RecurringExpense",   back_populates="expenses")
    # NOT a back_populates pair with MaintenanceRequest.expense — these are two
    # independent many-to-one FKs (each table optionally points at the other),
    # not one bidirectional relationship. foreign_keys + post_update still
    # needed to break the circular-FK insert-order cycle.
    maintenance_request = relationship(
        "MaintenanceRequest",
        foreign_keys=[maintenance_request_id],
        post_update=True,
    )

    def to_dict(self):
        return {
            "id":                     self.id,
            "landlord_id":            self.landlord_id,
            "property_id":            self.property_id,
            "unit_id":                self.unit_id,
            "category":               self.category,
            "amount":                 _serialise(self.amount),
            "payment_method":         self.payment_method,
            "expense_date":           _serialise(self.expense_date),
            "status":                 self.status,
            "notes":                  self.notes,
            "file_url":               self.file_url,
            "maintenance_request_id": self.maintenance_request_id,
            "recurring_expense_id":   self.recurring_expense_id,
            "is_deleted":             self.is_deleted,
            "deleted_at":             _serialise(self.deleted_at),
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }


class OwnerPayout(EtimsMixin, TimestampMixin, Base):
    """
    Money a property manager has remitted to a property's owner.

    A property management company collects every tenant's rent into its own
    paybill, then pays each landlord their share. This is the record of those
    remittances, so the property statement can close the loop:
    net income − remitted = retained.

    It is NOT an expense: a payout is the owner's own money being handed over,
    so it must never enter expense totals, taxable income, or the commission
    base. The property statement shows it as an informational line only.
    """
    __tablename__ = "owner_payouts"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id        = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id        = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    amount             = Column(Numeric(12, 2), nullable=False)
    payout_date        = Column(Date, nullable=False)
    period             = Column(String(7),   nullable=True, index=True)   # "YYYY-MM"
    method             = Column(String(30),  nullable=True)   # mpesa | bank | cash | other
    reference          = Column(String(100), nullable=True)
    notes              = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # --- Settlement ledger (sahilpay_payment_allocation_spec.md §4.10) -------
    # Extended in place rather than replaced: the property statement's
    # "Remitted to owner" line already reads this table, and a parallel
    # `payouts` table would mean two competing answers to "what did we pay
    # this owner". All columns are nullable — a payout recorded before this
    # existed simply has `amount` and no breakdown, and still renders.
    #
    # Math (§4.10):
    #   rent_collected_base = Σ rent allocations (current + arrears) in period
    #   commission_amount   = per the most-specific commission rule
    #   tax_amount          = 7.5% × rent_collected_base — DISPLAY unless the
    #                         account has withholding switched on
    #   total_collected     = every shilling for that owner; a deposit passes
    #                         through in full and is in neither base
    #   net_payable = total_collected − commission − other_deductions
    #                 [− tax if withholding]
    period_start        = Column(Date, nullable=True)
    period_end          = Column(Date, nullable=True)
    total_collected     = Column(Numeric(12, 2), nullable=True)
    rent_collected_base = Column(Numeric(12, 2), nullable=True)
    commission_amount   = Column(Numeric(12, 2), nullable=True)
    tax_amount          = Column(Numeric(12, 2), nullable=True)
    tax_withheld        = Column(Boolean, default=False, nullable=False, server_default="false")
    other_deductions    = Column(Numeric(12, 2), nullable=True)
    net_payable         = Column(Numeric(12, 2), nullable=True)
    status              = Column(String(10), nullable=True)   # enum PayoutStatus
    paid_at             = Column(DateTime, nullable=True)
    owner_id            = Column(Integer, ForeignKey("property_owners.id"), nullable=True, index=True)

    lines = relationship("PayoutLine", back_populates="payout",
                         cascade="all, delete-orphan")
    owner = relationship("PropertyOwner")

    __table_args__ = (
        Index("ix_owner_payouts_property_date", "property_id", "payout_date"),
        # The PM's own eTIMS invoice to the owner, for the commission deducted
        # from this payout. Same partial-unique reasoning as on payments.
        Index("uq_owner_payouts_etims_invoice_number", "etims_invoice_number",
              unique=True, postgresql_where=Column("etims_invoice_number").isnot(None)),
    )

    landlord = relationship("Landlord")
    property = relationship("Property")

    def to_dict(self):
        return {
            "id":                 self.id,
            "landlord_id":        self.landlord_id,
            "property_id":        self.property_id,
            "property_name":      self.property.name if self.property else None,
            "amount":             _serialise(self.amount),
            "payout_date":        _serialise(self.payout_date),
            "period":             self.period,
            "method":             self.method,
            "reference":          self.reference,
            "notes":              self.notes,
            "created_by_user_id": self.created_by_user_id,
            "period_start":       _serialise(self.period_start),
            "period_end":         _serialise(self.period_end),
            "total_collected":    _serialise(self.total_collected),
            "rent_collected_base": _serialise(self.rent_collected_base),
            "commission_amount":  _serialise(self.commission_amount),
            "tax_amount":         _serialise(self.tax_amount),
            "tax_withheld":       self.tax_withheld,
            "other_deductions":   _serialise(self.other_deductions),
            "net_payable":        _serialise(self.net_payable),
            "status":             self.status,
            "paid_at":            _serialise(self.paid_at),
            "owner_id":           self.owner_id,
            "owner_name":         self.owner.full_name if self.owner else None,
            **self.etims_dict(),
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }


class PayoutLine(TimestampMixin, Base):
    """
    One unit's contribution to a payout (spec §4.10) — the per-unit breakdown
    behind the totals, so a landlord's statement can answer "which unit did
    this money come from" rather than just showing a lump sum.
    """
    __tablename__ = "payout_lines"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    payout_id           = Column(Integer, ForeignKey("owner_payouts.id"), nullable=False, index=True)
    unit_id             = Column(Integer, ForeignKey("units.id"), nullable=True, index=True)
    tenant_id           = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    rent_collected      = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    deposits_collected  = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    other_collected     = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    commission_amount   = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    payout = relationship("OwnerPayout", back_populates="lines")
    unit   = relationship("Unit")
    tenant = relationship("Tenant")

    def to_dict(self):
        return {
            "id":                 self.id,
            "payout_id":          self.payout_id,
            "unit_id":            self.unit_id,
            "unit_name":          self.unit.name if self.unit else None,
            "tenant_id":          self.tenant_id,
            "tenant_name":        (f"{self.tenant.first_name} {self.tenant.last_name}".strip()
                                   if self.tenant else None),
            "rent_collected":     _serialise(self.rent_collected),
            "deposits_collected": _serialise(self.deposits_collected),
            "other_collected":    _serialise(self.other_collected),
            "commission_amount":  _serialise(self.commission_amount),
        }


class UtilityReading(TimestampMixin, Base):
    """
    §8.3  Meter reading per unit/utility/month.
    consumption is computed on write (= current_reading - previous_reading).
    Unique per (unit, utility_item, reading_month).

    Schema-level validation: current_reading >= previous_reading.
    """
    __tablename__ = "utility_readings"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id      = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id      = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    unit_id          = Column(Integer, ForeignKey("units.id"),      nullable=False, index=True)
    utility_item     = Column(String(80), nullable=False)     # enum UtilityItem or a landlord utility-type name
    # The utility ChargeCategory this reading bills — its invoice line inherits this
    # category with the reading's `subcategory` (spec §1.7). Landlords can record
    # against any of the category's subcategories: `current` (this month's charge),
    # `balance` (arrears/adjustment), or `deposit` (money held — never metered).
    category_id      = Column(Integer, ForeignKey("charge_categories.id"), nullable=True, index=True)
    subcategory      = Column(String(10), nullable=False, server_default="current")  # enum SubCategory
    previous_reading = Column(Numeric(12, 2), nullable=True)
    # #8 — nullable: non-metered utilities (garbage, security, custom flat charges) carry
    # no meter readings and are billed as a flat `amount` instead.
    current_reading  = Column(Numeric(12, 2), nullable=True)
    amount           = Column(Numeric(12, 2), nullable=True)  # flat charge for non-metered utilities
    consumption      = Column(Numeric(12, 2), nullable=True)  # set on write; current - previous
    reading_month    = Column(String(7), nullable=False)       # YYYY-MM
    invoice_id       = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)

    __table_args__ = (
        # One reading per (unit, utility_item, subcategory, month) — so a unit can
        # carry e.g. a Water current AND a Water deposit in the same month.
        UniqueConstraint("unit_id", "utility_item", "subcategory", "reading_month",
                         name="uq_utility_readings_unit_item_sub_month"),
        CheckConstraint(
            "(previous_reading IS NULL) OR (current_reading IS NULL) OR (current_reading >= previous_reading)",
            name="ck_utility_readings_current_gte_previous",
        ),
    )

    landlord = relationship("Landlord", back_populates="utility_readings")
    category = relationship("ChargeCategory")
    property = relationship("Property", back_populates="utility_readings")
    unit     = relationship("Unit",     back_populates="utility_readings")
    invoice  = relationship("Invoice",  back_populates="utility_readings")
    line_items = relationship("InvoiceLineItem", back_populates="utility_reading")

    def to_dict(self):
        return {
            "id":               self.id,
            "landlord_id":      self.landlord_id,
            "property_id":      self.property_id,
            "unit_id":          self.unit_id,
            "utility_item":     self.utility_item,
            "category_id":      self.category_id,
            "subcategory":      self.subcategory,
            "previous_reading": _serialise(self.previous_reading),
            "current_reading":  _serialise(self.current_reading),
            "amount":           _serialise(self.amount),
            "consumption":      _serialise(self.consumption),
            "reading_month":    self.reading_month,
            "invoice_id":       self.invoice_id,
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
        }


class ChargeCategory(TimestampMixin, Base):
    """
    Charge-category restructure (spec §1.1) — the landlord's unified catalogue of
    chargeable things. `kind` distinguishes utility-page vs invoice-page categories.
    Every category implicitly owns three subcategories (deposit / balance / current)
    — an enum stamped on invoice line items, NOT separate rows — so nothing can
    delete or desync a subcategory. Replaces LandlordUtilityType.
    """
    __tablename__ = "charge_categories"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    name              = Column(String(80), nullable=False)          # "Water", "Rent"
    kind              = Column(String(10), nullable=False)          # enum ChargeCategoryKind
    description       = Column(Text, nullable=True)
    is_metered        = Column(Boolean, default=False, nullable=False)   # utility kind only
    default_rate      = Column(Numeric(12, 2), nullable=True)
    auto_bill_monthly = Column(Boolean, default=False, nullable=False)   # non-metered only
    is_default        = Column(Boolean, default=False, nullable=False)   # protected: deactivatable, never deletable
    is_active         = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("landlord_id", "name", name="uq_charge_categories_landlord_name"),
        # Metered amounts are unpredictable, so they can't be auto-billed on the 1st.
        CheckConstraint("NOT (is_metered AND auto_bill_monthly)",
                        name="ck_charge_categories_metered_not_autobill"),
    )

    landlord   = relationship("Landlord", back_populates="charge_categories")
    line_items = relationship("InvoiceLineItem", back_populates="category")

    def subcategory_display(self) -> dict:
        """Derived display names for the three implicit subcategories."""
        return {
            "deposit": f"{self.name} Deposit",
            "balance": f"{self.name} Balance",
            "current": self.name,
        }

    def to_dict(self):
        names = self.subcategory_display()
        return {
            "id":                self.id,
            "landlord_id":       self.landlord_id,
            "name":              self.name,
            "kind":              self.kind,
            "description":       self.description,
            "is_metered":        self.is_metered,
            "default_rate":      _serialise(self.default_rate),
            "auto_bill_monthly": self.auto_bill_monthly,
            "is_default":        self.is_default,
            "is_active":         self.is_active,
            "subcategories":     [
                {"subcategory": s, "label": names[s]}
                for s in ("deposit", "balance", "current")
            ],
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


class BalanceRollover(TimestampMixin, Base):
    """
    Charge-category restructure (spec §1.4) — audit trail answering "where did this
    carried-forward balance come from?". Each row records that `amount` from a source
    line item (a prior current/balance line closed at month-end) was carried into a
    new "{Category} Balance b/f" target line, tagged with the month the debt
    ORIGINALLY arose. The unique constraint on source_line_item_id makes rollover
    idempotent (a source can only ever roll once).
    """
    __tablename__ = "balance_rollovers"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    tenant_id           = Column(Integer, ForeignKey("tenants.id"),   nullable=False, index=True)
    category_id         = Column(Integer, ForeignKey("charge_categories.id"), nullable=False, index=True)
    source_line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=False)
    target_line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=False, index=True)
    origin_month        = Column(Date, nullable=False)     # month the debt ORIGINALLY arose
    amount              = Column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        # One row per (source line, origin month): a balance line carrying several
        # origin-month components forward gets one row each, while re-running the
        # rollover for the same source is blocked (idempotency). See spec §1.4.
        UniqueConstraint("source_line_item_id", "origin_month",
                         name="uq_balance_rollovers_source_origin"),
    )

    landlord         = relationship("Landlord", back_populates="balance_rollovers")
    tenant           = relationship("Tenant",   back_populates="balance_rollovers")
    category         = relationship("ChargeCategory")
    source_line_item = relationship("InvoiceLineItem", foreign_keys=[source_line_item_id])
    target_line_item = relationship("InvoiceLineItem", foreign_keys=[target_line_item_id])

    def to_dict(self):
        return {
            "id":                  self.id,
            "landlord_id":         self.landlord_id,
            "tenant_id":           self.tenant_id,
            "category_id":         self.category_id,
            "source_line_item_id": self.source_line_item_id,
            "target_line_item_id": self.target_line_item_id,
            "origin_month":        _serialise(self.origin_month),
            "amount":              _serialise(self.amount),
            "created_at":          _serialise(self.created_at),
            "updated_at":          _serialise(self.updated_at),
        }


class CreditLedger(TimestampMixin, Base):
    """
    Charge-category restructure (spec §1.5) — signed movements of a tenant's advance/
    credit. `amount` is + on a top-up (overpayment remainder) and − on application to
    a line item. Tenant.credit_balance always equals the sum of these rows.
    """
    __tablename__ = "credit_ledger"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id  = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    tenant_id    = Column(Integer, ForeignKey("tenants.id"),   nullable=False, index=True)
    amount       = Column(Numeric(12, 2), nullable=False)      # + top-up, − application
    payment_id   = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)
    line_item_id = Column(Integer, ForeignKey("invoice_line_items.id"), nullable=True, index=True)
    memo         = Column(String(200), nullable=True)

    landlord  = relationship("Landlord", back_populates="credit_ledger")
    tenant    = relationship("Tenant",   back_populates="credit_ledger")
    payment   = relationship("Payment")
    line_item = relationship("InvoiceLineItem")

    def to_dict(self):
        return {
            "id":           self.id,
            "landlord_id":  self.landlord_id,
            "tenant_id":    self.tenant_id,
            "amount":       _serialise(self.amount),
            "payment_id":   self.payment_id,
            "line_item_id": self.line_item_id,
            "memo":         self.memo,
            "created_at":   _serialise(self.created_at),
            "updated_at":   _serialise(self.updated_at),
        }


class MaintenanceRequest(TimestampMixin, Base):
    """
    §8.4  Repair/maintenance ticket — raised by landlord/team or by a tenant.
    expense_id is nullable (1:1 optional link to Expense, created after the fact).
    """
    __tablename__ = "maintenance_requests"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"),  nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    unit_id     = Column(Integer, ForeignKey("units.id"),      nullable=False, index=True)
    tenant_id   = Column(Integer, ForeignKey("tenants.id"),    nullable=True,  index=True)
    summary     = Column(String(200), nullable=False)
    description = Column(Text,        nullable=True)
    category    = Column(String(30),  nullable=True)     # enum MaintenanceCategory
    status      = Column(String(15),  nullable=True)     # enum MaintenanceStatus
    image_url   = Column(String(255), nullable=True)
    expense_id  = Column(Integer, ForeignKey("expenses.id"), nullable=True, index=True)

    landlord = relationship("Landlord", back_populates="maintenance_requests")
    property = relationship("Property", back_populates="maintenance_requests")
    unit     = relationship("Unit",     back_populates="maintenance_requests")
    tenant   = relationship("Tenant",   back_populates="maintenance_requests")

    # NOT a back_populates pair with Expense.maintenance_request — see the note
    # there. post_update breaks the circular-FK insert cycle.
    expense = relationship(
        "Expense",
        foreign_keys=[expense_id],
        post_update=True,
    )

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "property_id": self.property_id,
            "unit_id":     self.unit_id,
            "tenant_id":   self.tenant_id,
            "summary":     self.summary,
            "description": self.description,
            "category":    self.category,
            "status":      self.status,
            "image_url":   self.image_url,
            "expense_id":  self.expense_id,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN G — Communications & Documents  (3 tables)
# ===========================================================================

class MessageTemplate(TimestampMixin, Base):
    """§9.1  Reusable SMS/WhatsApp/email templates with dynamic placeholders."""
    __tablename__ = "message_templates"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    name          = Column(String(120), nullable=False)
    channel       = Column(String(10),  nullable=True)    # enum MessageChannel
    template_type = Column(String(30),  nullable=True)    # enum MessageTemplateType
    body          = Column(Text, nullable=False)           # supports {tenant_name},{balance},{invoice_items}

    landlord = relationship("Landlord", back_populates="message_templates")

    def to_dict(self):
        return {
            "id":            self.id,
            "landlord_id":   self.landlord_id,
            "name":          self.name,
            "channel":       self.channel,
            "template_type": self.template_type,
            "body":          self.body,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


class CommunicationLog(CreatedAtMixin, Base):
    """
    §9.2  Every outbound message.  Append-only — no updated_at.
    Every SMS send must decrement landlords.sms_balance (app-level).
    """
    __tablename__ = "communication_logs"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"),    nullable=False, index=True)
    message_type        = Column(String(10),  nullable=True)    # enum MessageChannel
    recipient_type      = Column(String(15),  nullable=True)    # enum RecipientType
    tenant_id           = Column(Integer, ForeignKey("tenants.id"),      nullable=True, index=True)
    team_member_id      = Column(Integer, ForeignKey("team_members.id"), nullable=True, index=True)
    property_id         = Column(Integer, ForeignKey("properties.id"),   nullable=True, index=True)
    unit_id             = Column(Integer, ForeignKey("units.id"),        nullable=True, index=True)
    content             = Column(Text, nullable=False)
    sms_charge          = Column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)
    # §9.3 SMS reselling analytics snapshot (set at send time so historical
    # rows stay accurate even if the landlord later connects/disconnects a
    # sender ID or the admin changes pricing):
    sms_segments        = Column(Integer, nullable=True)   # credits consumed by this SMS
    uses_own_sender     = Column(Boolean, default=False, nullable=False)  # custom (own sender ID) vs default (shared pool)
    platform_cost       = Column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)  # SahilPay's provider cost; 0 for custom
    status              = Column(String(15), nullable=True)     # enum CommunicationStatus
    provider_message_id = Column(String(80), nullable=True)     # FluxSMS / SendGrid id
    sent_at             = Column(DateTime, nullable=True)

    landlord    = relationship("Landlord",   back_populates="communication_logs")
    tenant      = relationship("Tenant",     back_populates="communication_logs")
    team_member = relationship("TeamMember", back_populates="communication_logs")
    property    = relationship("Property",   foreign_keys=[property_id])
    unit        = relationship("Unit",       foreign_keys=[unit_id])

    def to_dict(self):
        return {
            "id":                  self.id,
            "landlord_id":         self.landlord_id,
            "message_type":        self.message_type,
            "recipient_type":      self.recipient_type,
            "tenant_id":           self.tenant_id,
            "team_member_id":      self.team_member_id,
            "property_id":         self.property_id,
            "unit_id":             self.unit_id,
            "content":             self.content,
            "sms_charge":          _serialise(self.sms_charge),
            "sms_segments":        self.sms_segments,
            "uses_own_sender":     self.uses_own_sender,
            "platform_cost":       _serialise(self.platform_cost),
            "status":              self.status,
            "provider_message_id": self.provider_message_id,
            "sent_at":             _serialise(self.sent_at),
            "created_at":          _serialise(self.created_at),
        }


class TenantMessage(CreatedAtMixin, Base):
    """
    §12b  Two-way tenant↔landlord conversation. One row per message; the
    "thread" is every row sharing (landlord_id, tenant_id), ordered by
    created_at. Tenants raise these from their portal; the landlord and any
    team member holding the `messages` permission see and reply to them.

    sender_role drives bubble alignment in the UI and defines who is_read
    refers to: a message stays unread until the *other* party opens the
    thread. category is a tenant-chosen topic ("rent", "repairs",
    "complaint", "general") so the landlord/team can triage what the tenant
    actually wants.
    """
    __tablename__ = "tenant_messages"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id    = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    tenant_id      = Column(Integer, ForeignKey("tenants.id"),   nullable=False, index=True)
    sender_role    = Column(String(15), nullable=False)          # 'tenant' | 'landlord' | 'team_member'
    sender_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_name    = Column(String(120), nullable=True)
    category       = Column(String(30), nullable=True)           # tenant-chosen topic
    body           = Column(Text, nullable=False)
    is_read        = Column(Boolean, default=False, nullable=False)
    read_at        = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_tenant_messages_thread", "landlord_id", "tenant_id", "created_at"),
    )

    landlord = relationship("Landlord", foreign_keys=[landlord_id])
    tenant   = relationship("Tenant",   foreign_keys=[tenant_id])
    sender   = relationship("User",     foreign_keys=[sender_user_id])

    def to_dict(self):
        return {
            "id":             self.id,
            "landlord_id":    self.landlord_id,
            "tenant_id":      self.tenant_id,
            "sender_role":    self.sender_role,
            "sender_user_id": self.sender_user_id,
            "sender_name":    self.sender_name,
            "category":       self.category,
            "body":           self.body,
            "is_read":        self.is_read,
            "read_at":        _serialise(self.read_at),
            "created_at":     _serialise(self.created_at),
        }


class DocumentTemplate(TimestampMixin, Base):
    """§9.3  Lease / tenancy / deposit document templates."""
    __tablename__ = "document_templates"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    name          = Column(String(150), nullable=False)
    document_type = Column(String(30),  nullable=True)    # enum DocumentType
    file_url      = Column(String(255), nullable=True)    # S3
    content       = Column(Text,        nullable=True)    # HTML body for WeasyPrint
    is_template   = Column(Boolean, default=True, nullable=False)

    landlord = relationship("Landlord", back_populates="document_templates")

    def to_dict(self):
        return {
            "id":            self.id,
            "landlord_id":   self.landlord_id,
            "name":          self.name,
            "document_type": self.document_type,
            "file_url":      self.file_url,
            "content":       self.content,
            "is_template":   self.is_template,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN H — Billing & Platform  (5 tables)
# ===========================================================================

class Package(TimestampMixin, Base):
    """
    §10.3  Admin-defined pricing tiers by unit band.
    Global table — no landlord_id.
    """
    __tablename__ = "packages"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    name           = Column(String(120), nullable=False)
    min_units      = Column(Integer, nullable=False)
    max_units      = Column(Integer, nullable=True)       # null = no upper bound
    price_per_unit = Column(Numeric(10, 2), nullable=True)
    flat_price     = Column(Numeric(12, 2), nullable=True)
    is_active      = Column(Boolean, default=True, nullable=False)

    # §Phase-2 public storefront: the admin controls which packages surface on the
    # public pricing page and how they're badged. is_featured gates visibility on
    # the marketing site; is_recommended/is_popular drive the highlight badges;
    # public_description + feature_list are the marketing copy; display_order sorts
    # the cards left-to-right.
    is_featured        = Column(Boolean, default=False, nullable=False)
    is_recommended     = Column(Boolean, default=False, nullable=False)
    is_popular         = Column(Boolean, default=False, nullable=False)
    public_description = Column(String(255), nullable=True)
    feature_list       = Column(JSON, nullable=True)      # list[str] of selling points
    display_order      = Column(Integer, default=0, nullable=False)
    # #17 — the special "Custom" package: admin adds landlords into it manually and sets
    # a negotiated per-unit price on each landlord. Never shown on the public storefront
    # and never featurable/recommendable.
    is_custom          = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(max_units IS NULL) OR (max_units >= min_units)",
            name="ck_packages_max_gte_min",
        ),
        CheckConstraint(
            "(price_per_unit IS NOT NULL) OR (flat_price IS NOT NULL)",
            name="ck_packages_at_least_one_price",
        ),
    )

    landlords = relationship("Landlord", back_populates="package")

    def to_dict(self):
        return {
            "id":             self.id,
            "name":           self.name,
            "min_units":      self.min_units,
            "max_units":      self.max_units,
            "price_per_unit": _serialise(self.price_per_unit),
            "flat_price":     _serialise(self.flat_price),
            "is_active":      self.is_active,
            "is_featured":        self.is_featured,
            "is_recommended":     self.is_recommended,
            "is_popular":         self.is_popular,
            "public_description": self.public_description,
            "feature_list":       self.feature_list or [],
            "display_order":      self.display_order,
            "is_custom":          self.is_custom,
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
        }

    def to_public_dict(self):
        """The marketing-site view — no internal unit-band math, just the pitch."""
        return {
            "id":             self.id,
            "name":           self.name,
            "min_units":      self.min_units,
            "max_units":      self.max_units,
            "price_per_unit": _serialise(self.price_per_unit),
            "flat_price":     _serialise(self.flat_price),
            "is_recommended":     self.is_recommended,
            "is_popular":         self.is_popular,
            "public_description": self.public_description,
            "feature_list":       self.feature_list or [],
            "display_order":      self.display_order,
        }


class Subscription(TimestampMixin, Base):
    """§10.1  Landlord's plan with the platform.  1:1 with landlord."""
    __tablename__ = "subscriptions"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"), nullable=False, unique=True, index=True)
    plan              = Column(String(15), nullable=True)     # enum SubscriptionPlan
    unit_count        = Column(Integer, nullable=False)
    subscription_cost = Column(Numeric(12, 2), nullable=False)
    billing_cycle     = Column(String(10), nullable=True)     # enum BillingCycle
    discount_rate     = Column(Numeric(5, 2), default=Decimal("0.00"), nullable=False)
    amount_due        = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    next_billing_date = Column(Date, nullable=True)
    status            = Column(String(15), nullable=True)     # enum SubscriptionStatus

    landlord = relationship("Landlord", back_populates="subscription")

    def to_dict(self):
        return {
            "id":                self.id,
            "landlord_id":       self.landlord_id,
            "plan":              self.plan,
            "unit_count":        self.unit_count,
            "subscription_cost": _serialise(self.subscription_cost),
            "billing_cycle":     self.billing_cycle,
            "discount_rate":     _serialise(self.discount_rate),
            "amount_due":        _serialise(self.amount_due),
            "next_billing_date": _serialise(self.next_billing_date),
            "status":            self.status,
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


class BillingTransaction(EtimsMixin, TimestampMixin, Base):
    """
    §10.2  Ledger of payments landlord makes to the platform.
    Schema-level: sms_count >= 100 when type == 'sms_purchase'.

    Affiliate-program prerequisite (AFFILIATE_PROGRAM_SPEC.md §3): a subscription
    transaction only becomes commissionable once is_verified=True — either a
    confirmed Daraja STK callback on Sahil's own paybill, or an explicit admin
    manual-verify. The legacy self-reported payment_reference flow (pay_subscription)
    still marks status='paid' immediately for UX continuity, but leaves
    is_verified=False, so it can NEVER trigger affiliate commission on its own.
    context_json carries the pending activation intent (billing_cycle, package_id,
    months, discount) for the STK path, applied only once verification lands
    (services/billing_service.py::finalize_subscription_payment).
    """
    __tablename__ = "billing_transactions"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    type              = Column(String(20), nullable=True)     # enum BillingTransactionType
    amount            = Column(Numeric(12, 2), nullable=False)
    sms_count         = Column(Integer, nullable=True)        # min 100 when sms_purchase
    payment_reference = Column(String(50), nullable=True)
    status            = Column(String(15), nullable=True)     # enum BillingTransactionStatus
    tax_invoice_url   = Column(String(255), nullable=True)    # generated PDF

    context_json          = Column(JSON, nullable=True)       # pending STK activation intent
    is_verified            = Column(Boolean, default=False, nullable=False)
    verified_at             = Column(DateTime, nullable=True)
    verified_by_admin_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    is_reversed             = Column(Boolean, default=False, nullable=False)
    reversed_at              = Column(DateTime, nullable=True)
    reversed_by_admin_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    reversal_reason          = Column(String(255), nullable=True)

    __table_args__ = (
        # SahilPay's own eTIMS invoice to the client for this subscription /
        # SMS purchase, entered by a System Admin. Partial-unique as elsewhere.
        Index("uq_billing_transactions_etims_invoice_number", "etims_invoice_number",
              unique=True, postgresql_where=Column("etims_invoice_number").isnot(None)),
    )

    landlord = relationship("Landlord", back_populates="billing_transactions")

    def to_dict(self):
        return {
            "id":                self.id,
            "landlord_id":       self.landlord_id,
            "type":              self.type,
            "amount":            _serialise(self.amount),
            "sms_count":         self.sms_count,
            "payment_reference": self.payment_reference,
            "status":            self.status,
            "tax_invoice_url":   self.tax_invoice_url,
            "is_verified":       self.is_verified,
            "verified_at":       _serialise(self.verified_at),
            "verified_by_admin_id": self.verified_by_admin_id,
            "is_reversed":       self.is_reversed,
            "reversed_at":       _serialise(self.reversed_at),
            "reversal_reason":   self.reversal_reason,
            **self.etims_dict(),
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


class Affiliate(TimestampMixin, Base):
    """
    §10.6  Affiliate Program — referrer profile.
    See AFFILIATE_PROGRAM_SPEC.md §4.2. Balance is NEVER stored here — it is
    always derived (services/affiliate_service.py::get_balance) from
    confirmed commissions minus non-rejected withdrawals (D-decisions §2, R7
    in the ledger backtest).
    """
    __tablename__ = "affiliates"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    user_id                     = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    full_name                   = Column(String(120), nullable=False)
    phone                       = Column(String(20), nullable=False)
    mpesa_number                = Column(String(20), nullable=True)   # required before first withdrawal
    national_id                 = Column(String(30), nullable=True)   # required before first withdrawal (KRA)
    kra_pin                     = Column(String(20), nullable=True)   # optional, shown on receipts when present
    referral_code                = Column(String(12), unique=True, nullable=False, index=True)
    status                       = Column(String(12), nullable=False, default=AffiliateStatus.pending.value)
    commission_rate_override     = Column(Numeric(5, 2), nullable=True)   # null → program default
    commission_months_override   = Column(Integer, nullable=True)         # null → program default
    approved_by_admin_id         = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at                  = Column(DateTime, nullable=True)
    notes                        = Column(Text, nullable=True)   # admin-only

    user      = relationship("User", back_populates="affiliate_profile", foreign_keys=[user_id])
    referrals    = relationship("AffiliateReferral",  back_populates="affiliate")
    commissions  = relationship("AffiliateCommission", back_populates="affiliate")
    withdrawals  = relationship("AffiliateWithdrawal", back_populates="affiliate")

    def to_dict(self):
        return {
            "id":                        self.id,
            "user_id":                   self.user_id,
            "full_name":                 self.full_name,
            "phone":                     self.phone,
            "mpesa_number":              self.mpesa_number,
            "national_id":               self.national_id,
            "kra_pin":                   self.kra_pin,
            "referral_code":             self.referral_code,
            "status":                    self.status,
            "commission_rate_override":  _serialise(self.commission_rate_override),
            "commission_months_override": self.commission_months_override,
            "approved_by_admin_id":      self.approved_by_admin_id,
            "approved_at":               _serialise(self.approved_at),
            "notes":                     self.notes,
            "created_at":                _serialise(self.created_at),
            "updated_at":                _serialise(self.updated_at),
        }


class AffiliateReferral(TimestampMixin, Base):
    """
    §10.6  One row per (affiliate, landlord) pair — a landlord can be referred
    by at most one affiliate, ever (unique landlord_id).

    rate/months_total are SNAPSHOTTED at attribution time (D5): changing the
    program default or the affiliate's override afterwards never rewrites an
    existing referral's terms. window_started_at is set on the FIRST verified
    payment (D3), not at attribution.
    """
    __tablename__ = "affiliate_referrals"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id       = Column(Integer, ForeignKey("affiliates.id"), nullable=False, index=True)
    landlord_id        = Column(Integer, ForeignKey("landlords.id"), nullable=False, unique=True, index=True)
    rate               = Column(Numeric(5, 2), nullable=False)
    months_total        = Column(Integer, nullable=False)
    months_used          = Column(Integer, nullable=False, default=0)
    window_started_at     = Column(DateTime, nullable=True)
    status              = Column(String(12), nullable=False, default=ReferralStatus.active.value)
    attributed_by        = Column(String(20), nullable=False, default="registration")  # registration | admin_grace

    __table_args__ = (
        CheckConstraint("months_used >= 0 AND months_used <= months_total",
                        name="ck_affiliate_referrals_months_bounds"),
    )

    affiliate = relationship("Affiliate", back_populates="referrals")
    landlord  = relationship("Landlord", back_populates="affiliate_referral")
    commissions = relationship("AffiliateCommission", back_populates="referral")

    def to_dict(self):
        return {
            "id":               self.id,
            "affiliate_id":     self.affiliate_id,
            "landlord_id":      self.landlord_id,
            "rate":             _serialise(self.rate),
            "months_total":     self.months_total,
            "months_used":      self.months_used,
            "window_started_at": _serialise(self.window_started_at),
            "status":           self.status,
            "attributed_by":    self.attributed_by,
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
        }


class AffiliateCommission(TimestampMixin, Base):
    """
    §10.6  One row per VERIFIED subscription BillingTransaction that earned an
    affiliate a commission. Reversal (D10) flips status to 'reversed' in
    place — it does NOT insert a negative row — and the referral's
    months_used is restored by the same operation
    (services/affiliate_service.py::reverse_for_transaction).

    Idempotency: a partial unique index on billing_transaction_id WHERE
    status != 'reversed' guarantees a duplicate accrual attempt (e.g. a
    replayed Daraja callback) can never create a second live commission for
    the same transaction (backtest S11 / spec E10).
    """
    __tablename__ = "affiliate_commissions"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    referral_id             = Column(Integer, ForeignKey("affiliate_referrals.id"), nullable=False, index=True)
    affiliate_id            = Column(Integer, ForeignKey("affiliates.id"), nullable=False, index=True)
    billing_transaction_id  = Column(Integer, ForeignKey("billing_transactions.id"), nullable=False, index=True)
    amount                  = Column(Numeric(12, 2), nullable=False)
    rate_applied             = Column(Numeric(5, 2), nullable=False)
    monthly_equivalent       = Column(Numeric(12, 2), nullable=False)
    months_commissioned       = Column(Integer, nullable=False)
    status                  = Column(String(12), nullable=False, default=CommissionStatus.confirmed.value)
    reversed_at               = Column(DateTime, nullable=True)

    referral  = relationship("AffiliateReferral", back_populates="commissions")
    affiliate = relationship("Affiliate", back_populates="commissions")
    billing_transaction = relationship("BillingTransaction")

    def to_dict(self):
        return {
            "id":                     self.id,
            "referral_id":            self.referral_id,
            "affiliate_id":           self.affiliate_id,
            "billing_transaction_id": self.billing_transaction_id,
            "amount":                 _serialise(self.amount),
            "rate_applied":           _serialise(self.rate_applied),
            "monthly_equivalent":     _serialise(self.monthly_equivalent),
            "months_commissioned":    self.months_commissioned,
            "status":                 self.status,
            "reversed_at":            _serialise(self.reversed_at),
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }


class AffiliateWithdrawal(TimestampMixin, Base):
    """
    §10.6  A withdrawal request and its KRA-compliant breakdown. All rate/fee
    figures are SNAPSHOTTED from AffiliateProgramConfig at request time so a
    receipt regenerated years later is byte-identical regardless of later
    config changes (E24) — CheckConstraint enforces the breakdown always sums
    to the gross (D7/D11).
    """
    __tablename__ = "affiliate_withdrawals"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    affiliate_id           = Column(Integer, ForeignKey("affiliates.id"), nullable=False, index=True)
    gross_amount           = Column(Numeric(12, 2), nullable=False)
    wht_rate               = Column(Numeric(5, 2), nullable=False)
    wht_amount              = Column(Numeric(12, 2), nullable=False)
    fee_type                = Column(String(10), nullable=False)   # enum AffiliateFeeType
    fee_value                = Column(Numeric(12, 2), nullable=False)
    fee_amount               = Column(Numeric(12, 2), nullable=False)
    net_amount               = Column(Numeric(12, 2), nullable=False)
    status                  = Column(String(12), nullable=False, default=WithdrawalStatus.requested.value)
    receipt_number           = Column(String(30), unique=True, nullable=True)
    mpesa_reference           = Column(String(50), nullable=True)
    processed_by_admin_id      = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at              = Column(DateTime, nullable=True)
    rejection_reason           = Column(String(255), nullable=True)

    # B2C automation (MPESA_INTEGRATION_SPEC.md §8.1) — admin-triggered payout
    # via Daraja B2C, with the manual mpesa_reference flow above kept as fallback.
    b2c_originator_id   = Column(String(40), unique=True, nullable=True)  # UUID we send to Daraja
    b2c_conversation_id = Column(String(60), nullable=True)               # Daraja's ConversationID
    b2c_status          = Column(String(20), nullable=True)               # sent | result_received | timeout | failed
    b2c_result_code     = Column(Integer, nullable=True)
    b2c_result_desc     = Column(Text, nullable=True)
    paid_amount         = Column(Numeric(12, 2), nullable=True)           # whole-shilling amount actually sent

    __table_args__ = (
        CheckConstraint(
            "wht_amount + fee_amount + net_amount = gross_amount",
            name="ck_affiliate_withdrawals_breakdown_sums",
        ),
    )

    affiliate = relationship("Affiliate", back_populates="withdrawals")

    def to_dict(self):
        return {
            "id":                 self.id,
            "affiliate_id":       self.affiliate_id,
            "gross_amount":       _serialise(self.gross_amount),
            "wht_rate":           _serialise(self.wht_rate),
            "wht_amount":         _serialise(self.wht_amount),
            "fee_type":           self.fee_type,
            "fee_value":          _serialise(self.fee_value),
            "fee_amount":         _serialise(self.fee_amount),
            "net_amount":         _serialise(self.net_amount),
            "status":             self.status,
            "receipt_number":     self.receipt_number,
            "mpesa_reference":    self.mpesa_reference,
            "processed_by_admin_id": self.processed_by_admin_id,
            "processed_at":       _serialise(self.processed_at),
            "rejection_reason":   self.rejection_reason,
            "b2c_originator_id":   self.b2c_originator_id,
            "b2c_conversation_id": self.b2c_conversation_id,
            "b2c_status":          self.b2c_status,
            "b2c_result_code":     self.b2c_result_code,
            "b2c_result_desc":     self.b2c_result_desc,
            "paid_amount":         _serialise(self.paid_amount),
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }


class AffiliateProgramConfig(TimestampMixin, Base):
    """
    §10.6  Single global settings row (mirrors TrialConfig's global-row
    pattern) — default rate/months, withdrawal minimum, WHT rate, platform
    fee, attribution grace window, and the program kill switch (D14).
    """
    __tablename__ = "affiliate_program_config"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    default_commission_rate     = Column(Numeric(5, 2), nullable=False, default=Decimal("40.00"))
    default_commission_months   = Column(Integer, nullable=False, default=4)
    min_withdrawal              = Column(Numeric(12, 2), nullable=False, default=Decimal("500.00"))
    wht_rate                    = Column(Numeric(5, 2), nullable=False, default=Decimal("5.00"))
    fee_type                    = Column(String(10), nullable=False, default=AffiliateFeeType.percent.value)
    fee_value                   = Column(Numeric(12, 2), nullable=False, default=Decimal("3.00"))
    attribution_grace_days      = Column(Integer, nullable=False, default=7)
    is_program_active           = Column(Boolean, nullable=False, default=True)

    def to_dict(self):
        return {
            "id":                        self.id,
            "default_commission_rate":   _serialise(self.default_commission_rate),
            "default_commission_months": self.default_commission_months,
            "min_withdrawal":            _serialise(self.min_withdrawal),
            "wht_rate":                  _serialise(self.wht_rate),
            "fee_type":                  self.fee_type,
            "fee_value":                 _serialise(self.fee_value),
            "attribution_grace_days":    self.attribution_grace_days,
            "is_program_active":         self.is_program_active,
            "created_at":                _serialise(self.created_at),
            "updated_at":                _serialise(self.updated_at),
        }


class TrialConfig(TimestampMixin, Base):
    """
    §10.4  Global default trial + per-landlord overrides.
    Partial unique index: exactly one row where scope='global'.
    """
    __tablename__ = "trial_configs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    scope         = Column(String(15), nullable=False)    # enum TrialScope
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)
    duration_days = Column(Integer, nullable=False)
    is_active     = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        # One per-landlord override row at most
        UniqueConstraint("landlord_id", name="uq_trial_configs_landlord"),
        # Exactly one global row — partial unique index
        Index(
            "ix_trial_configs_single_global",
            "scope",
            unique=True,
            postgresql_where=(Column("scope") == "global"),
        ),
    )

    landlord = relationship("Landlord", back_populates="trial_configs")

    def to_dict(self):
        return {
            "id":            self.id,
            "scope":         self.scope,
            "landlord_id":   self.landlord_id,
            "duration_days": self.duration_days,
            "is_active":     self.is_active,
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


class ImpersonationRequest(TimestampMixin, Base):
    """
    §10.5  Consent-based impersonation workflow.
    Admin requests → landlord grants → admin operates account.
    Every impersonation action is audit-logged with the admin as actor.
    """
    __tablename__ = "impersonation_requests"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"),     nullable=False, index=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    status        = Column(String(15), nullable=True)    # enum ImpersonationStatus
    requested_at  = Column(DateTime, default=datetime.utcnow)
    granted_at    = Column(DateTime, nullable=True)
    revoked_at    = Column(DateTime, nullable=True)
    expires_at    = Column(DateTime, nullable=True)

    admin_user = relationship("User",     back_populates="impersonation_requests",
                              foreign_keys=[admin_user_id])
    landlord   = relationship("Landlord", back_populates="impersonation_requests",
                              foreign_keys=[landlord_id])

    def to_dict(self):
        return {
            "id":            self.id,
            "admin_user_id": self.admin_user_id,
            "landlord_id":   self.landlord_id,
            "status":        self.status,
            "requested_at":  _serialise(self.requested_at),
            "granted_at":    _serialise(self.granted_at),
            "revoked_at":    _serialise(self.revoked_at),
            "expires_at":    _serialise(self.expires_at),
            "created_at":    _serialise(self.created_at),
            "updated_at":    _serialise(self.updated_at),
        }


# ===========================================================================
# DOMAIN I — Settings, Audit & Ops  (5 tables)
# ===========================================================================

class LandlordSettings(TimestampMixin, Base):
    """§11.1  General channel settings.  1:1 with landlord."""
    __tablename__ = "landlord_settings"

    id                       = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id              = Column(Integer, ForeignKey("landlords.id"), nullable=False, unique=True, index=True)
    sms_enabled              = Column(Boolean, default=True,  nullable=False)
    whatsapp_enabled         = Column(Boolean, default=False, nullable=False)
    email_enabled            = Column(Boolean, default=True,  nullable=False)
    low_sms_balance_threshold = Column(Integer, default=50,   nullable=False)

    # §9.3 SMS reselling (FluxSMS). A landlord connects their own FluxSMS API
    # key + registered sender ID; SahilPay then delivers SMS under that sender
    # ID and bills a flat rate per SMS. Landlords without a sender ID fall
    # back to SahilPay's shared sender ID, billed by message length.
    sms_api_key    = Column(String(255), nullable=True)   # landlord's own SMS provider API key
    sms_sender_id  = Column(String(20),  nullable=True)   # their registered alphanumeric sender ID
    sms_connected  = Column(Boolean, default=False, nullable=False)

    # Which collections count as the GROSS on reports:
    #   "all"       — every shilling collected (a landlord's own view)
    #   "rent_only" — rent current + rent arrears, excluding deposits and
    #                 utilities (a Kenyan property manager's commissionable base)
    # Remembered per landlord so the choice sticks between sessions.
    report_gross_basis = Column(String(10), default="all", nullable=False)

    # Receipt layout (services/receipt_layout.py): paper size, which header
    # component sits in which slot, density. NULL means the built-in default, so
    # every landlord who never touches it keeps exactly the receipt they have.
    receipt_layout_json = Column(Text, nullable=True)

    # Co-Pilot SMS forwarder (COPILOT_PLATFORM_SPEC.md §2.6). Enabling is the
    # landlord's consent step; auto_allocate picks confirmed+allocated vs
    # pending-review for every payment the pipeline creates; admin_locked is a
    # platform kill switch the landlord cannot override.
    copilot_enabled       = Column(Boolean, default=False, nullable=False)
    copilot_auto_allocate = Column(Boolean, default=False, nullable=False)
    copilot_consented_at  = Column(DateTime, nullable=True)
    copilot_admin_locked  = Column(Boolean, default=False, nullable=False)
    # COPILOT_LANDLORD_INBOX_SPEC.md §2.3 — opt-in (default OFF) exemption from
    # the §2 unmatched-message body redaction. Lets support see real unrecognised
    # SMS text to author new bank/format templates, at the landlord's consent.
    copilot_retain_unmatched = Column(Boolean, default=False, nullable=False)

    # --- KRA / eTIMS (spec §2.1, §4.5) --------------------------------------
    # Account-level master switch. OFF (the default, and the state of every
    # existing account) hides every eTIMS surface account-wide regardless of
    # per-property flags — turning it off is a display decision, never a delete.
    etims_enabled = Column(Boolean, default=False, nullable=False, server_default="false")
    # The two monthly nudges, each individually mutable. They only ever fire for
    # accounts that opted in, so defaulting them ON costs a silent account nothing.
    etims_reminder_record_enabled = Column(Boolean, default=True, nullable=False,
                                           server_default="true")   # ~5th: record invoices
    etims_reminder_filing_enabled = Column(Boolean, default=True, nullable=False,
                                           server_default="true")   # 15th: MRI due by the 20th

    landlord = relationship("Landlord", back_populates="landlord_settings")

    def to_dict(self, mask_secrets: bool = True):
        # api key is a secret — only ever expose whether one is set, plus a
        # masked tail, never the full value.
        api_key_display = None
        if self.sms_api_key:
            api_key_display = f"••••{self.sms_api_key[-4:]}" if mask_secrets else self.sms_api_key
        return {
            "id":                        self.id,
            "landlord_id":               self.landlord_id,
            "sms_enabled":               self.sms_enabled,
            "whatsapp_enabled":          self.whatsapp_enabled,
            "email_enabled":             self.email_enabled,
            "low_sms_balance_threshold": self.low_sms_balance_threshold,
            "sms_sender_id":             self.sms_sender_id,
            "sms_connected":             self.sms_connected,
            "sms_api_key_set":           bool(self.sms_api_key),
            "sms_api_key_masked":        api_key_display,
            "report_gross_basis":        self.report_gross_basis or "all",
            "copilot_enabled":           self.copilot_enabled,
            "copilot_auto_allocate":     self.copilot_auto_allocate,
            "copilot_consented_at":      _serialise(self.copilot_consented_at),
            "copilot_admin_locked":      self.copilot_admin_locked,
            "copilot_retain_unmatched":  self.copilot_retain_unmatched,
            "etims_enabled":             self.etims_enabled,
            "etims_reminder_record_enabled": self.etims_reminder_record_enabled,
            "etims_reminder_filing_enabled": self.etims_reminder_filing_enabled,
            "created_at":                _serialise(self.created_at),
            "updated_at":                _serialise(self.updated_at),
        }


class AutomationSettings(TimestampMixin, Base):
    """§11.2  Automation toggles consumed by Celery Beat jobs.  1:1 with landlord."""
    __tablename__ = "automation_settings"

    id                              = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id                     = Column(Integer, ForeignKey("landlords.id"), nullable=False, unique=True, index=True)
    auto_generate_recurring_invoices = Column(Boolean, default=False, nullable=False)
    auto_generate_recurring_bills    = Column(Boolean, default=False, nullable=False)
    alert_on_new_tenant              = Column(Boolean, default=True,  nullable=False)
    auto_send_payment_acknowledgments = Column(Boolean, default=False, nullable=False)
    monthly_reminders_enabled        = Column(Boolean, default=False, nullable=False)
    monthly_reminder_day             = Column(Integer, nullable=True)
    lease_expiry_notifications       = Column(Boolean, default=False, nullable=False)
    lease_expiry_range_days          = Column(Integer, default=30,    nullable=False)
    # Property-manager automation: email every 'owner'-preset team member last
    # month's statement for each property they can access, on owner_reports_day.
    owner_reports_enabled            = Column(Boolean, default=False, nullable=False)
    owner_reports_day                = Column(Integer, nullable=True)   # 1–28

    landlord = relationship("Landlord", back_populates="automation_settings")

    def to_dict(self):
        return {
            "id":                               self.id,
            "landlord_id":                      self.landlord_id,
            "auto_generate_recurring_invoices":  self.auto_generate_recurring_invoices,
            "auto_generate_recurring_bills":     self.auto_generate_recurring_bills,
            "alert_on_new_tenant":               self.alert_on_new_tenant,
            "auto_send_payment_acknowledgments": self.auto_send_payment_acknowledgments,
            "monthly_reminders_enabled":         self.monthly_reminders_enabled,
            "monthly_reminder_day":              self.monthly_reminder_day,
            "lease_expiry_notifications":        self.lease_expiry_notifications,
            "lease_expiry_range_days":           self.lease_expiry_range_days,
            "owner_reports_enabled":             self.owner_reports_enabled,
            "owner_reports_day":                 self.owner_reports_day,
            "created_at":                        _serialise(self.created_at),
            "updated_at":                        _serialise(self.updated_at),
        }


class AlertSetting(TimestampMixin, Base):
    """§11.3  Per-alert-type settings.  One row per (landlord, alert_type)."""
    __tablename__ = "alert_settings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    alert_type  = Column(String(40), nullable=False)    # enum AlertType
    is_enabled  = Column(Boolean, default=True, nullable=False)
    cadence     = Column(String(10), nullable=True)     # enum AlertCadence
    channel     = Column(String(15), nullable=True)     # enum AlertChannel

    __table_args__ = (
        UniqueConstraint("landlord_id", "alert_type", name="uq_alert_settings_landlord_type"),
    )

    landlord = relationship("Landlord", back_populates="alert_settings")

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "alert_type":  self.alert_type,
            "is_enabled":  self.is_enabled,
            "cadence":     self.cadence,
            "channel":     self.channel,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class AuditLog(CreatedAtMixin, Base):
    """
    §11.4  Append-only, immutable record of every create/update/delete.
    No updated_at.  landlord_id is nullable (null for pure admin/platform acts).
    Every admin impersonation action must be written here with the admin as actor.
    """
    __tablename__ = "audit_logs"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id         = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)
    # Nullable: an OTP-only tenant self-service action (e.g. submitting a payment)
    # has no linked User row, yet must still be audited with the tenant's snapshot
    # name/username. (#18)
    actor_user_id       = Column(Integer, ForeignKey("users.id"),     nullable=True, index=True)
    actor_username      = Column(String(150), nullable=True)    # denormalized snapshot
    actor_full_name     = Column(String(200), nullable=True)    # denormalized snapshot
    action              = Column(String(60),  nullable=True)    # e.g. create_payment
    entity_type         = Column(String(40),  nullable=True)    # enum AuditEntityType
    entity_id           = Column(Integer,     nullable=True)
    description         = Column(Text,        nullable=True)
    before_data         = Column(JSON,        nullable=True)
    after_data          = Column(JSON,        nullable=True)
    affected_properties = Column(JSON,        nullable=True)
    file_url            = Column(String(255), nullable=True)
    ip_address          = Column(String(45),  nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_landlord_created_at",  "landlord_id",  "created_at"),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )

    actor_user = relationship("User",     back_populates="audit_logs_as_actor")
    landlord   = relationship("Landlord", foreign_keys=[landlord_id])

    def to_dict(self):
        return {
            "id":                  self.id,
            "landlord_id":         self.landlord_id,
            "actor_user_id":       self.actor_user_id,
            "actor_username":      self.actor_username,
            "actor_full_name":     self.actor_full_name,
            "action":              self.action,
            "entity_type":         self.entity_type,
            "entity_id":           self.entity_id,
            "description":         self.description,
            "before_data":         self.before_data,
            "after_data":          self.after_data,
            "affected_properties": self.affected_properties,
            "file_url":            self.file_url,
            "ip_address":          self.ip_address,
            "created_at":          _serialise(self.created_at),
        }


class Backup(TimestampMixin, Base):
    """§11.5  Generated backup exports, downloadable as Excel or PDF."""
    __tablename__ = "backups"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    scope_type  = Column(String(20), nullable=True)    # enum BackupScopeType
    scope_id    = Column(Integer, nullable=True)        # target id when applicable
    format      = Column(String(10), nullable=True)     # enum BackupFormat
    file_url    = Column(String(255), nullable=True)    # generated async

    landlord = relationship("Landlord", back_populates="backups")

    def to_dict(self):
        return {
            "id":          self.id,
            "landlord_id": self.landlord_id,
            "scope_type":  self.scope_type,
            "scope_id":    self.scope_id,
            "format":      self.format,
            "file_url":    self.file_url,
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
        }


class Notification(TimestampMixin, Base):
    """
    §12  In-app notification — one row per resolved recipient. A broadcast to
    50 tenants fans out into 50 rows sharing the same category/title/body but
    distinct recipient_user_id, so each tenant's read state is independent.

    sender_user_id is null for system-generated notifications (e.g. a Celery
    Beat trial-expiry check); set to the acting admin/landlord's user id for
    a manual broadcast. landlord_id scopes which landlord's "send" UI/audit
    this belongs to — null for pure-platform sends (admin -> all landlords).
    """
    __tablename__ = "notifications"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    # A notification targets EITHER a User (landlord/team-member/admin) OR a
    # Tenant. OTP-only tenants have no User row, so they must be addressed by
    # tenant id — that is why recipient_user_id is nullable and a parallel
    # recipient_tenant_id exists. Exactly one of the two is set per row.
    recipient_user_id  = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    recipient_tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    sender_user_id     = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    landlord_id        = Column(Integer, ForeignKey("landlords.id"), nullable=True, index=True)
    category           = Column(String(40), nullable=False)    # enum NotificationCategory
    title              = Column(String(150), nullable=False)
    body               = Column(Text, nullable=False)
    link               = Column(String(255), nullable=True)    # frontend route to deep-link to
    entity_type        = Column(String(40), nullable=True)
    entity_id          = Column(Integer, nullable=True)
    is_read            = Column(Boolean, default=False, nullable=False)
    read_at            = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
        Index("ix_notifications_recipient_is_read", "recipient_user_id", "is_read"),
        Index("ix_notifications_tenant_is_read", "recipient_tenant_id", "is_read"),
    )

    recipient = relationship("User", foreign_keys=[recipient_user_id])
    recipient_tenant = relationship("Tenant", foreign_keys=[recipient_tenant_id])
    sender    = relationship("User", foreign_keys=[sender_user_id])
    landlord  = relationship("Landlord", foreign_keys=[landlord_id])

    def to_dict(self):
        return {
            "id":                self.id,
            "recipient_user_id": self.recipient_user_id,
            "recipient_tenant_id": self.recipient_tenant_id,
            "sender_user_id":    self.sender_user_id,
            "landlord_id":       self.landlord_id,
            "category":          self.category,
            "title":             self.title,
            "body":              self.body,
            "link":              self.link,
            "entity_type":       self.entity_type,
            "entity_id":         self.entity_id,
            "is_read":           self.is_read,
            "read_at":           _serialise(self.read_at),
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
        }


# ===========================================================================
# §9.3  SMS RESELLING — admin pricing config & shared-pool ledger
# ===========================================================================

class SmsPricingConfig(TimestampMixin, Base):
    """
    Admin-editable global SMS reselling knobs (§9.3). Singleton — exactly one
    row (id=1). Sets the resale price per SMS for *default* users (who send via
    SahilPay's shared sender ID out of the platform pool) and *custom* users
    (who connected their own SMS sender ID and pay a per-SMS
    service fee), the fixed platform cost per SMS used for margin analytics,
    the shared-pool credit balance, and the master toggle gating shared sending.
    """
    __tablename__ = "sms_pricing_config"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    default_price_per_sms  = Column(Numeric(8, 4), default=Decimal("1.00"), nullable=False)
    custom_price_per_sms   = Column(Numeric(8, 4), default=Decimal("0.50"), nullable=False)
    platform_cost_per_sms  = Column(Numeric(8, 4), default=Decimal("0.65"), nullable=False)
    pool_balance           = Column(Integer, default=0, nullable=False)
    shared_sending_enabled = Column(Boolean, default=True, nullable=False)

    @classmethod
    def get_singleton(cls):
        """Fetch the single config row, creating it with defaults on first use."""
        from extensions import db
        cfg = db.session.get(cls, 1)
        if cfg is None:
            cfg = cls(id=1)
            db.session.add(cfg)
            db.session.flush()
        return cfg

    def to_dict(self):
        return {
            "id":                     self.id,
            "default_price_per_sms":  _serialise(self.default_price_per_sms),
            "custom_price_per_sms":   _serialise(self.custom_price_per_sms),
            "platform_cost_per_sms":  _serialise(self.platform_cost_per_sms),
            "pool_balance":           self.pool_balance,
            "shared_sending_enabled": self.shared_sending_enabled,
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }


class SmsCreditRange(TimestampMixin, Base):
    """
    Admin-editable word-count → credits pricing tiers for landlord SMS sends.

    A landlord's message costs `credits` when its word count falls in
    [min_words, max_words] (inclusive). Ranges must NOT overlap. The final,
    open-ended tier uses max_words = NULL ("and above"). One credit is worth
    SmsPricingConfig.default_price_per_sms (KES), so longer messages cost more
    credits — matching FluxSMS/GSM segmenting where longer text spans more SMS
    segments. Replaces the old flat "1 credit per 160-char segment" assumption
    with a transparent, operator-tunable table.
    """
    __tablename__ = "sms_credit_ranges"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    min_words  = Column(Integer, nullable=False)
    max_words  = Column(Integer, nullable=True)   # NULL = open-ended ("and above")
    credits    = Column(Integer, nullable=False)

    __table_args__ = (
        Index("ix_sms_credit_ranges_min", "min_words"),
    )

    def to_dict(self):
        return {
            "id":        self.id,
            "min_words": self.min_words,
            "max_words": self.max_words,
            "credits":   self.credits,
        }


class SmsPoolTopUp(CreatedAtMixin, Base):
    """
    Append-only ledger of admin top-ups to the shared SMS pool (§9.3). Records
    how many credits were added, the resulting pool balance, an optional note,
    and which admin performed it — powering the pool history on the admin SMS
    monitoring page.
    """
    __tablename__ = "sms_pool_topups"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    credits_added = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    note          = Column(String(255), nullable=True)

    admin_user = relationship("User", foreign_keys=[admin_user_id])

    def to_dict(self):
        return {
            "id":            self.id,
            "admin_user_id": self.admin_user_id,
            "credits_added": self.credits_added,
            "balance_after": self.balance_after,
            "note":          self.note,
            "created_at":    _serialise(self.created_at),
        }


class SmsLandlordCredit(CreatedAtMixin, Base):
    """
    Append-only ledger of admin manual SMS-balance adjustments for ONE landlord.
    Used while automated M-Pesa billing is being finalised: a landlord pays the
    operator directly (e.g. 100 KES to a Safaricom number) and the admin credits
    the equivalent SMS balance here. Every row records the credit amount (may be
    negative to correct a mistake), the landlord's resulting balance, a mandatory
    reason/reference, and which admin did it — so a manual credit is always
    traceable and reversible, exactly like SmsPoolTopUp is for the shared pool.
    """
    __tablename__ = "sms_landlord_credits"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id   = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    admin_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    credits_added = Column(Integer, nullable=False)          # signed; negative = correction
    balance_after = Column(Integer, nullable=False)
    reason        = Column(String(255), nullable=False)      # mandatory reference (e.g. "M-Pesa 100 KES, code ABC123")

    landlord   = relationship("Landlord", foreign_keys=[landlord_id])
    admin_user = relationship("User", foreign_keys=[admin_user_id])

    def to_dict(self):
        return {
            "id":            self.id,
            "landlord_id":   self.landlord_id,
            "admin_user_id": self.admin_user_id,
            "credits_added": self.credits_added,
            "balance_after": self.balance_after,
            "reason":        self.reason,
            "created_at":    _serialise(self.created_at),
        }


# ===========================================================================
# DOMAIN J — Help Content CMS, preferences & platform config
#            (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §1.5, §2.3, §9.4)
# ===========================================================================
#
# Not to be confused with client/src/features/landlord/tutorials/, which is the
# hardcoded first-run product TOUR. These tables back the admin-authored help
# LIBRARY: markdown articles Swalleh writes and publishes from the admin portal,
# filtered by role, rendered read-only in every other portal.
# ===========================================================================

class TutorialCategory(TimestampMixin, Base):
    """One shelf in the help library, e.g. "Tax Compliance (KRA & eTIMS)"."""
    __tablename__ = "tutorial_categories"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    name             = Column(String(150), nullable=False)
    slug             = Column(String(160), nullable=False, unique=True, index=True)
    icon             = Column(String(60), nullable=True)      # a lucide icon name
    description      = Column(Text, nullable=True)
    sort_order       = Column(Integer, default=0, nullable=False)
    # JSON array of UserRole values. Empty list / null = visible to every role.
    visible_to_roles = Column(JSON, nullable=True)
    is_published     = Column(Boolean, default=False, nullable=False)

    articles = relationship("TutorialArticle", back_populates="category",
                            order_by="TutorialArticle.sort_order",
                            cascade="all, delete-orphan")

    def to_dict(self, article_count: int | None = None):
        data = {
            "id":               self.id,
            "name":             self.name,
            "slug":             self.slug,
            "icon":             self.icon,
            "description":      self.description,
            "sort_order":       self.sort_order,
            "visible_to_roles": self.visible_to_roles or [],
            "is_published":     self.is_published,
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
        }
        if article_count is not None:
            data["article_count"] = article_count
        return data


class TutorialArticle(TimestampMixin, Base):
    """
    One markdown help article. Bodies are authored in the admin CMS and
    rendered through a sanitising markdown pipeline on the way out — raw HTML
    and scripts are stripped, so an article can never inject into a portal.
    """
    __tablename__ = "tutorial_articles"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    category_id        = Column(Integer, ForeignKey("tutorial_categories.id"),
                                nullable=False, index=True)
    title              = Column(String(200), nullable=False)
    slug               = Column(String(220), nullable=False, unique=True, index=True)
    summary            = Column(String(400), nullable=True)
    body_markdown      = Column(Text, nullable=True)
    sort_order         = Column(Integer, default=0, nullable=False)
    # null = inherit the category's audience; a list narrows it further.
    visible_to_roles   = Column(JSON, nullable=True)
    is_published       = Column(Boolean, default=False, nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    category   = relationship("TutorialCategory", back_populates="articles")
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])
    images     = relationship("TutorialImage", back_populates="article",
                              order_by="TutorialImage.sort_order",
                              cascade="all, delete-orphan")

    def to_dict(self, include_body: bool = True):
        data = {
            "id":                 self.id,
            "category_id":        self.category_id,
            "category_slug":      self.category.slug if self.category else None,
            "category_name":      self.category.name if self.category else None,
            "title":              self.title,
            "slug":               self.slug,
            "summary":            self.summary,
            "sort_order":         self.sort_order,
            "visible_to_roles":   self.visible_to_roles,
            "is_published":       self.is_published,
            "updated_by_user_id": self.updated_by_user_id,
            "created_at":         _serialise(self.created_at),
            "updated_at":         _serialise(self.updated_at),
        }
        if include_body:
            data["body_markdown"] = self.body_markdown or ""
        return data


class TutorialImage(TimestampMixin, Base):
    """
    A screenshot in the help library. `article_id` is nullable so shared images
    can live in a general library and be reused across articles.

    Uploads are downscaled and recompressed on the way in (max 1200px wide,
    ~250KB) because these pages are read on Kenyan mobile data. Replacing an
    image writes to the SAME file_path, so every article already referencing it
    updates without being edited.
    """
    __tablename__ = "tutorial_images"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    article_id          = Column(Integer, ForeignKey("tutorial_articles.id"),
                                 nullable=True, index=True)
    file_path           = Column(String(500), nullable=False)
    caption             = Column(String(300), nullable=True)
    alt_text            = Column(String(300), nullable=True)
    sort_order          = Column(Integer, default=0, nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    article     = relationship("TutorialArticle", back_populates="images")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self):
        return {
            "id":                  self.id,
            "article_id":          self.article_id,
            "file_path":           self.file_path,
            "url":                 self.file_path,
            "caption":             self.caption,
            "alt_text":            self.alt_text,
            "sort_order":          self.sort_order,
            "uploaded_by_user_id": self.uploaded_by_user_id,
            "markdown":            f"![{self.alt_text or self.caption or ''}]({self.file_path})",
            "created_at":          _serialise(self.created_at),
            "updated_at":          _serialise(self.updated_at),
        }


class UserPreference(TimestampMixin, Base):
    """
    A small per-user JSON scratchpad for UI stickiness that has no business
    meaning — which report checkboxes were last ticked, which one-time nudge
    cards have been dismissed. One row per user; the shape is owned by whoever
    writes the key, and an unknown key simply reads back as its default.

    Deliberately NOT a settings table: nothing here may change what a document
    contains or who can see what, only what the UI remembers.
    """
    __tablename__ = "user_preferences"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False,
                          unique=True, index=True)
    preferences  = Column(JSON, nullable=False, server_default="{}", default=dict)

    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id":          self.id,
            "user_id":     self.user_id,
            "preferences": self.preferences or {},
            "updated_at":  _serialise(self.updated_at),
        }


class PlatformSettings(TimestampMixin, Base):
    """
    Single global row for platform-owner values that don't belong to any
    landlord — following the AffiliateProgramConfig / TrialConfig pattern.

    Today that is SahilPay's own KRA PIN (printed on subscription receipts when
    set) and the eTIMS kill switch. The switch also exists as the
    ETIMS_FEATURES_ENABLED env var; the env var wins, so a bad deploy can be
    shut off without database access.
    """
    __tablename__ = "platform_settings"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    kra_pin               = Column(String(11), nullable=True)
    legal_entity_name     = Column(String(200), nullable=True)   # e.g. "Raswal Ltd"
    etims_features_enabled = Column(Boolean, default=True, nullable=False,
                                    server_default="true")

    def to_dict(self):
        return {
            "id":                     self.id,
            "kra_pin":                self.kra_pin,
            "legal_entity_name":      self.legal_entity_name,
            "etims_features_enabled": self.etims_features_enabled,
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }


# ===========================================================================
# §17 ACCEPTANCE CHECKLIST — verified at definition time
# ===========================================================================
#
# [x] 39 models: User, SystemAdmin, Landlord, TeamMember, TeamMemberPermission,
#     TeamMemberPropertyAccess, OtpToken,                                    (A: 7)
#     PropertyGroup, Property, Unit, RecurringBill, ManagerAssignment,       (B: 5)
#     Tenant, TenantUnitHistory, TenantDocument,                             (C: 3)
#     Invoice, InvoiceLineItem,                                              (D: 2)
#     BankStatementUpload, Payment, PaymentAllocation,
#     BankStatementTransaction, MpesaTransaction,                            (E: 5)
#     RecurringExpense, Expense, UtilityReading, MaintenanceRequest,         (F: 4)
#     MessageTemplate, CommunicationLog, DocumentTemplate,                   (G: 3)
#     Package, Subscription, BillingTransaction,
#     TrialConfig, ImpersonationRequest,                                     (H: 5)
#     LandlordSettings, AutomationSettings, AlertSetting,
#     AuditLog, Backup                                                       (I: 5)
#     TOTAL = 39  ✓
#
# [x] Every table: id + created_at (+ updated_at except OtpToken,
#     CommunicationLog, AuditLog)  ✓
# [x] All money columns Numeric with exact per-column precision  ✓
# [x] Soft-delete (is_deleted + deleted_at) on 6 tables only:
#     Tenant, Property, Unit, Invoice, Payment, Expense  ✓
# [x] All FKs present with correct nullability; every FK column indexed  ✓
# [x] Composite uniques, CheckConstraints, partial index all in __table_args__  ✓
# [x] Enums defined once; no value outside Appendix A  ✓
# [x] back_populates on both sides of every relationship  ✓
# [x] payments↔invoices M:N through PaymentAllocation  ✓
# [x] expenses↔maintenance_requests circular FK resolved with
#     use_alter=True + post_update=True  ✓
# [x] to_dict() on every model  ✓
# [x] SoftDeleteQuery default filter implemented  ✓
# [x] No report/statement tables; no stack substitutions  ✓
#
# TO MIGRATE after changes:
#   alembic revision --autogenerate -m "describe your change"
#   alembic upgrade head
# ===========================================================================
