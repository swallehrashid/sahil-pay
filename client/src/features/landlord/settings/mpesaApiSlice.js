import { apiSlice } from "@/store/apiSlice";

// §4.22 — mirrors server/routes/mpesa_routes.py (landlord-initiated status checks, not webhooks).
export const mpesaApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    checkMpesaStatus: builder.mutation({
      query: (body) => ({ url: "/mpesa/status-check", method: "POST", body }),
      invalidatesTags: ["MpesaTransaction"],
    }),
    getMpesaTransactions: builder.query({
      query: (params) => ({ url: "/mpesa/transactions", params }),
      providesTags: ["MpesaTransaction"],
    }),
  }),
});

export const { useCheckMpesaStatusMutation, useGetMpesaTransactionsQuery } = mpesaApiSlice;
