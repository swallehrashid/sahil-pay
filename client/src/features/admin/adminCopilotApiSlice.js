import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/admin_copilot_routes.py (COPILOT_PLATFORM_SPEC.md §7).
export const adminCopilotApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getCopilotOverview: builder.query({
      query: () => "/admin/copilot/overview",
      providesTags: ["AdminCopilot"],
    }),
    getCopilotDevices: builder.query({
      query: (params) => ({ url: "/admin/copilot/devices", params }),
      providesTags: ["AdminCopilot"],
    }),
    revokeCopilotDeviceAdmin: builder.mutation({
      query: (id) => ({ url: `/admin/copilot/devices/${id}/revoke`, method: "POST" }),
      invalidatesTags: ["AdminCopilot"],
    }),
    getCopilotLandlordPosture: builder.query({
      query: () => "/admin/copilot/landlords",
      providesTags: ["AdminCopilot"],
    }),
    setCopilotLandlordLock: builder.mutation({
      query: ({ id, admin_locked }) => ({
        url: `/admin/copilot/landlords/${id}`, method: "PUT", body: { admin_locked },
      }),
      invalidatesTags: ["AdminCopilot"],
    }),
    getCopilotMessagesAdmin: builder.query({
      query: (params) => ({ url: "/admin/copilot/messages", params }),
      providesTags: ["AdminCopilot"],
    }),
    getCopilotTemplates: builder.query({
      query: (params) => ({ url: "/admin/copilot/templates", params }),
      providesTags: ["AdminCopilot"],
    }),
    createCopilotTemplate: builder.mutation({
      query: (body) => ({ url: "/admin/copilot/templates", method: "POST", body }),
      invalidatesTags: ["AdminCopilot"],
    }),
    updateCopilotTemplate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/copilot/templates/${id}`, method: "PUT", body }),
      invalidatesTags: ["AdminCopilot"],
    }),
    deleteCopilotTemplate: builder.mutation({
      query: (id) => ({ url: `/admin/copilot/templates/${id}`, method: "DELETE" }),
      invalidatesTags: ["AdminCopilot"],
    }),
    testCopilotTemplate: builder.mutation({
      query: (body) => ({ url: "/admin/copilot/templates/test", method: "POST", body }),
    }),
    getCopilotUnparsed: builder.query({
      query: () => "/admin/copilot/unparsed",
      providesTags: ["AdminCopilot"],
    }),
    retryCopilotMessage: builder.mutation({
      query: (id) => ({ url: `/admin/copilot/unparsed/${id}/retry`, method: "POST" }),
      invalidatesTags: ["AdminCopilot"],
    }),
    retryAllCopilotMessages: builder.mutation({
      query: (senderId) => ({
        url: "/admin/copilot/unparsed/retry-all",
        method: "POST",
        params: senderId ? { sender_id: senderId } : undefined,
      }),
      invalidatesTags: ["AdminCopilot"],
    }),
    getCopilotReleases: builder.query({
      query: () => "/admin/copilot/releases",
      providesTags: ["AdminCopilot"],
    }),
    createCopilotRelease: builder.mutation({
      query: (formData) => ({ url: "/admin/copilot/releases", method: "POST", body: formData }),
      invalidatesTags: ["AdminCopilot"],
    }),
  }),
});

export const {
  useGetCopilotOverviewQuery,
  useGetCopilotDevicesQuery,
  useRevokeCopilotDeviceAdminMutation,
  useGetCopilotLandlordPostureQuery,
  useSetCopilotLandlordLockMutation,
  useGetCopilotMessagesAdminQuery,
  useGetCopilotTemplatesQuery,
  useCreateCopilotTemplateMutation,
  useUpdateCopilotTemplateMutation,
  useDeleteCopilotTemplateMutation,
  useTestCopilotTemplateMutation,
  useGetCopilotUnparsedQuery,
  useRetryCopilotMessageMutation,
  useRetryAllCopilotMessagesMutation,
  useGetCopilotReleasesQuery,
  useCreateCopilotReleaseMutation,
} = adminCopilotApiSlice;
