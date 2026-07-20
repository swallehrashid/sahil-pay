import { apiSlice } from "@/store/apiSlice";

// Affiliate self-registration + authenticated portal. Mirrors
// server/routes/affiliate_routes.py exactly. Receipt downloads go through
// utils/downloadFile.js (blob response), not RTK Query.
export const affiliateApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    registerAffiliate: builder.mutation({
      query: (body) => ({ url: "/affiliate/register", method: "POST", body }),
    }),
    getAffiliateDashboard: builder.query({
      query: () => "/affiliate/dashboard",
      providesTags: ["Affiliate"],
    }),
    getAffiliateReferrals: builder.query({
      query: (params) => ({ url: "/affiliate/referrals", params }),
      providesTags: ["AffiliateReferral"],
    }),
    getAffiliateCommissions: builder.query({
      query: (params) => ({ url: "/affiliate/commissions", params }),
      providesTags: ["AffiliateCommission"],
    }),
    getAffiliateWithdrawals: builder.query({
      query: (params) => ({ url: "/affiliate/withdrawals", params }),
      providesTags: ["AffiliateWithdrawal"],
    }),
    requestAffiliateWithdrawal: builder.mutation({
      query: (body) => ({ url: "/affiliate/withdrawals", method: "POST", body }),
      invalidatesTags: ["AffiliateWithdrawal", "Affiliate"],
    }),
    getAffiliateProfile: builder.query({
      query: () => "/affiliate/profile",
      providesTags: ["Affiliate"],
    }),
    updateAffiliateProfile: builder.mutation({
      query: (body) => ({ url: "/affiliate/profile", method: "PATCH", body }),
      invalidatesTags: ["Affiliate"],
    }),
  }),
});

export const {
  useRegisterAffiliateMutation,
  useGetAffiliateDashboardQuery,
  useGetAffiliateReferralsQuery,
  useGetAffiliateCommissionsQuery,
  useGetAffiliateWithdrawalsQuery,
  useRequestAffiliateWithdrawalMutation,
  useGetAffiliateProfileQuery,
  useUpdateAffiliateProfileMutation,
} = affiliateApiSlice;
