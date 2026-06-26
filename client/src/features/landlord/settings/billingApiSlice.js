import { apiSlice } from "@/store/apiSlice";

// §4.21 — mirrors server/routes/billing_routes.py.
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
    buySms: builder.mutation({
      query: (body) => ({ url: "/billing/buy-sms", method: "POST", body }),
      invalidatesTags: ["Billing"],
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
  useBuySmsMutation,
  useGetBillingTransactionsQuery,
  useGenerateTaxInvoiceMutation,
} = billingApiSlice;
