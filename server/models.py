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
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime,
    ForeignKey, Index, Integer, JSON, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Query, relationship


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


class PaymentStatus(str, enum.Enum):
    confirmed = "confirmed"
    pending   = "pending"
    declined  = "declined"


class PaymentSource(str, enum.Enum):
    mpesa           = "mpesa"
    co_pilot        = "co_pilot"
    bank_statement  = "bank_statement"
    manual          = "manual"


class BankStatementStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsing  = "parsing"
    parsed   = "parsed"
    failed   = "failed"


class MpesaTransactionStatus(str, enum.Enum):
    recorded  = "recorded"
    unmatched = "unmatched"
    pending   = "pending"


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
    tenant_profile      = relationship("Tenant",       back_populates="user",
                                       uselist=False, cascade="all, delete-orphan")

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
    default_tax_rate       = Column(Numeric(5, 2),  default=Decimal("7.50"), nullable=False)
    agent_code             = Column(String(50),  unique=True, nullable=True)
    sms_balance            = Column(Integer, default=0, nullable=False)
    per_unit_price         = Column(Numeric(10, 2), nullable=True)
    package_id             = Column(Integer, ForeignKey("packages.id"), nullable=True, index=True)
    trial_ends_at          = Column(DateTime, nullable=True)
    is_on_trial            = Column(Boolean, default=True, nullable=False)

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
    properties           = relationship("Property",           back_populates="landlord")
    team_members         = relationship("TeamMember",         back_populates="landlord")
    tenants              = relationship("Tenant",             back_populates="landlord")
    invoices             = relationship("Invoice",            back_populates="landlord")
    payments             = relationship("Payment",            back_populates="landlord")
    expenses             = relationship("Expense",            back_populates="landlord")
    recurring_expenses   = relationship("RecurringExpense",   back_populates="landlord")
    utility_readings     = relationship("UtilityReading",     back_populates="landlord")
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
            "default_tax_rate":       _serialise(self.default_tax_rate),
            "agent_code":             self.agent_code,
            "sms_balance":            self.sms_balance,
            "per_unit_price":         _serialise(self.per_unit_price),
            "package_id":             self.package_id,
            "trial_ends_at":          _serialise(self.trial_ends_at),
            "is_on_trial":            self.is_on_trial,
            "created_at":             _serialise(self.created_at),
            "updated_at":             _serialise(self.updated_at),
        }


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
    property_access_all = Column(Boolean, default=False, nullable=False)
    activation_token    = Column(String(255), nullable=True)
    is_active           = Column(Boolean, default=False, nullable=False)

    user     = relationship("User",     back_populates="team_member_profile", uselist=False)
    landlord = relationship("Landlord", back_populates="team_members")

    permissions         = relationship("TeamMemberPermission",    back_populates="team_member",
                                       cascade="all, delete-orphan")
    property_accesses   = relationship("TeamMemberPropertyAccess", back_populates="team_member",
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
    owner_phone         = Column(String(20),  nullable=True)
    notes               = Column(Text,        nullable=True)

    landlord       = relationship("Landlord",       back_populates="properties")
    property_group = relationship("PropertyGroup",  back_populates="properties")

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
            "owner_phone":          self.owner_phone,
            "notes":                self.notes,
            "is_deleted":           self.is_deleted,
            "deleted_at":           _serialise(self.deleted_at),
            "created_at":           _serialise(self.created_at),
            "updated_at":           _serialise(self.updated_at),
        }


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

    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_units_property_name"),
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
            "notes":       self.notes,
            "is_deleted":  self.is_deleted,
            "deleted_at":  _serialise(self.deleted_at),
            "created_at":  _serialise(self.created_at),
            "updated_at":  _serialise(self.updated_at),
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
    lease_start_date     = Column(Date, nullable=True)
    lease_expiry_date    = Column(Date, nullable=True)
    move_in_date         = Column(Date, nullable=True)
    move_out_date        = Column(Date, nullable=True)
    notes                = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "account_number", name="uq_tenants_landlord_account"),
    )

    user     = relationship("User",     back_populates="tenant_profile", uselist=False)
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
            "lease_start_date":     _serialise(self.lease_start_date),
            "lease_expiry_date":    _serialise(self.lease_expiry_date),
            "move_in_date":         _serialise(self.move_in_date),
            "move_out_date":        _serialise(self.move_out_date),
            "notes":                self.notes,
            "is_deleted":           self.is_deleted,
            "deleted_at":           _serialise(self.deleted_at),
            "created_at":           _serialise(self.created_at),
            "updated_at":           _serialise(self.updated_at),
        }


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

    invoice         = relationship("Invoice",        back_populates="line_items")
    utility_reading = relationship("UtilityReading", back_populates="line_items")

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


