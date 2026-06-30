// Single source of truth for every route path in the app.
// AppRoutes.jsx, sidebars, redirects and links all import from here — never hardcode a path string elsewhere.

export const PUBLIC_ROUTES = {
  home: "/",
  about: "/about",
  features: "/features",
  pricing: "/pricing",
  contact: "/contact",
  faq: "/faq",
  privacy: "/privacy",
  terms: "/terms",
};

export const AUTH_ROUTES = {
  login: "/login",
  register: "/register",
  verifyEmail: "/verify-email/:token",
  verifyEmailPath: (token) => `/verify-email/${token}`,
  forgotPassword: "/forgot-password",
  resetPassword: "/reset-password",
  teamActivate: "/team-activate/:token",
  teamActivatePath: (token) => `/team-activate/${token}`,
  tenantLogin: "/tenant/login",
  changePassword: "/change-password",
};

// Module path suffixes shared between the Landlord portal and the Team Member
// portal (the team member re-mounts the same landlord page components, gated
// by their permission matrix instead of duplicating pages).
const SHARED_MODULES = {
  dashboard: "dashboard",
  properties: "properties",
  units: "units",
  tenants: "tenants",
  tenantsDeleted: "tenants/deleted",
  tenantTransactions: "tenants/:id/transactions",
  invoices: "invoices",
  payments: "payments",
  expenses: "expenses",
  utilities: "utilities",
  maintenance: "maintenance",
  groups: "groups",
  reportsStatements: "reports/statements",
  reportsInsights: "reports/insights",
  communications: "communications",
  notifications: "notifications",
};

function buildPortalRoutes(rootPrefix) {
  const routes = { root: rootPrefix };
  for (const [key, suffix] of Object.entries(SHARED_MODULES)) {
    routes[key] = `${rootPrefix}/${suffix}`;
  }
  routes.tenantTransactionsPath = (id) => `${rootPrefix}/tenants/${id}/transactions`;
  return routes;
}

export const LANDLORD_ROUTES = {
  ...buildPortalRoutes("/landlord"),
  bankStatementReview: "/landlord/payments/bank-statement/:id",
  bankStatementReviewPath: (id) => `/landlord/payments/bank-statement/${id}`,
  notificationsSend: "/landlord/notifications/send",
  settings: {
    root: "/landlord/settings",
    general: "/landlord/settings/general",
    backup: "/landlord/settings/backup",
    alerts: "/landlord/settings/alerts",
    account: "/landlord/settings/account",
    documents: "/landlord/settings/documents",
    team: "/landlord/settings/team",
    billing: "/landlord/settings/billing",
    mpesa: "/landlord/settings/mpesa",
    audit: "/landlord/settings/audit",
    impersonationRequests: "/landlord/settings/impersonation-requests",
  },
};

export const TEAM_ROUTES = {
  ...buildPortalRoutes("/team"),
  profile: "/team/profile",
};

export const TENANT_ROUTES = {
  root: "/portal",
  dashboard: "/portal/dashboard",
  pay: "/portal/pay",
  statement: "/portal/statement",
  maintenance: "/portal/maintenance",
  profile: "/portal/profile",
  notifications: "/portal/notifications",
};

export const ADMIN_ROUTES = {
  root: "/admin",
  dashboard: "/admin/dashboard",
  landlords: "/admin/landlords",
  landlordDetail: "/admin/landlords/:id",
  landlordDetailPath: (id) => `/admin/landlords/${id}`,
  pricing: "/admin/pricing",
  trials: "/admin/trials",
  impersonation: "/admin/impersonation",
  audit: "/admin/audit",
  notifications: "/admin/notifications",
  notificationsSend: "/admin/notifications/send",
};

export const NOT_FOUND_ROUTE = "*";
