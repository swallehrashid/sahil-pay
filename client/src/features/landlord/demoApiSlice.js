import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/demo_routes.py (DEMO_MODE_SPEC.md §3.2).
export const demoApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getDemoStatus: builder.query({
      query: () => "/demo/status",
      providesTags: ["Demo"],
    }),
    enterDemo: builder.mutation({
      query: () => ({ url: "/demo/enter", method: "POST" }),
      invalidatesTags: ["Demo"],
    }),
    exitDemo: builder.mutation({
      query: () => ({ url: "/demo/exit", method: "POST" }),
      invalidatesTags: ["Demo"],
    }),
    resetDemo: builder.mutation({
      query: () => ({ url: "/demo/reset", method: "POST" }),
      invalidatesTags: ["Demo"],
    }),
  }),
});

export const {
  useGetDemoStatusQuery,
  useEnterDemoMutation,
  useExitDemoMutation,
  useResetDemoMutation,
} = demoApiSlice;
