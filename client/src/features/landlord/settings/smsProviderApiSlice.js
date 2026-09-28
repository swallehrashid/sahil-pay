import { apiSlice } from "@/store/apiSlice";

// §9.3 — mirrors the /api/settings/sms-provider endpoints: Sahil Pay's shared
// sender, a branded sender name on Sahil Pay's account, or a third party's own
// FluxSMS account (API key + sender ID), verified live on connect.
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
    testSmsProvider: builder.mutation({
      query: (body) => ({ url: "/settings/sms-provider/test", method: "POST", body }),
    }),
  }),
});

export const {
  useGetSmsProviderQuery,
  useUpdateSmsProviderMutation,
  useConnectSmsProviderMutation,
  useDisconnectSmsProviderMutation,
  useTestSmsProviderMutation,
} = smsProviderApiSlice;
