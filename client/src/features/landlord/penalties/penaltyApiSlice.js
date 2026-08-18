import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/penalty_routes.py — late-payment penalties.
//
// Policies are held PER PROPERTY, so every query here is keyed by property id
// rather than by account: a manager running eighty blocks for seventy owners
// has some who charge late fees and some who refuse to.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const penaltyApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPenaltyPolicy: builder.query({
      query: (propertyId) => `/properties/${propertyId}/penalty-policy`,
      transformResponse: unwrap,
      providesTags: (result, error, propertyId) => [
        { type: "PenaltyPolicy", id: propertyId },
      ],
    }),
    savePenaltyPolicy: builder.mutation({
      query: ({ propertyId, ...body }) => ({
        url: `/properties/${propertyId}/penalty-policy`,
        method: "PUT",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: (result, error, { propertyId }) => [
        { type: "PenaltyPolicy", id: propertyId },
        "PenaltyReport",
      ],
    }),

    // Dry run: who WOULD be charged. Nobody should have to discover what an
    // automatic fine does by watching it land on real tenants.
    previewPenalties: builder.query({
      query: (date) => ({ url: "/penalties/preview", params: date ? { date } : {} }),
      transformResponse: unwrap,
      providesTags: ["PenaltyReport"],
    }),
    runPenalties: builder.mutation({
      query: (body) => ({ url: "/penalties/run", method: "POST", body: body || {} }),
      transformResponse: unwrap,
      invalidatesTags: ["PenaltyReport", "Invoice", "Tenant", "Dashboard"],
    }),
    chargePenalty: builder.mutation({
      query: (body) => ({ url: "/penalties/charge", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["PenaltyReport", "Invoice", "Tenant", "Dashboard"],
    }),

    // Manual batch runs — the counterpart to the automatic policy engine.
    // Candidates is a QUERY (read-only, re-fetches as filters change); the run
    // is a mutation that invalidates the ledger it just moved.
    getPenaltyCandidates: builder.query({
      query: (params) => ({ url: "/penalties/batch/candidates", params }),
      transformResponse: (r) => r?.data ?? r,
      providesTags: ["PenaltyReport"],
    }),
    runBatchPenalties: builder.mutation({
      query: (body) => ({ url: "/penalties/batch/run", method: "POST", body }),
      transformResponse: (r) => r?.data ?? r,
      invalidatesTags: ["PenaltyReport", "Invoice", "Tenant", "Payment"],
    }),
    getPenaltyReport: builder.query({
      query: (params = {}) => ({ url: "/reports/penalties", params }),
      transformResponse: unwrap,
      providesTags: ["PenaltyReport"],
    }),
  }),
});

export const {
  useGetPenaltyCandidatesQuery,
  useRunBatchPenaltiesMutation,
  useGetPenaltyPolicyQuery,
  useSavePenaltyPolicyMutation,
  usePreviewPenaltiesQuery,
  useRunPenaltiesMutation,
  useChargePenaltyMutation,
  useGetPenaltyReportQuery,
} = penaltyApiSlice;
