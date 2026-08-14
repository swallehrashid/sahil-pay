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
  useGetPortalLeaseQuery,
  useSubmitPortalLeaseMutation,
} = leaseApiSlice;
