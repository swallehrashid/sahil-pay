// FE mirror of the backend's Appendix A enum vocabularies — EXACT values only.
// Never introduce a status/category outside these sets; this file is the guardian
// against vocabulary drift between client and server.

export const USER_ROLES = {
  SYSTEM_ADMIN: "system_admin",
  LANDLORD: "landlord",
  PROPERTY_MANAGER: "property_manager",
  TEAM_MEMBER: "team_member",
  TENANT: "tenant",
  AFFILIATE: "affiliate",
};

export const ACCOUNT_TYPES = ["gated_community", "property_management", "landlord"];
export const MPESA_TYPES = ["paybill", "till"];
export const TEAM_MEMBER_ROLES = ["editor", "viewer"];

export const PERMISSION_MODULES = [
  "payments",
  "invoices",
  "utilities",
  "unit_utilities",
  "tenants",
  "units",
  "properties",
  "messages",
  "expenses",
  "maintenance",
  "reports",
  "groups",
];

export const MANAGER_SCOPE_TYPES = ["unit", "property", "group"];

export const INVOICE_STATUSES = ["draft", "void", "open", "partial", "paid"];
export const INVOICE_TYPES = ["rent", "utility", "penalty", "custom", "recurring", "deposit"];

export const PAYMENT_STATUSES = ["confirmed", "pending", "declined"];
export const PAYMENT_SOURCES = ["mpesa", "co_pilot", "bank_statement", "manual"];
export const PAYMENT_SOURCE_LABELS = {
  mpesa: "M-Pesa",
  co_pilot: "Co-pilot",
  bank_statement: "Bank Statement",
  manual: "Manual",
  credit: "Credit",
};

export const EXPENSE_STATUSES = ["confirmed", "pending"];
export const EXPENSE_CATEGORIES = [
  "garbage",
  "maintenance",
  "security",
  "electricity",
  "water",
  "cleaning",
  "internet",
  "other",
];

// Selectable charge types for an invoice line item. "other" reveals a free-text
// field so anything not listed can still be billed.
export const INVOICE_LINE_ITEMS = [
  "rent",
  "water",
  "electricity",
  "garbage",
  "security",
  "service charge",
  "deposit",
  "penalty",
  "other",
];

// Channels a payment receipt can be delivered on. `enabled:false` ones are shown
// but not selectable until the integration is wired (e.g. WhatsApp Business API).
export const RECEIPT_CHANNELS = [
  { value: "email", label: "Email", enabled: true },
  { value: "in_app", label: "In-app notification", enabled: true },
  { value: "sms", label: "SMS", enabled: true },
  { value: "whatsapp", label: "WhatsApp (coming soon)", enabled: false },
];

export const MAINTENANCE_STATUSES = ["open", "in_progress", "closed"];
export const MAINTENANCE_CATEGORIES = [
  "electrical",
  "plumbing",
  "roofing",
  "pest_control",
  "roof_repair",
  "locksmith",
  "pool",
  "garage",
  "heating_cooling",
  "handiwork",
  "tiles",
  "washroom",
  "painting",
  "security",
  "other",
];

// Delivery channels a landlord may choose. `in_app` lands in the recipient's
// portal — free, instant, and it survives a lost handset, which matters when
// SMS is billed per segment.
export const MESSAGE_CHANNELS = ["sms", "whatsapp", "email", "in_app"];

// Human labels — "in_app" is not something to show a landlord.
export const MESSAGE_CHANNEL_LABELS = {
  sms: "SMS",
  whatsapp: "WhatsApp",
  email: "Email",
  in_app: "In the app",
};
export const MESSAGE_TEMPLATE_TYPES = ["balance_reminder", "invoice_reminder", "custom"];
export const RECIPIENT_TYPES = ["tenant", "team_member"];
export const COMMUNICATION_STATUSES = ["pending", "delivered", "failed"];

export const DOCUMENT_TYPES = ["lease", "tenancy_agreement", "deposit", "other"];

export const SUBSCRIPTION_PLANS = ["monthly", "quarterly", "annual"];
export const BILLING_CYCLES = ["monthly", "yearly"];
export const SUBSCRIPTION_STATUSES = ["trial", "active", "past_due", "suspended"];
export const BILLING_TRANSACTION_TYPES = ["subscription", "sms_purchase"];
export const BILLING_TRANSACTION_STATUSES = ["pending", "paid", "failed"];

