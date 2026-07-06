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
      query: ({ id, reason }) => ({ url: `/admin/landlords/${id}/suspend`, method: "POST", body: { reason } }),
      invalidatesTags: ["AdminLandlord"],
    }),
    reactivateLandlord: builder.mutation({
      query: ({ id, reason }) => ({ url: `/admin/landlords/${id}/reactivate`, method: "POST", body: { reason } }),
      invalidatesTags: ["AdminLandlord"],
    }),
    correctData: builder.mutation({
      query: (body) => ({ url: "/admin/correct-data", method: "POST", body }),
      invalidatesTags: ["Audit"],
    }),
    // ── Dashboard drill-downs: platform-wide entity directories ──────────────
    getAdminUnits: builder.query({
      query: (params) => ({ url: "/admin/units", params }),
      providesTags: ["AdminUnit"],
    }),
    getAdminUnit: builder.query({
      query: (id) => `/admin/units/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminUnit", id }],
    }),
    getAdminTenants: builder.query({
      query: (params) => ({ url: "/admin/tenants", params }),
      providesTags: ["AdminTenant"],
    }),
    getAdminTenant: builder.query({
      query: (id) => `/admin/tenants/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminTenant", id }],
    }),
    getAdminTeamMembers: builder.query({
      query: (params) => ({ url: "/admin/team-members", params }),
      providesTags: ["AdminTeamMember"],
    }),
    getAdminTeamMember: builder.query({
      query: (id) => `/admin/team-members/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminTeamMember", id }],
    }),
    getAdminProperties: builder.query({
      query: (params) => ({ url: "/admin/properties", params }),
      providesTags: ["AdminProperty"],
    }),
    getAdminProperty: builder.query({
      query: (id) => `/admin/properties/${id}`,
      providesTags: (result, error, id) => [{ type: "AdminProperty", id }],
    }),
    getMasterAuditLogs: builder.query({
      query: (params) => ({ url: "/admin/audit", params }),
      providesTags: ["Audit"],
    }),
    revertAuditAction: builder.mutation({
      query: ({ auditId, reason }) => ({ url: `/admin/revert/${auditId}`, method: "POST", body: { reason } }),
      invalidatesTags: ["Audit"],
    }),
  }),
});

export const {
  useGetAdminDashboardQuery,
  useGetAdminLandlordsQuery,
  useGetAdminLandlordQuery,
  useGetAdminUnitsQuery,
  useGetAdminUnitQuery,
  useGetAdminTenantsQuery,
  useGetAdminTenantQuery,
  useGetAdminTeamMembersQuery,
  useGetAdminTeamMemberQuery,
  useGetAdminPropertiesQuery,
  useGetAdminPropertyQuery,
  useSuspendLandlordMutation,
  useReactivateLandlordMutation,
  useCorrectDataMutation,
  useGetMasterAuditLogsQuery,
  useRevertAuditActionMutation,
} = adminApiSlice;
