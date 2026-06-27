import { createApi, fetchBaseQuery } from "@reduxjs/toolkit/query/react";
import { env } from "@/config/env";
import { getAccessToken, getRefreshToken, setTokens, clearTokens } from "@/utils/tokenStorage";
import { getImpersonationTarget } from "@/utils/impersonationStorage";

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
    return headers;
  },
});

let refreshPromise = null;

// Wraps the raw query so a single 401 triggers exactly one refresh attempt (shared across
// concurrent requests via refreshPromise) before retrying the original request once.
async function baseQueryWithReauth(args, api, extraOptions) {
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
    "Communication",
    "MessageTemplate",
    "DocumentTemplate",
    "Billing",
    "Subscription",
    "Package",
    "Trial",
    "Impersonation",
    "Settings",
    "Audit",
    "Notification",
    "Backup",
    "Dashboard",
    "Report",
    "AdminLandlord",
    "TenantPortal",
  ],
  endpoints: () => ({}),
});

export default apiSlice;