export const TRIAL_SCOPES = ["global", "per_landlord"];
export const IMPERSONATION_STATUSES = ["pending", "granted", "revoked", "expired"];
export const BANK_STATEMENT_STATUSES = ["uploaded", "parsing", "parsed", "failed"];
export const MPESA_TRANSACTION_STATUSES = ["recorded", "unmatched", "pending"];

export const COPILOT_DEVICE_STATUSES = ["active", "revoked"];
export const COPILOT_PARSE_STATUSES = ["parsed", "unparsed", "duplicate", "rejected"];
export const COPILOT_MATCH_STATUSES = ["matched", "unmatched", "n_a"];

export const AUDIT_ENTITY_TYPES = [
  "payment",
  "invoice",
  "expense",
  "property",
  "unit",
  "team_member",
  "tenant",
  "account",
  "utility",
  "maintenance",
  "landlord",
  "recurring_expense",
  "page",
];

export const ALERT_TYPES = ["payment", "report", "lease_expiry", "low_sms", "arrears"];
export const ALERT_CADENCES = ["daily", "weekly", "monthly", "realtime"];
export const ALERT_CHANNELS = ["dashboard", "sms", "email", "invoice"];

export const BACKUP_SCOPE_TYPES = ["property", "grouping", "tenants", "payments", "category"];
export const BACKUP_FORMATS = ["excel", "pdf"];

export const OTP_CHANNELS = ["sms", "email"];

export const DEFAULT_CURRENCY = "KES";
export const DEFAULT_TAX_RATE = 7.5;

// status value -> { label, color } consumed by <StatusBadge>. One map for every
// status vocabulary on the platform so a given status always renders identically.
export const STATUS_BADGE_MAP = {
  draft: { label: "Draft", color: "slate" },
  void: { label: "Void", color: "rose" },
  open: { label: "Open", color: "indigo" },
  overdue: { label: "Overdue", color: "rose" },
  partial: { label: "Partial", color: "amber" },
  // #7 — a fully-cleared invoice reads as "Confirmed" (auto-flips to paid on full allocation).
  paid: { label: "Confirmed", color: "emerald" },
  confirmed: { label: "Confirmed", color: "emerald" },
  pending: { label: "Pending", color: "amber" },
  declined: { label: "Declined", color: "rose" },
  in_progress: { label: "In Progress", color: "amber" },
  closed: { label: "Closed", color: "emerald" },
  uploaded: { label: "Uploaded", color: "indigo" },
  parsing: { label: "Parsing", color: "amber" },
  parsed: { label: "Parsed", color: "emerald" },
  failed: { label: "Failed", color: "rose" },
  recorded: { label: "Recorded", color: "emerald" },
  unmatched: { label: "Unmatched", color: "rose" },
  delivered: { label: "Delivered", color: "emerald" },
  trial: { label: "Trial", color: "indigo" },
  active: { label: "Active", color: "emerald" },
  past_due: { label: "Past Due", color: "amber" },
  suspended: { label: "Suspended", color: "rose" },
  granted: { label: "Granted", color: "emerald" },
  revoked: { label: "Revoked", color: "rose" },
  expired: { label: "Expired", color: "slate" },
  // Affiliate program
  rejected: { label: "Rejected", color: "rose" },
  completed: { label: "Completed", color: "emerald" },
  requested: { label: "Requested", color: "indigo" },
  processing: { label: "Processing", color: "amber" },
  // Co-pilot ingest log (parse_status / match_status)
  unparsed: { label: "Not recognized", color: "amber" },
  duplicate: { label: "Duplicate", color: "slate" },
  matched: { label: "Matched", color: "emerald" },
  n_a: { label: "—", color: "slate" },
};

export const STATUS_BADGE_COLOR_CLASSES = {
  slate: "bg-white/10 text-white/70 border border-white/15",
  indigo: "bg-third/20 text-third-100 border border-third/40",
  amber: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  emerald: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  rose: "bg-secondary/20 text-secondary-100 border border-secondary/40",
};
