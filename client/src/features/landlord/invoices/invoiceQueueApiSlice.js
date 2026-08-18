import { apiSlice } from "@/store/apiSlice";

// Charges held for a unit's next invoice — see
// server/services/invoice_queue_service.py for why they exist.
const unwrap = (response) => response?.data ?? response;

export const invoiceQueueApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getInvoiceQueue: builder.query({
      query: () => "/invoice-queue/",
      transformResponse: unwrap,
      providesTags: ["InvoiceQueue"],
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
      invalidatesTags: ["InvoiceQueue"],
    }),
  }),
});

export const {
  useGetInvoiceQueueQuery,
  useGetUnitInvoiceQueueQuery,
  useApplyQueuedChargesMutation,
  useCancelQueuedChargeMutation,
} = invoiceQueueApiSlice;