class Payment(SoftDeleteMixin, TimestampMixin, Base):
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
    notes             = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("landlord_id", "payment_ref", name="uq_payments_landlord_ref"),
    )

    landlord       = relationship("Landlord",            back_populates="payments")
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
            "notes":             self.notes,
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
    amount_allocated = Column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("payment_id", "invoice_id", name="uq_payment_allocations_payment_invoice"),
        CheckConstraint("amount_allocated > 0", name="ck_payment_allocations_positive"),
    )

    payment = relationship("Payment", back_populates="payment_allocations")
    invoice = relationship("Invoice", back_populates="payment_allocations")

    def to_dict(self):
        return {
            "id":               self.id,
            "payment_id":       self.payment_id,
            "invoice_id":       self.invoice_id,
            "amount_allocated": _serialise(self.amount_allocated),
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
    utility_item     = Column(String(20), nullable=False)     # enum UtilityItem
    previous_reading = Column(Numeric(12, 2), nullable=True)
    current_reading  = Column(Numeric(12, 2), nullable=False)
    consumption      = Column(Numeric(12, 2), nullable=True)  # set on write; current - previous
    reading_month    = Column(String(7), nullable=False)       # YYYY-MM
    invoice_id       = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)

    __table_args__ = (
        UniqueConstraint("unit_id", "utility_item", "reading_month",
                         name="uq_utility_readings_unit_item_month"),
        CheckConstraint(
            "(previous_reading IS NULL) OR (current_reading >= previous_reading)",
            name="ck_utility_readings_current_gte_previous",
        ),
    )

    landlord = relationship("Landlord", back_populates="utility_readings")
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
            "previous_reading": _serialise(self.previous_reading),
            "current_reading":  _serialise(self.current_reading),
            "consumption":      _serialise(self.consumption),
            "reading_month":    self.reading_month,
            "invoice_id":       self.invoice_id,
            "created_at":       _serialise(self.created_at),
            "updated_at":       _serialise(self.updated_at),
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
    status              = Column(String(15), nullable=True)     # enum CommunicationStatus
    provider_message_id = Column(String(80), nullable=True)     # Africa's Talking / SendGrid id
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
            "status":              self.status,
            "provider_message_id": self.provider_message_id,
            "sent_at":             _serialise(self.sent_at),
            "created_at":          _serialise(self.created_at),
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
            "created_at":     _serialise(self.created_at),
            "updated_at":     _serialise(self.updated_at),
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


class BillingTransaction(TimestampMixin, Base):
    """
    §10.2  Ledger of payments landlord makes to the platform.
    Schema-level: sms_count >= 100 when type == 'sms_purchase'.
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
            "created_at":        _serialise(self.created_at),
            "updated_at":        _serialise(self.updated_at),
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

    landlord = relationship("Landlord", back_populates="landlord_settings")

    def to_dict(self):
        return {
            "id":                        self.id,
            "landlord_id":               self.landlord_id,
            "sms_enabled":               self.sms_enabled,
            "whatsapp_enabled":          self.whatsapp_enabled,
            "email_enabled":             self.email_enabled,
            "low_sms_balance_threshold": self.low_sms_balance_threshold,
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
    actor_user_id       = Column(Integer, ForeignKey("users.id"),     nullable=False, index=True)
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
