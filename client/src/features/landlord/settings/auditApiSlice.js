import { apiSlice } from "@/store/apiSlice";

// §4.23 — mirrors server/routes/audit_routes.py (landlord-scoped view).
export const auditApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getAuditLogs: builder.query({
      query: (params) => ({ url: "/audit", params }),
      providesTags: ["Audit"],
    }),
    getAuditLog: builder.query({
      query: (id) => `/audit/${id}`,
      providesTags: (result, error, id) => [{ type: "Audit", id }],
    }),
  }),
});

export const { useGetAuditLogsQuery, useGetAuditLogQuery } = auditApiSlice;
