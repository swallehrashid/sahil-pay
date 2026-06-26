import { apiSlice } from "@/store/apiSlice";

// Domain 6 — mirrors server/routes/tenant_portal_routes.py. Self-service, OTP-authenticated.
export const tenantPortalApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPortalDashboard: builder.query({
      query: () => "/portal/dashboard",
      providesTags: ["TenantPortal"],
    }),
    makePortalPayment: builder.mutation({
      query: (body) => ({ url: "/portal/pay", method: "POST", body }),
      invalidatesTags: ["TenantPortal"],
    }),
    getPortalStatement: builder.query({
      query: (params) => ({ url: "/portal/statement", params }),
      providesTags: ["TenantPortal"],
    }),
    getPortalProfile: builder.query({
      query: () => "/portal/profile",
      providesTags: ["TenantPortal"],
    }),
    updatePortalProfile: builder.mutation({
      query: (body) => ({ url: "/portal/profile", method: "PUT", body }),
      invalidatesTags: ["TenantPortal"],
    }),
    getPortalMaintenanceRequests: builder.query({
      query: () => "/portal/maintenance",
      providesTags: ["TenantPortal"],
    }),
    createPortalMaintenanceRequest: builder.mutation({
      query: (body) => ({ url: "/portal/maintenance", method: "POST", body }),
      invalidatesTags: ["TenantPortal"],
    }),
  }),
});

export const {
  useGetPortalDashboardQuery,
  useMakePortalPaymentMutation,
  useGetPortalStatementQuery,
  useGetPortalProfileQuery,
  useUpdatePortalProfileMutation,
  useGetPortalMaintenanceRequestsQuery,
  useCreatePortalMaintenanceRequestMutation,
} = tenantPortalApiSlice;
