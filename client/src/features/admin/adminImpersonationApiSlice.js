import { apiSlice } from "@/store/apiSlice";

// §7.3 / §10.5 — mirrors server/routes/admin_impersonation_routes.py (admin side).
export const adminImpersonationApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    requestImpersonation: builder.mutation({
      query: (body) => ({ url: "/admin/impersonation/request", method: "POST", body }),
      invalidatesTags: ["Impersonation"],
    }),
    getImpersonationRequests: builder.query({
      query: () => "/admin/impersonation/requests",
      providesTags: ["Impersonation"],
    }),
    revokeImpersonation: builder.mutation({
      query: (id) => ({ url: `/admin/impersonation/requests/${id}/revoke`, method: "POST" }),
      invalidatesTags: ["Impersonation"],
    }),
  }),
});

export const { useRequestImpersonationMutation, useGetImpersonationRequestsQuery, useRevokeImpersonationMutation } = adminImpersonationApiSlice;
