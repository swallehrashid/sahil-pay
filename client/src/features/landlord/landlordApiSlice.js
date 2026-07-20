import { apiSlice } from "@/store/apiSlice";

// §4.1 dashboard aggregates — cross-module reads that don't belong to any single
// feature folder. Mirrors server/routes/landlord_dashboard_routes.py.
export const landlordApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getDashboardSummary: builder.query({
      query: () => "/dashboard/summary",
      providesTags: ["Dashboard"],
    }),
    getUnpaidTenants: builder.query({
      query: (params) => ({ url: "/dashboard/unpaid-tenants", params }),
      providesTags: ["Dashboard"],
    }),
    getPerformanceGraph: builder.query({
      query: () => "/dashboard/performance-graph",
      providesTags: ["Dashboard"],
    }),
    getQuickActionsData: builder.query({
      query: () => "/dashboard/quick-actions",
      providesTags: ["Dashboard"],
    }),
  }),
});

export const {
  useGetDashboardSummaryQuery,
  useGetUnpaidTenantsQuery,
  useGetPerformanceGraphQuery,
  useGetQuickActionsDataQuery,
} = landlordApiSlice;
