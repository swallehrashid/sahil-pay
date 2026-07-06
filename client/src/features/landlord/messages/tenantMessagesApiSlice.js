import { apiSlice } from "@/store/apiSlice";

// Landlord/team side of the tenant↔landlord conversation.
// Mirrors server/routes/tenant_message_routes.py.
export const tenantMessagesApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getTenantMessageThreads: builder.query({
      query: () => "/tenant-messages/",
      providesTags: ["TenantMessages"],
    }),
    getTenantMessageThread: builder.query({
      query: (tenantId) => `/tenant-messages/${tenantId}`,
      providesTags: (result, error, tenantId) => [{ type: "TenantMessageThread", id: tenantId }],
    }),
    replyTenantMessage: builder.mutation({
      query: ({ tenantId, body }) => ({
        url: `/tenant-messages/${tenantId}`,
        method: "POST",
        body: { body },
      }),
      invalidatesTags: (result, error, { tenantId }) => [
        "TenantMessages",
        { type: "TenantMessageThread", id: tenantId },
      ],
    }),
  }),
});

export const {
  useGetTenantMessageThreadsQuery,
  useGetTenantMessageThreadQuery,
  useReplyTenantMessageMutation,
} = tenantMessagesApiSlice;
