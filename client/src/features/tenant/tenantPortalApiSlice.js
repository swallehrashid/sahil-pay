import { apiSlice } from "@/store/apiSlice";

// Domain 6 — mirrors server/routes/tenant_portal_routes.py. Self-service, OTP-authenticated.
export const tenantPortalApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPortalDashboard: builder.query({
      query: () => "/portal/dashboard",
      providesTags: ["TenantPortal"],
    }),
    getPaymentDetails: builder.query({
      query: () => "/portal/payment-details",
      providesTags: ["TenantPortal"],
    }),
    getPortalPayments: builder.query({
      query: () => "/portal/payments",
      providesTags: ["TenantPortal"],
    }),
    submitPortalPayment: builder.mutation({
      // Accepts FormData (with a proof file) — the base query passes it through untouched.
      query: (body) => ({ url: "/portal/payments/submit", method: "POST", body }),
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
    getPortalReceipt: builder.query({
      query: (paymentId) => `/portal/payments/${paymentId}/receipt?format=json`,
    }),
    getPortalMessages: builder.query({
      query: () => "/portal/messages",
      providesTags: ["TenantMessages"],
    }),
    sendPortalMessage: builder.mutation({
      query: (body) => ({ url: "/portal/messages", method: "POST", body }),
      invalidatesTags: ["TenantMessages"],
    }),
  }),
});

export const {
  useGetPortalDashboardQuery,
  useGetPaymentDetailsQuery,
  useGetPortalPaymentsQuery,
  useSubmitPortalPaymentMutation,
  useGetPortalStatementQuery,
  useGetPortalProfileQuery,
  useUpdatePortalProfileMutation,
  useGetPortalMaintenanceRequestsQuery,
  useCreatePortalMaintenanceRequestMutation,
  useGetPortalReceiptQuery,
  useLazyGetPortalReceiptQuery,
  useGetPortalMessagesQuery,
  useSendPortalMessageMutation,
} = tenantPortalApiSlice;
