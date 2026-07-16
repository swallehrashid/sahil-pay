import { apiSlice } from "@/store/apiSlice";

// §9.3 — mirrors the /api/settings/sms-provider endpoints (custom SMS sender reselling).
export const smsProviderApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getSmsProvider: builder.query({
      query: () => "/settings/sms-provider",
      providesTags: ["Settings"],
    }),
    updateSmsProvider: builder.mutation({
      query: (body) => ({ url: "/settings/sms-provider", method: "PUT", body }),
      invalidatesTags: ["Settings"],
    }),
    connectSmsProvider: builder.mutation({
      query: () => ({ url: "/settings/sms-provider/connect", method: "POST" }),
      invalidatesTags: ["Settings"],
    }),
    disconnectSmsProvider: builder.mutation({
      query: () => ({ url: "/settings/sms-provider/disconnect", method: "POST" }),
      invalidatesTags: ["Settings"],
    }),
  }),
});

export const {
  useGetSmsProviderQuery,
  useUpdateSmsProviderMutation,
  useConnectSmsProviderMutation,
  useDisconnectSmsProviderMutation,
} = smsProviderApiSlice;
