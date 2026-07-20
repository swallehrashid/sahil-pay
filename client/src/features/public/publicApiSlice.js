import { apiSlice } from "@/store/apiSlice";

// Phase 2 — unauthenticated marketing-site data (mirrors server/routes/public_routes.py).
export const publicApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPublicPackages: builder.query({
      query: () => "/public/packages",
      providesTags: ["Package"],
      transformResponse: (res) => res?.packages ?? [],
    }),
    getPublicAffiliateProgram: builder.query({
      query: () => "/public/affiliate-program",
    }),
  }),
});

export const { useGetPublicPackagesQuery, useGetPublicAffiliateProgramQuery } = publicApiSlice;
