import { apiSlice } from "@/store/apiSlice";

// Charge-category restructure — mirrors server/routes/charge_category_routes.py,
// settings allocation-priority, and the payments report / rollover-trail endpoints.
export const chargeCategoryApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // ── Catalogue CRUD (kind = utility | invoice) ──────────────────────────
    getChargeCategories: builder.query({
      query: (params) => ({ url: "/charge-categories", params }),
      providesTags: ["ChargeCategory"],
    }),
    createChargeCategory: builder.mutation({
      query: (body) => ({ url: "/charge-categories", method: "POST", body }),
      invalidatesTags: ["ChargeCategory", "AllocationPriority"],
    }),
    updateChargeCategory: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/charge-categories/${id}`, method: "PATCH", body }),
      invalidatesTags: ["ChargeCategory", "AllocationPriority"],
    }),
    deleteChargeCategory: builder.mutation({
      query: (id) => ({ url: `/charge-categories/${id}`, method: "DELETE" }),
      invalidatesTags: ["ChargeCategory", "AllocationPriority"],
    }),

    // ── Settings → allocation priority ─────────────────────────────────────
    getAllocationPriority: builder.query({
      query: () => "/settings/allocation-priority",
      providesTags: ["AllocationPriority"],
    }),
    updateAllocationPriority: builder.mutation({
      query: (order) => ({ url: "/settings/allocation-priority", method: "PUT", body: { order } }),
      invalidatesTags: ["AllocationPriority"],
    }),

    // ── Payments (allocation) ──────────────────────────────────────────────
    getTenantOutstandingItems: builder.query({
      query: (tenantId) => `/payments/tenants/${tenantId}/outstanding-items`,
      providesTags: ["Payment", "Invoice"],
    }),

    // ── Reports ────────────────────────────────────────────────────────────
    getPaymentsReport: builder.query({
      query: (params) => ({ url: "/reports/payments", params }),
      providesTags: ["Report"],
    }),
    getRolloverTrail: builder.query({
      query: (lineId) => `/reports/line-items/${lineId}/rollover-trail`,
    }),
  }),
});

export const {
  useGetChargeCategoriesQuery,
  useCreateChargeCategoryMutation,
  useUpdateChargeCategoryMutation,
  useDeleteChargeCategoryMutation,
  useGetAllocationPriorityQuery,
  useUpdateAllocationPriorityMutation,
  useGetTenantOutstandingItemsQuery,
  useLazyGetTenantOutstandingItemsQuery,
  useGetPaymentsReportQuery,
  useGetRolloverTrailQuery,
  useLazyGetRolloverTrailQuery,
} = chargeCategoryApiSlice;
