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
    // Pre-send SMS credit-cost calculator (email/in-app are free).
    quoteCommunication: builder.mutation({
      query: (body) => ({ url: "/communications/quote", method: "POST", body }),
    }),
    // Credit balance + sender identity, gated on `messages` rather than
    // `settings`. The settings endpoint carries the provider API key, so the
    // people who actually send messages could not read their own balance from
    // it — see the route's docstring.
    getSmsBalance: builder.query({
      query: () => "/communications/sms-balance",
      providesTags: ["Communication"],
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
  useQuoteCommunicationMutation,
  useGetSmsBalanceQuery,
  useResendCommunicationMutation,
  useGetMessageTemplatesQuery,
  useGetMessageVariablesQuery,
  useGetDefaultTemplatesQuery,
  useInstallDefaultTemplatesMutation,
  useCreateMessageTemplateMutation,
  useUpdateMessageTemplateMutation,
  useDeleteMessageTemplateMutation,
} = communicationApiSlice;
