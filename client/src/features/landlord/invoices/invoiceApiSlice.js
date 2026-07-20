import { apiSlice } from "@/store/apiSlice";

// §4.2 — mirrors server/routes/invoice_routes.py. Statuses exactly: draft/void/open/partial/paid.
export const invoiceApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getInvoices: builder.query({
      query: (params) => ({ url: "/invoices", params }),
      providesTags: ["Invoice"],
    }),
    getInvoice: builder.query({
      query: (id) => `/invoices/${id}`,
      providesTags: (result, error, id) => [{ type: "Invoice", id }],
    }),
    createInvoice: builder.mutation({
      query: (body) => ({ url: "/invoices", method: "POST", body }),
      invalidatesTags: ["Invoice", "Tenant"],
    }),
    updateInvoice: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/invoices/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Invoice", id }, "Invoice"],
    }),
    deleteInvoice: builder.mutation({
      query: (id) => ({ url: `/invoices/${id}`, method: "DELETE" }),
      invalidatesTags: ["Invoice"],
    }),
    sendInvoice: builder.mutation({
      query: (id) => ({ url: `/invoices/${id}/send`, method: "POST" }),
    }),
    bulkDownloadInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/bulk-download", method: "POST", body }),
    }),
    generateRentInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/generate/rent", method: "POST", body }),
      invalidatesTags: ["Invoice"],
    }),
    generateRecurringInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/generate/recurring", method: "POST", body }),
      invalidatesTags: ["Invoice"],
    }),
    generatePenaltyInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/generate/penalty", method: "POST", body }),
      invalidatesTags: ["Invoice"],
    }),
    generateCustomInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/generate/custom", method: "POST", body }),
      invalidatesTags: ["Invoice"],
    }),
    bulkAddInvoices: builder.mutation({
      query: (body) => ({ url: "/invoices/bulk", method: "POST", body }),
      invalidatesTags: ["Invoice"],
    }),
  }),
});

export const {
  useGetInvoicesQuery,
  useGetInvoiceQuery,
  useCreateInvoiceMutation,
  useUpdateInvoiceMutation,
  useDeleteInvoiceMutation,
  useSendInvoiceMutation,
  useBulkDownloadInvoicesMutation,
  useGenerateRentInvoicesMutation,
  useGenerateRecurringInvoicesMutation,
  useGeneratePenaltyInvoicesMutation,
  useGenerateCustomInvoicesMutation,
  useBulkAddInvoicesMutation,
} = invoiceApiSlice;
