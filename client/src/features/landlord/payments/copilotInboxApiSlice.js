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
  }),
});

export const {
  useGetCopilotInboxMessagesQuery,
  useGetCopilotInboxMessageQuery,
  useGetCopilotInboxSummaryQuery,
} = copilotInboxApiSlice;
