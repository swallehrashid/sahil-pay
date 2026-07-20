import { apiSlice } from "@/store/apiSlice";

// §4.21 — mirrors server/routes/billing_routes.py.
// MPESA_INTEGRATION_SPEC.md D3: the legacy pay-subscription/buy-sms mutations
// below are the Daraja-outage escape hatch — they no longer activate anything
// immediately, only the /stk variants (or an admin verify) do.
export const billingApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getBilling: builder.query({
      query: () => "/billing",
      providesTags: ["Billing"],
    }),
    paySubscription: builder.mutation({
      query: (body) => ({ url: "/billing/pay-subscription", method: "POST", body }),
      invalidatesTags: ["Billing", "Subscription"],
    }),
    paySubscriptionStk: builder.mutation({
      query: (body) => ({ url: "/billing/pay-subscription/stk", method: "POST", body }),
      invalidatesTags: ["Billing", "Subscription"],
    }),
    buySms: builder.mutation({
      query: (body) => ({ url: "/billing/buy-sms", method: "POST", body }),
      invalidatesTags: ["Billing"],
    }),
    buySmsStk: builder.mutation({
      query: (body) => ({ url: "/billing/buy-sms/stk", method: "POST", body }),
      invalidatesTags: ["Billing"],
    }),
    getTransactionStatus: builder.query({
      query: (id) => `/billing/transactions/${id}/status`,
    }),
    getBillingTransactions: builder.query({
      query: () => "/billing/transactions",
      providesTags: ["Billing"],
    }),
    generateTaxInvoice: builder.mutation({
      query: (body) => ({ url: "/billing/tax-invoice", method: "POST", body }),
      invalidatesTags: ["Billing"],
    }),
  }),
});

export const {
  useGetBillingQuery,
  usePaySubscriptionMutation,
  usePaySubscriptionStkMutation,
  useBuySmsMutation,
  useBuySmsStkMutation,
  useLazyGetTransactionStatusQuery,
  useGetBillingTransactionsQuery,
  useGenerateTaxInvoiceMutation,
} = billingApiSlice;
