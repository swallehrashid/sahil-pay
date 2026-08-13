import { apiSlice } from "@/store/apiSlice";

// The admin-authored help LIBRARY (server/routes/tutorial_routes.py).
//
// Not to be confused with features/landlord/tutorials/, which is the hardcoded
// first-run product tour. Article bodies arrive as finished, sanitised HTML —
// the client never parses markdown, and publication state plus role visibility
// are both decided server-side.
// Unwrap server/utils.py::success()'s {success, data, message} envelope.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const helpApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getHelpCategories: builder.query({
      query: () => "/tutorials",
      transformResponse: unwrap,
      providesTags: ["Tutorial"],
    }),
    getHelpArticle: builder.query({
      query: (slug) => `/tutorials/${slug}`,
      transformResponse: unwrap,
      providesTags: ["Tutorial"],
    }),
  }),
});

export const { useGetHelpCategoriesQuery, useGetHelpArticleQuery } = helpApiSlice;
