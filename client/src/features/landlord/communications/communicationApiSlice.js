import { apiSlice } from "@/store/apiSlice";

// §4.13 + §4.19 — mirrors server/routes/communication_routes.py.
export const communicationApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getCommunications: builder.query({
      query: (params) => ({ url: "/communications", params }),
      providesTags: ["Communication"],
    }),
    sendCommunication: builder.mutation({
      query: (body) => ({ url: "/communications/send", method: "POST", body }),
      invalidatesTags: ["Communication"],
    }),
    resendCommunication: builder.mutation({
      query: (id) => ({ url: `/communications/${id}/resend`, method: "POST" }),
      invalidatesTags: ["Communication"],
    }),
    getMessageTemplates: builder.query({
      query: () => "/communications/templates",
      providesTags: ["MessageTemplate"],
    }),
    getMessageVariables: builder.query({
      query: () => "/communications/variables",
    }),
    getDefaultTemplates: builder.query({
      query: () => "/communications/default-templates",
    }),
    installDefaultTemplates: builder.mutation({
      query: () => ({ url: "/communications/templates/install-defaults", method: "POST" }),
      invalidatesTags: ["MessageTemplate"],
    }),
    createMessageTemplate: builder.mutation({
      query: (body) => ({ url: "/communications/templates", method: "POST", body }),
      invalidatesTags: ["MessageTemplate"],
    }),
    updateMessageTemplate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/communications/templates/${id}`, method: "PUT", body }),
      invalidatesTags: ["MessageTemplate"],
    }),
    deleteMessageTemplate: builder.mutation({
      query: (id) => ({ url: `/communications/templates/${id}`, method: "DELETE" }),
      invalidatesTags: ["MessageTemplate"],
    }),
  }),
});

export const {
  useGetCommunicationsQuery,
  useSendCommunicationMutation,
  useResendCommunicationMutation,
  useGetMessageTemplatesQuery,
  useGetMessageVariablesQuery,
  useGetDefaultTemplatesQuery,
  useInstallDefaultTemplatesMutation,
  useCreateMessageTemplateMutation,
  useUpdateMessageTemplateMutation,
  useDeleteMessageTemplateMutation,
} = communicationApiSlice;
