import { apiSlice } from "@/store/apiSlice";

// §4.11 + §4.12 — mirrors server/routes/report_routes.py. Every statement supports
// ?format=pdf|excel via ExportButtons; these queries fetch the on-screen preview data.
export const reportApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getTenantStatement: builder.query({
      query: ({ id, ...params }) => ({ url: `/reports/statements/tenant/${id}`, params }),
      providesTags: ["Report"],
    }),
    getPropertyStatement: builder.query({
      query: ({ id, ...params }) => ({ url: `/reports/statements/property/${id}`, params }),
      providesTags: ["Report"],
    }),
    getArrearsReport: builder.query({
      query: (params) => ({ url: "/reports/statements/arrears", params }),
      providesTags: ["Report"],
    }),
    getExpensesReport: builder.query({
      query: (params) => ({ url: "/reports/statements/expenses", params }),
      providesTags: ["Report"],
    }),
    getMonthOnMonthReport: builder.query({
      query: (params) => ({ url: "/reports/statements/month-on-month", params }),
      providesTags: ["Report"],
    }),
    getYearOnYearReport: builder.query({
      query: (params) => ({ url: "/reports/statements/year-on-year", params }),
      providesTags: ["Report"],
    }),
    getGroupingReport: builder.query({
      query: ({ id, ...params }) => ({ url: `/reports/statements/grouping/${id}`, params }),
      providesTags: ["Report"],
    }),
    getDeletedTenantsReport: builder.query({
      query: (params) => ({ url: "/reports/statements/deleted-tenants", params }),
      providesTags: ["Report"],
    }),
    getInsights: builder.query({
      query: (params) => ({ url: "/reports/insights", params }),
      providesTags: ["Report"],
    }),
    getOccupancyInsights: builder.query({
      query: (params) => ({ url: "/reports/insights/occupancy", params }),
      providesTags: ["Report"],
    }),
  }),
});

export const {
  useGetTenantStatementQuery,
  useGetPropertyStatementQuery,
  useGetArrearsReportQuery,
  useGetExpensesReportQuery,
  useGetMonthOnMonthReportQuery,
  useGetYearOnYearReportQuery,
  useGetGroupingReportQuery,
  useGetDeletedTenantsReportQuery,
  useGetInsightsQuery,
  useGetOccupancyInsightsQuery,
} = reportApiSlice;
