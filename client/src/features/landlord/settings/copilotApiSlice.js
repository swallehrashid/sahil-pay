import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/settings_routes.py's /copilot section (COPILOT_PLATFORM_SPEC.md §5).
export const copilotApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getCopilotSettings: builder.query({
      query: () => "/settings/copilot",
      providesTags: ["CopilotSettings"],
    }),
    updateCopilotSettings: builder.mutation({
      query: (body) => ({ url: "/settings/copilot", method: "PUT", body }),
      invalidatesTags: ["CopilotSettings"],
    }),
    revokeCopilotDevice: builder.mutation({
      query: (id) => ({ url: `/settings/copilot/devices/${id}`, method: "DELETE" }),
      invalidatesTags: ["CopilotSettings"],
    }),
    getCopilotMessages: builder.query({
      query: (params) => ({ url: "/settings/copilot/messages", params }),
      providesTags: ["CopilotSettings"],
    }),
  }),
});

export const {
  useGetCopilotSettingsQuery,
  useUpdateCopilotSettingsMutation,
  useRevokeCopilotDeviceMutation,
  useGetCopilotMessagesQuery,
} = copilotApiSlice;
