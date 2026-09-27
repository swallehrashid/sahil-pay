import { apiSlice } from "@/store/apiSlice";

// §4.8 — mirrors server/routes/utility_routes.py. Items: water/electricity/garbage/security.
export const utilityApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getUtilityReadings: builder.query({
      query: (params) => ({ url: "/utilities", params }),
      providesTags: ["Utility"],
    }),
    createUtilityReading: builder.mutation({
      query: (body) => ({ url: "/utilities", method: "POST", body }),
      invalidatesTags: ["Utility"],
    }),
    updateUtilityReading: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/utilities/${id}`, method: "PUT", body }),
      invalidatesTags: ["Utility"],
    }),
    deleteUtilityReading: builder.mutation({
      query: (id) => ({ url: `/utilities/${id}`, method: "DELETE" }),
      invalidatesTags: ["Utility"],
    }),
    bulkUploadUtilities: builder.mutation({
      query: (body) => ({ url: "/utilities/bulk-upload", method: "POST", body }),
      invalidatesTags: ["Utility"],
    }),
    generateUtilityInvoices: builder.mutation({
      query: (body) => ({ url: "/utilities/bulk-upload/generate-invoices", method: "POST", body }),
      invalidatesTags: ["Utility", "Invoice"],
    }),
    addReadingToInvoice: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/utilities/${id}/add-to-invoice`, method: "POST", body }),
      invalidatesTags: ["Utility", "Invoice", "InvoiceQueue"],
    }),
    // Queue readings for the next invoice. A caretaker's go in as "waiting for
    // review"; an invoices editor's are approved straight away.
    queueUtilityReadings: builder.mutation({
      query: (body) => ({ url: "/utilities/queue", method: "POST", body }),
      invalidatesTags: ["Utility", "InvoiceQueue"],
    }),
    // The landlord utility catalogue now lives in chargeCategoryApiSlice
    // (/charge-categories?kind=utility) — see ChargeCategoryManager.
  }),
});

export const {
  useGetUtilityReadingsQuery,
  useCreateUtilityReadingMutation,
  useUpdateUtilityReadingMutation,
  useDeleteUtilityReadingMutation,
  useBulkUploadUtilitiesMutation,
  useGenerateUtilityInvoicesMutation,
  useAddReadingToInvoiceMutation,
  useQueueUtilityReadingsMutation,
} = utilityApiSlice;
