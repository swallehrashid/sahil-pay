import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/admin_affiliate_routes.py (/api/admin/affiliates).
export const adminAffiliateApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getAdminAffiliates: builder.query({
      query: (params) => ({ url: "/admin/affiliates", params }),
      providesTags: ["AdminAffiliate"],
    }),
    getAdminAffiliateDetail: builder.query({
      query: (id) => `/admin/affiliates/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminAffiliate", id }],
    }),
    approveAffiliate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/${id}/approve`, method: "POST", body }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    rejectAffiliate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/${id}/reject`, method: "POST", body }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    suspendAffiliate: builder.mutation({
      query: (id) => ({ url: `/admin/affiliates/${id}/suspend`, method: "POST" }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    reactivateAffiliate: builder.mutation({
      query: (id) => ({ url: `/admin/affiliates/${id}/reactivate`, method: "POST" }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    updateAffiliate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/${id}`, method: "PATCH", body }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    updateAffiliateReferral: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/referrals/${id}`, method: "PATCH", body }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    voidAffiliateReferral: builder.mutation({
      query: (id) => ({ url: `/admin/affiliates/referrals/${id}/void`, method: "POST" }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    attributeAffiliateReferral: builder.mutation({
      query: (body) => ({ url: "/admin/affiliates/attribute", method: "POST", body }),
      invalidatesTags: ["AdminAffiliate"],
    }),
    getAffiliateConfig: builder.query({
      query: () => "/admin/affiliates/config",
      providesTags: ["AdminAffiliateConfig"],
    }),
    updateAffiliateConfig: builder.mutation({
      query: (body) => ({ url: "/admin/affiliates/config", method: "PATCH", body }),
      invalidatesTags: ["AdminAffiliateConfig"],
    }),
    getAdminAffiliateWithdrawals: builder.query({
      query: (params) => ({ url: "/admin/affiliates/withdrawals", params }),
      providesTags: ["AdminAffiliateWithdrawal"],
    }),
    processAffiliateWithdrawal: builder.mutation({
      query: (id) => ({ url: `/admin/affiliates/withdrawals/${id}/process`, method: "POST" }),
      invalidatesTags: ["AdminAffiliateWithdrawal", "AdminAffiliate"],
    }),
    payAffiliateWithdrawal: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/withdrawals/${id}/pay`, method: "POST", body }),
      invalidatesTags: ["AdminAffiliateWithdrawal", "AdminAffiliate"],
    }),
    payAffiliateWithdrawalB2c: builder.mutation({
      query: ({ id }) => ({ url: `/admin/affiliates/withdrawals/${id}/pay-b2c`, method: "POST" }),
      invalidatesTags: ["AdminAffiliateWithdrawal", "AdminAffiliate"],
    }),
    rejectAffiliateWithdrawal: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/affiliates/withdrawals/${id}/reject`, method: "POST", body }),
      invalidatesTags: ["AdminAffiliateWithdrawal", "AdminAffiliate"],
    }),
    getAffiliateAnalytics: builder.query({
      query: () => "/admin/affiliates/analytics",
    }),
  }),
});

export const {
  useGetAdminAffiliatesQuery,
  useGetAdminAffiliateDetailQuery,
  useApproveAffiliateMutation,
  useRejectAffiliateMutation,
  useSuspendAffiliateMutation,
  useReactivateAffiliateMutation,
  useUpdateAffiliateMutation,
  useUpdateAffiliateReferralMutation,
  useVoidAffiliateReferralMutation,
  useAttributeAffiliateReferralMutation,
  useGetAffiliateConfigQuery,
  useUpdateAffiliateConfigMutation,
  useGetAdminAffiliateWithdrawalsQuery,
  useProcessAffiliateWithdrawalMutation,
  usePayAffiliateWithdrawalMutation,
  usePayAffiliateWithdrawalB2cMutation,
  useRejectAffiliateWithdrawalMutation,
  useGetAffiliateAnalyticsQuery,
} = adminAffiliateApiSlice;
