import { apiSlice } from "@/store/apiSlice";

// Section 7 — mirrors server/routes/admin_routes.py. Platform health + account control.
export const adminApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getAdminDashboard: builder.query({
      query: () => "/admin/dashboard",
      providesTags: ["AdminLandlord"],
    }),
    getAdminLandlords: builder.query({
      query: (params) => ({ url: "/admin/landlords", params }),
      providesTags: ["AdminLandlord"],
    }),
    getAdminLandlord: builder.query({
      query: (id) => `/admin/landlords/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminLandlord", id }],
    }),
    suspendLandlord: builder.mutation({
      query: (id) => ({ url: `/admin/landlords/${id}/suspend`, method: "POST" }),
      invalidatesTags: ["AdminLandlord"],
    }),
    reactivateLandlord: builder.mutation({
      query: (id) => ({ url: `/admin/landlords/${id}/reactivate`, method: "POST" }),
      invalidatesTags: ["AdminLandlord"],
    }),
    correctData: builder.mutation({
      query: (body) => ({ url: "/admin/correct-data", method: "POST", body }),
      invalidatesTags: ["Audit"],
    }),
    getMasterAuditLogs: builder.query({
      query: (params) => ({ url: "/admin/audit", params }),
      providesTags: ["Audit"],
    }),
    revertAuditAction: builder.mutation({
      query: (auditId) => ({ url: `/admin/revert/${auditId}`, method: "POST" }),
      invalidatesTags: ["Audit"],
    }),
  }),
});

export const {
  useGetAdminDashboardQuery,
  useGetAdminLandlordsQuery,
  useGetAdminLandlordQuery,
  useSuspendLandlordMutation,
  useReactivateLandlordMutation,
  useCorrectDataMutation,
  useGetMasterAuditLogsQuery,
  useRevertAuditActionMutation,
} = adminApiSlice;
