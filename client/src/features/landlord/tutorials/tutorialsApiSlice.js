import { apiSlice } from "@/store/apiSlice";

// Mirrors settingsApiSlice.js — GET/PUT /api/settings/onboarding
// (ONBOARDING_TUTORIALS_SPEC.md §4.2 / §5.1).
export const tutorialsApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getOnboarding: builder.query({
      query: () => "/settings/onboarding",
      providesTags: ["Onboarding"],
    }),
    updateOnboarding: builder.mutation({
      query: (body) => ({ url: "/settings/onboarding", method: "PUT", body }),
      invalidatesTags: ["Onboarding"],
    }),
  }),
});

export const { useGetOnboardingQuery, useUpdateOnboardingMutation } = tutorialsApiSlice;
