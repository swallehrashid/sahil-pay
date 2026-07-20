import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/admin_billing_routes.py
// (/api/admin/billing-transactions, /api/admin/billing/c2b-payments).
export const adminBillingApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getAdminBillingTransactions: builder.query({
      query: (params) => ({ url: "/admin/billing-transactions", params }),
      providesTags: ["AdminBillingTransaction"],
    }),
    verifyBillingTransaction: builder.mutation({
      query: (id) => ({ url: `/admin/billing-transactions/${id}/verify`, method: "POST" }),
      invalidatesTags: ["AdminBillingTransaction"],
    }),
    reverseBillingTransaction: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/billing-transactions/${id}/reverse`, method: "POST", body }),
      invalidatesTags: ["AdminBillingTransaction"],
    }),
    getAdminC2bPayments: builder.query({
      query: (params) => ({ url: "/admin/billing/c2b-payments", params }),
      providesTags: ["AdminC2bPayment"],
    }),
    resolveC2bPayment: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/billing/c2b-payments/${id}/resolve`, method: "POST", body }),
      invalidatesTags: ["AdminC2bPayment", "AdminBillingTransaction"],
    }),
  }),
});

export const {
  useGetAdminBillingTransactionsQuery,
  useVerifyBillingTransactionMutation,
  useReverseBillingTransactionMutation,
  useGetAdminC2bPaymentsQuery,
  useResolveC2bPaymentMutation,
} = adminBillingApiSlice;
