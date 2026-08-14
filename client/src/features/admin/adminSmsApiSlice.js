import { apiSlice } from "@/store/apiSlice";

// §9.3 — mirrors server/routes/admin_sms_routes.py (/api/admin/sms).
export const adminSmsApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getSmsPricing: builder.query({
      query: () => "/admin/sms/pricing",
      providesTags: ["SmsPricing"],
    }),
    updateSmsPricing: builder.mutation({
      query: (body) => ({ url: "/admin/sms/pricing", method: "PUT", body }),
      invalidatesTags: ["SmsPricing", "SmsOverview"],
    }),
    getSmsCreditRanges: builder.query({
      query: () => "/admin/sms/credit-ranges",
      providesTags: ["SmsPricing"],
    }),
    updateSmsCreditRanges: builder.mutation({
      query: (body) => ({ url: "/admin/sms/credit-ranges", method: "PUT", body }),
      invalidatesTags: ["SmsPricing"],
    }),
    getSmsOverview: builder.query({
      query: (params) => ({ url: "/admin/sms/overview", params }),
      providesTags: ["SmsOverview"],
    }),
    getSmsPoolHistory: builder.query({
      query: () => "/admin/sms/pool/history",
      providesTags: ["SmsOverview"],
    }),
    topUpSmsPool: builder.mutation({
      query: (body) => ({ url: "/admin/sms/pool/top-up", method: "POST", body }),
      invalidatesTags: ["SmsPricing", "SmsOverview"],
    }),
    syncSmsPool: builder.mutation({
      query: () => ({ url: "/admin/sms/pool/sync", method: "POST" }),
      invalidatesTags: ["SmsPricing", "SmsOverview"],
    }),
    getLandlordSmsProvider: builder.query({
      query: (landlordId) => `/admin/sms/landlords/${landlordId}/provider`,
      providesTags: ["SmsOverview"],
    }),
    updateLandlordSmsProvider: builder.mutation({
      query: ({ landlordId, ...body }) => ({
        url: `/admin/sms/landlords/${landlordId}/provider`,
        method: "PUT",
        body,
      }),
      invalidatesTags: ["SmsOverview"],
    }),
    // Manually credit ONE landlord's SMS balance (paid the operator directly).
    creditLandlordSms: builder.mutation({
      query: ({ landlordId, ...body }) => ({
        url: `/admin/sms/landlords/${landlordId}/credit`,
        method: "POST",
        body,
      }),
      invalidatesTags: ["SmsOverview"],
    }),
    getLandlordSmsCredits: builder.query({
      query: (landlordId) => `/admin/sms/landlords/${landlordId}/credit`,
      providesTags: ["SmsOverview"],
    }),
    // Preview JSON for the report (downloads go through downloadFile in ReportView).
    getSmsReport: builder.query({
      query: (params) => ({ url: "/admin/sms/report", params }),
    }),

    // The rate ONE landlord pays per credit. Null returns them to the
    // account-wide default. A reason is mandatory — it is a verbally agreed
    // commercial term and lands in the audit log.
    setLandlordSmsPrice: builder.mutation({
      query: ({ landlordId, ...body }) => ({
        url: `/admin/sms/landlords/${landlordId}/price`,
        method: "PUT",
        body,
      }),
      invalidatesTags: ["SmsOverview", "AdminLandlord"],
      providesTags: ["SmsOverview"],
    }),
  }),
});

export const {
  useGetSmsPricingQuery,
  useUpdateSmsPricingMutation,
  useGetSmsCreditRangesQuery,
  useUpdateSmsCreditRangesMutation,
  useGetSmsOverviewQuery,
  useGetSmsPoolHistoryQuery,
  useTopUpSmsPoolMutation,
  useSyncSmsPoolMutation,
  useGetLandlordSmsProviderQuery,
  useUpdateLandlordSmsProviderMutation,
  useCreditLandlordSmsMutation,
  useGetLandlordSmsCreditsQuery,
  useGetSmsReportQuery,
  useSetLandlordSmsPriceMutation,
} = adminSmsApiSlice;
