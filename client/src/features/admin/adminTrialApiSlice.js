import { apiSlice } from "@/store/apiSlice";

// §7.5 — mirrors server/routes/admin_trial_routes.py.
export const adminTrialApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getGlobalTrialConfig: builder.query({
      query: () => "/admin/trials/global",
      providesTags: ["Trial"],
    }),
    updateGlobalTrialConfig: builder.mutation({
      query: (body) => ({ url: "/admin/trials/global", method: "PUT", body }),
      invalidatesTags: ["Trial"],
    }),
    updateLandlordTrial: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/trials/landlords/${id}`, method: "PUT", body }),
      invalidatesTags: ["Trial", "AdminLandlord"],
    }),
    runTrialExpiry: builder.mutation({
      query: () => ({ url: "/admin/trials/expire-due", method: "POST" }),
      invalidatesTags: ["Trial", "AdminLandlord"],
    }),
  }),
});

export const {
  useGetGlobalTrialConfigQuery,
  useUpdateGlobalTrialConfigMutation,
  useUpdateLandlordTrialMutation,
  useRunTrialExpiryMutation,
} = adminTrialApiSlice;
