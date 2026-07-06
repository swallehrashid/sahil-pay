import { apiSlice } from "@/store/apiSlice";

// §4.5 — mirrors server/routes/tenant_routes.py.
export const tenantApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getTenants: builder.query({
      query: (params) => ({ url: "/tenants", params }),
      providesTags: ["Tenant"],
    }),
    getDeletedTenants: builder.query({
      query: (params) => ({ url: "/tenants/deleted", params }),
      providesTags: ["Tenant"],
    }),
    getTenant: builder.query({
      query: (id) => `/tenants/${id}`,
      providesTags: (result, error, id) => [{ type: "Tenant", id }],
    }),
    getTenantTransactions: builder.query({
      query: (id) => `/tenants/${id}/transactions`,
      providesTags: (result, error, id) => [{ type: "Tenant", id }],
    }),
    createTenant: builder.mutation({
      query: (body) => ({ url: "/tenants", method: "POST", body }),
      invalidatesTags: ["Tenant"],
    }),
    updateTenant: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/tenants/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Tenant", id }, "Tenant"],
    }),
    deleteTenant: builder.mutation({
      query: (id) => ({ url: `/tenants/${id}`, method: "DELETE" }),
      invalidatesTags: ["Tenant"],
    }),
    shiftTenant: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/tenants/${id}/shift`, method: "POST", body }),
      invalidatesTags: ["Tenant", "Unit"],
    }),
    sendTenantReminder: builder.mutation({
      // #4 — body carries { channels: [...], message? } chosen at send time.
      query: ({ id, ...body }) => ({ url: `/tenants/${id}/reminder`, method: "POST", body }),
    }),
    sendBulkReminder: builder.mutation({
      query: (body) => ({ url: "/tenants/bulk-reminder", method: "POST", body }),
    }),
    sendTenantStatement: builder.mutation({
      query: (id) => ({ url: `/tenants/${id}/statement/send`, method: "POST" }),
    }),
    uploadTenantDocument: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/tenants/${id}/documents`, method: "POST", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Tenant", id }],
    }),
  }),
});

export const {
  useGetTenantsQuery,
  useGetDeletedTenantsQuery,
  useGetTenantQuery,
  useGetTenantTransactionsQuery,
  useCreateTenantMutation,
  useUpdateTenantMutation,
  useDeleteTenantMutation,
  useShiftTenantMutation,
  useSendTenantReminderMutation,
  useSendBulkReminderMutation,
  useSendTenantStatementMutation,
  useUploadTenantDocumentMutation,
} = tenantApiSlice;
