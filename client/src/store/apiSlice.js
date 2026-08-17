import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import { env } from "@/config/env";
import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "@/utils/tokenStorage";
import { getImpersonationTarget } from "@/utils/impersonationStorage";
import { getDemoMode } from "@/utils/demoStorage";
import { getSelectedTenantId } from "@/utils/tenantUnitStorage";

const rawBaseQuery = fetchBaseQuery({
  baseUrl: env.apiBaseUrl,
  prepareHeaders: (headers) => {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    // Consent-based impersonation (§10.5) — when a system_admin has entered a
    // granted session, every request carries this header so the backend's
    // current_landlord_id() resolves to the impersonated account. Harmless to
    // send unconditionally: the server only honors it for system_admin callers
    // with a matching granted, non-expired ImpersonationRequest.
    const target = getImpersonationTarget();
    if (target?.landlordId) headers.set("X-Impersonate-Landlord", String(target.landlordId));
    // Demo mode (DEMO_MODE_SPEC.md §5.2) — once a landlord/PM has entered
    // their demo shadow, every request carries this so the backend's
    // current_landlord_id() resolves to the shadow instead of their real
    // account. Harmless to send unconditionally: the server only honors it
    // for a landlord/PM caller with an existing shadow.
    if (getDemoMode()?.active) headers.set("X-Demo-Mode", "1");
    // Multi-unit tenants (one person, several tenancies) pick which unit they
    // are looking at; every portal request carries it. Harmless to send
    // unconditionally — the server honours it ONLY when the requested tenancy
    // belongs to the same person as the signed-in one, and 403s otherwise, so
    // this header can never reach somebody else's account.
    const unitId = getSelectedTenantId();
    if (unitId) headers.set("X-Tenant-Id", String(unitId));
    return headers;
  },
});

let refreshPromise = null;

// Optional numeric fields left blank in a form arrive here as "" (empty string).
// Sent as-is they reach the API as "" and Postgres rejects them with
// `invalid input syntax for type numeric: ""` — a 500 whose error page carries no
// CORS header, so the browser surfaces it as an opaque "No Access-Control-Allow-Origin"
// network failure. Normalising "" -> null at the single mutation chokepoint clears every
// create/edit form at once. (The backend should ALSO coerce/validate these at its
// boundary so a bad client can never 500 it — see QA report.) FormData bodies (file
// uploads) are passed through untouched.
function sanitizeBody(args) {
  if (!args || typeof args !== "object") return args;
  const { body } = args;
  if (!body || typeof body !== "object" || body instanceof FormData) return args;
  const cleaned = {};
  for (const [k, v] of Object.entries(body)) cleaned[k] = v === "" ? null : v;
  return { ...args, body: cleaned };
}

// Wraps the raw query so a single 401 triggers exactly one refresh attempt (shared across
// concurrent requests via refreshPromise) before retrying the original request once.
async function baseQueryWithReauth(args, api, extraOptions) {
  if (typeof args === "object") args = sanitizeBody(args);
  let result = await rawBaseQuery(args, api, extraOptions);

  if (result.error?.status === 401 && getRefreshToken()) {
    refreshPromise ??= rawBaseQuery(
      {
        url: "/auth/refresh",
        method: "POST",
        body: { refresh_token: getRefreshToken() },
      },
      api,
      extraOptions
    ).finally(() => {
      refreshPromise = null;
    });

    const refreshResult = await refreshPromise;

    if (refreshResult.data?.access_token) {
      setTokens({ accessToken: refreshResult.data.access_token });
      result = await rawBaseQuery(args, api, extraOptions);
    } else {
      clearTokens();
    }
  }

  return result;
}

// The ONE createApi instance for the whole app. Every feature slice injects into this
// via apiSlice.injectEndpoints(...) — never call createApi anywhere else.
export const apiSlice = createApi({
  reducerPath: "api",
  baseQuery: baseQueryWithReauth,
  tagTypes: [
    "Me",
    "Landlord",
    "TeamMember",
    "TeamMemberPermission",
    "Property",
    "Unit",
    "PropertyGroup",
    "ManagerAssignment",
    "Tenant",
    "TenantDocument",
    "Invoice",
    "Payment",
    "BankStatement",
    "MpesaTransaction",
    "Expense",
    "RecurringExpense",
    "Utility",
    "Maintenance",
    "ImportMapping",
    // Separate from "Maintenance" so posting a note refetches the thread
    // without re-pulling the whole request list behind the dialog.
    "MaintenanceComment",
    "Communication",
    "MessageTemplate",
    "DocumentTemplate",
    "Billing",
    "Subscription",
    "Package",
    "SmsPricing",
    "SmsOverview",
    "Trial",
    "Impersonation",
    "Settings",
    "Onboarding",
    "ChargeCategory",
    "AllocationPriority",
    "Audit",
    "Notification",
    "Backup",
    "Dashboard",
    "Report",
    "AdminLandlord",
    "AdminUnit",
    "AdminTenant",
    "AdminTeamMember",
    "AdminProperty",
    "TenantPortal",
    "TenantMessages",
    "TenantMessageThread",
    "Affiliate",
    "AffiliateReferral",
    "AffiliateCommission",
    "AffiliateWithdrawal",
    "AdminAffiliate",
    "AdminAffiliateWithdrawal",
    "AdminAffiliateConfig",
    "CopilotSettings",
    "AdminCopilot",
    "CopilotInbox",
    "OwnerPayout",
    "TeamPreset",
    "TenantScore",
    "Demo",
    "AdminBillingTransaction",
    "AdminC2bPayment",
    // KRA / eTIMS compliance layer + Help Content CMS
    "EtimsSettings",
    "EtimsScope",
    "EtimsRegister",
    "PropertyOwner",
    "KraReport",
    "TaxPermission",
    "Tutorial",
    "AdminTutorial",
    "UserPreference",
    // Payment allocation engine
    "AllocationSettings",
    "PaymentSource",
    "ReviewQueue",
    "CommissionRule",
    "Payout",
    // Tenancy agreements (staff + tenant portal share this tag)
    "Lease",
    // Late-payment penalties (per property)
    "PenaltyPolicy",
    "PenaltyReport",
  ],
  endpoints: () => ({}),
});

export default apiSlice;
