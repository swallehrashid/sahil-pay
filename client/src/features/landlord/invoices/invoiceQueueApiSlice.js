import { apiSlice } from "@/store/apiSlice";

// Charges held for a unit's next invoice — see
// server/services/invoice_queue_service.py for why they exist.
const unwrap = (response) => response?.data ?? response;

export const invoiceQueueApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getInvoiceQueue: builder.query({
      query: (params) => ({ url: "/invoice-queue/", params }),
      transformResponse: unwrap,
      providesTags: ["InvoiceQueue"],
    }),
    reviewQueuedCharges: builder.mutation({
      query: (body) => ({ url: "/invoice-queue/review", method: "POST", body }),
      transformResponse: (response) => ({ ...(response?.data ?? {}), message: response?.message }),
      invalidatesTags: ["InvoiceQueue", "Utility"],
    }),
    // Raise this month's invoices now: rent and/or approved queued charges,
    // with any unpaid balance carried forward onto the same invoice.
    runMonthlyInvoicing: builder.mutation({
      query: (body) => ({ url: "/invoice-queue/run-monthly", method: "POST", body }),
      transformResponse: (response) => ({ ...(response?.data ?? {}), message: response?.message }),
      invalidatesTags: ["InvoiceQueue", "Invoice", "Tenant", "Utility", "Dashboard"],
    }),
    // Monthly invoicing one property at a time: the overview of every
    // property for a month, and what one property's run would bill.
    getMonthlyByProperty: builder.query({
      query: (params) => ({ url: "/invoice-queue/by-property", params }),
      transformResponse: unwrap,
      providesTags: ["InvoiceQueue", "Invoice"],
    }),
    getMonthlyPropertyPreview: builder.query({
      query: ({ propertyId, ...params }) => ({ url: `/invoice-queue/by-property/${propertyId}`, params }),
      transformResponse: unwrap,
      providesTags: ["InvoiceQueue", "Invoice"],
    }),
    // Asked by the invoice form before saving, so it can warn that a unit has
    // charges waiting rather than letting somebody raise a bill that silently
    // omits the month's water.
    getUnitInvoiceQueue: builder.query({
      query: (unitId) => `/invoice-queue/units/${unitId}`,
      transformResponse: unwrap,
      providesTags: (result, error, unitId) => [{ type: "InvoiceQueue", id: unitId }],
    }),
    applyQueuedCharges: builder.mutation({
      query: ({ unitId, ...body }) => ({
        url: `/invoice-queue/units/${unitId}/apply`,
        method: "POST",
        body,
      }),
      transformResponse: unwrap,
      // Billing a queued charge moves an invoice and a tenant balance.
      invalidatesTags: ["InvoiceQueue", "Invoice", "Tenant"],
    }),
    cancelQueuedCharge: builder.mutation({
      query: (id) => ({ url: `/invoice-queue/${id}`, method: "DELETE" }),
      invalidatesTags: ["InvoiceQueue", "Utility"],
    }),
  }),
});

export const {
  useGetInvoiceQueueQuery,
  useGetUnitInvoiceQueueQuery,
  useApplyQueuedChargesMutation,
  useCancelQueuedChargeMutation,
  useReviewQueuedChargesMutation,
  useRunMonthlyInvoicingMutation,
  useGetMonthlyByPropertyQuery,
  useGetMonthlyPropertyPreviewQuery,
} = invoiceQueueApiSlice;
