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
      invalidatesTags: ["Utility", "Invoice"],
    }),

    // #6 — landlord utility catalogue (deposit / balance / current_utility types).
    getUtilityTypes: builder.query({
      query: (params) => ({ url: "/utilities/types", params }),
      providesTags: ["UtilityType"],
    }),
    createUtilityType: builder.mutation({
      query: (body) => ({ url: "/utilities/types", method: "POST", body }),
      invalidatesTags: ["UtilityType"],
    }),
    updateUtilityType: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/utilities/types/${id}`, method: "PUT", body }),
      invalidatesTags: ["UtilityType"],
    }),
    deleteUtilityType: builder.mutation({
      query: (id) => ({ url: `/utilities/types/${id}`, method: "DELETE" }),
      invalidatesTags: ["UtilityType"],
    }),
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
  useGetUtilityTypesQuery,
  useCreateUtilityTypeMutation,
  useUpdateUtilityTypeMutation,
  useDeleteUtilityTypeMutation,
} = utilityApiSlice;
