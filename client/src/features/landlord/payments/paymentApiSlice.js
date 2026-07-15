import { apiSlice } from "@/store/apiSlice";

// §4.3 — mirrors server/routes/payment_routes.py. Statuses exactly: confirmed/pending/declined.
export const paymentApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPayments: builder.query({
      query: (params) => ({ url: "/payments", params }),
      providesTags: ["Payment"],
    }),
    getPayment: builder.query({
      query: (id) => `/payments/${id}`,
      providesTags: (result, error, id) => [{ type: "Payment", id }],
    }),
    createPayment: builder.mutation({
      query: (body) => ({ url: "/payments", method: "POST", body }),
      invalidatesTags: ["Payment", "Invoice", "Tenant"],
    }),
    updatePayment: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/payments/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Payment", id }, "Payment", "Invoice"],
    }),
    deletePayment: builder.mutation({
      query: (id) => ({ url: `/payments/${id}`, method: "DELETE" }),
      invalidatesTags: ["Payment", "Invoice"],
    }),
    getAllocationPreview: builder.query({
      // Accepts either a bare payment id, or { id, tenant_id } to preview
      // allocation against a tenant other than (or in place of) the payment's own.
      query: (arg) => {
        const { id, tenant_id } = typeof arg === "object" ? arg : { id: arg, tenant_id: undefined };
        return { url: `/payments/${id}/allocation-preview`, params: tenant_id ? { tenant_id } : undefined };
      },
      providesTags: (result, error, arg) => [{ type: "Payment", id: typeof arg === "object" ? arg.id : arg }],
    }),
    confirmPayment: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/payments/${id}/confirm`, method: "POST", body }),
      invalidatesTags: ["Payment", "Invoice", "Tenant"],
    }),
    declinePayment: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/payments/${id}/decline`, method: "POST", body }),
      invalidatesTags: ["Payment"],
    }),
    sendPaymentReceipt: builder.mutation({
      // Accepts either a bare id (legacy row action → defaults to email) or
      // { id, channels: [...] } from the record-payment form.
      query: (arg) => {
        const { id, channels } = typeof arg === "object" ? arg : { id: arg, channels: undefined };
        return { url: `/payments/${id}/receipt/send`, method: "POST", body: channels ? { channels } : {} };
      },
    }),
    reassignPaymentTenant: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/payments/${id}/reassign`, method: "POST", body }),
      invalidatesTags: ["Payment", "Tenant"],
    }),
    uploadBankStatement: builder.mutation({
      query: (body) => ({ url: "/payments/bank-statement/upload", method: "POST", body }),
      invalidatesTags: ["BankStatement"],
    }),
    getBankStatementTransactions: builder.query({
      query: (id) => `/payments/bank-statement/${id}/transactions`,
      providesTags: (result, error, id) => [{ type: "BankStatement", id }],
    }),
    importBankStatementTransactions: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/payments/bank-statement/${id}/import`, method: "POST", body }),
      invalidatesTags: ["BankStatement", "Payment", "Invoice", "Tenant"],
    }),
    getTenantOutstandingItems: builder.query({
      query: (tenantId) => `/payments/tenants/${tenantId}/outstanding-items`,
      providesTags: (result, error, tenantId) => [{ type: "Tenant", id: tenantId }],
    }),
  }),
});

export const {
  useGetPaymentsQuery,
  useGetPaymentQuery,
  useCreatePaymentMutation,
  useUpdatePaymentMutation,
  useDeletePaymentMutation,
  useLazyGetAllocationPreviewQuery,
  useGetAllocationPreviewQuery,
  useConfirmPaymentMutation,
  useDeclinePaymentMutation,
  useSendPaymentReceiptMutation,
  useReassignPaymentTenantMutation,
  useUploadBankStatementMutation,
  useGetBankStatementTransactionsQuery,
  useImportBankStatementTransactionsMutation,
  useGetTenantOutstandingItemsQuery,
  useLazyGetTenantOutstandingItemsQuery,
} = paymentApiSlice;
