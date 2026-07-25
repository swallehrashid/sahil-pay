import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/copilot_routes.py's landlord-session endpoints
// (COPILOT_LANDLORD_INBOX_SPEC.md §3) — the Payments page's Co-Pilot tab.
// NOT the device-token API in copilot_routes.py's /pair, /heartbeat, /ingest.
export const copilotInboxApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getCopilotInboxMessages: builder.query({
      query: (params) => ({ url: "/copilot/messages", params }),
      providesTags: ["CopilotInbox"],
    }),
    getCopilotInboxMessage: builder.query({
      query: (id) => `/copilot/messages/${id}`,
      providesTags: (result, error, id) => [{ type: "CopilotInbox", id }],
    }),
    getCopilotInboxSummary: builder.query({
      query: () => "/copilot/messages/summary",
      providesTags: ["CopilotInbox"],
    }),
    // Materialise a pending payment for a parsed-but-unmatched message so it
    // can be opened in the shared review-and-allocate modal (ConfirmPaymentModal).
    prepareCopilotPayment: builder.mutation({
      query: (id) => ({ url: `/copilot/messages/${id}/prepare-payment`, method: "POST" }),
      invalidatesTags: (result, error, id) => [
        "CopilotInbox",
        { type: "CopilotInbox", id },
        "Payment",
      ],
    }),
  }),
});

export const {
  useGetCopilotInboxMessagesQuery,
  useGetCopilotInboxMessageQuery,
  useGetCopilotInboxSummaryQuery,
  usePrepareCopilotPaymentMutation,
} = copilotInboxApiSlice;
