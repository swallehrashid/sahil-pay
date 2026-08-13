import { apiSlice } from "@/store/apiSlice";

// Per-user UI stickiness (server/routes/preference_routes.py): sticky report
// checkboxes, dismissed one-time nudges. Nothing here changes what a document
// contains or who may see what — it only remembers what the UI last did.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const preferencesApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPreferences: builder.query({
      query: () => "/preferences",
      transformResponse: unwrap,
      providesTags: ["UserPreference"],
    }),
    updatePreferences: builder.mutation({
      query: (body) => ({ url: "/preferences", method: "PATCH", body }),
      transformResponse: unwrap,
      invalidatesTags: ["UserPreference"],
    }),
  }),
});

export const { useGetPreferencesQuery, useUpdatePreferencesMutation } = preferencesApiSlice;
