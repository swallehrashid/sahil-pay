import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/lease_routes.py.
//
// Both halves live here — the staff side and the tenant portal — because they
// are one feature and the cache tags have to invalidate together: a tenant
// signing must refresh the landlord's review queue.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const leaseApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // --- Staff -------------------------------------------------------------
    getLeases: builder.query({
      query: (params = {}) => ({ url: "/leases", params }),
      transformResponse: unwrap,
      providesTags: ["Lease"],
    }),
    getTenantLeases: builder.query({
      query: (tenantId) => `/tenants/${tenantId}/leases`,
      transformResponse: unwrap,
      providesTags: ["Lease"],
    }),
    getLease: builder.query({
      query: (id) => `/leases/${id}`,
      transformResponse: unwrap,
      providesTags: (r, e, id) => [{ type: "Lease", id }],
    }),
    createLease: builder.mutation({
      query: ({ tenantId, ...body }) => ({
        url: `/tenants/${tenantId}/leases`, method: "POST", body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),
    sendLease: builder.mutation({
      query: (id) => ({ url: `/leases/${id}/send`, method: "POST" }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),
    approveLease: builder.mutation({
      query: (id) => ({ url: `/leases/${id}/approve`, method: "POST" }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),
    rejectLease: builder.mutation({
      query: ({ id, reason }) => ({
        url: `/leases/${id}/reject`, method: "POST", body: { reason },
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),
    getLeaseDocumentOptions: builder.query({
      query: () => "/leases/document-options",
      transformResponse: unwrap,
      providesTags: ["Lease", "DocumentTemplate"],
    }),
    // JSON { tenant_ids, document_kind, template_id, title } or FormData with `file`.
    sendLeases: builder.mutation({
      query: (body) => ({ url: "/leases/send-many", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease", "Notification"],
    }),
    uploadLease: builder.mutation({
      query: ({ tenantId, formData }) => ({
        url: `/tenants/${tenantId}/leases/upload`, method: "POST", body: formData,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),

    // --- Tenant portal -----------------------------------------------------
    getPortalLease: builder.query({
      query: () => "/portal/lease",
      transformResponse: unwrap,
      providesTags: ["Lease"],
    }),
    submitPortalLease: builder.mutation({
      query: (body) => ({ url: "/portal/lease/submit", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease"],
    }),
    // Every agreement across all the units this person rents.
    getPortalLeases: builder.query({
      query: () => "/portal/leases",
      transformResponse: unwrap,
      providesTags: ["Lease"],
    }),
    getPortalLeaseDetail: builder.query({
      query: (id) => `/portal/leases/${id}`,
      transformResponse: unwrap,
      providesTags: (r, e, id) => ["Lease", { type: "Lease", id }],
    }),
    signPortalLease: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/portal/leases/${id}/sign`, method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease", "Notification"],
    }),
    // FormData: files (one per page), signed_name, agreed=true
    uploadPortalLeaseScan: builder.mutation({
      query: ({ id, formData }) => ({ url: `/portal/leases/${id}/upload`, method: "POST", body: formData }),
      transformResponse: unwrap,
      invalidatesTags: ["Lease", "Notification"],
    }),
  }),
});

export const {
  useGetLeasesQuery,
  useGetTenantLeasesQuery,
  useGetLeaseQuery,
  useCreateLeaseMutation,
  useSendLeaseMutation,
  useApproveLeaseMutation,
  useRejectLeaseMutation,
  useUploadLeaseMutation,
  useGetLeaseDocumentOptionsQuery,
  useSendLeasesMutation,
  useGetPortalLeaseQuery,
  useSubmitPortalLeaseMutation,
  useGetPortalLeasesQuery,
  useGetPortalLeaseDetailQuery,
  useSignPortalLeaseMutation,
  useUploadPortalLeaseScanMutation,
} = leaseApiSlice;
