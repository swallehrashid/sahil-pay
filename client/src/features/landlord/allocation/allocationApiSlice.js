import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/allocation_routes.py — the payment allocation engine.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const allocationApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // --- Allocation settings ---------------------------------------------
    getAllocationMethod: builder.query({
      query: () => "/settings/allocation-method",
      transformResponse: unwrap,
      providesTags: ["AllocationSettings"],
    }),
    setAllocationMethod: builder.mutation({
      query: (body) => ({ url: "/settings/allocation-method", method: "PUT", body }),
      transformResponse: unwrap,
      invalidatesTags: ["AllocationSettings", "Unit", "Payout"],
    }),

    // --- Unit pay-codes ----------------------------------------------------
    setPayCode: builder.mutation({
      query: ({ unitId, pay_code }) => ({
        url: `/units/${unitId}/pay-code`,
        method: "PUT",
        body: { pay_code },
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Unit"],
    }),
    checkPayCode: builder.query({
      query: ({ code, unitId }) => ({
        url: "/units/pay-code-available",
        params: { code, ...(unitId ? { unit_id: unitId } : {}) },
      }),
      transformResponse: unwrap,
    }),

    // --- Payment sources ---------------------------------------------------
    getPaymentSources: builder.query({
      query: () => "/payment-sources",
      transformResponse: unwrap,
      providesTags: ["PaymentSource"],
    }),
    createPaymentSource: builder.mutation({
      query: (body) => ({ url: "/payment-sources", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["PaymentSource"],
    }),
    updatePaymentSource: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `/payment-sources/${id}`, method: "PATCH", body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["PaymentSource"],
    }),

    // --- Review queue ------------------------------------------------------
    getReviewQueue: builder.query({
      query: () => "/payments/review-queue",
      transformResponse: unwrap,
      providesTags: ["ReviewQueue"],
    }),
    getPaymentSuggestion: builder.query({
      query: (paymentId) => `/payments/${paymentId}/suggestion`,
      transformResponse: unwrap,
    }),
    allocatePayment: builder.mutation({
      query: ({ paymentId, splits }) => ({
        url: `/payments/${paymentId}/allocate`, method: "POST", body: { splits },
      }),
      transformResponse: unwrap,
      invalidatesTags: ["ReviewQueue", "Payment", "Tenant", "Payout", "Dashboard"],
    }),
    reversePayment: builder.mutation({
      query: ({ paymentId, reason }) => ({
        url: `/payments/${paymentId}/reverse`, method: "POST", body: { reason },
      }),
      transformResponse: unwrap,
      invalidatesTags: ["ReviewQueue", "Payment", "Tenant", "Payout", "Dashboard"],
    }),
    getAllocationAudit: builder.query({
      query: (paymentId) => `/payments/${paymentId}/allocation-audit`,
      transformResponse: unwrap,
    }),

    // --- Commission rules --------------------------------------------------
    getCommissionRules: builder.query({
      query: () => "/commission-rules",
      transformResponse: unwrap,
      providesTags: ["CommissionRule"],
    }),
    saveCommissionRule: builder.mutation({
      query: (body) => ({ url: "/commission-rules", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["CommissionRule", "Payout"],
    }),
    deleteCommissionRule: builder.mutation({
      query: (id) => ({ url: `/commission-rules/${id}`, method: "DELETE" }),
      invalidatesTags: ["CommissionRule", "Payout"],
    }),

    // --- Payouts -----------------------------------------------------------
    previewPayouts: builder.query({
      // `include` is a comma-joined list of charge-type keys, omitted entirely
      // until the operator has actually chosen — an empty string would read as
      // "nothing", and rent is never nothing.
      query: ({ period_start, period_end, include, commission_basis } = {}) => ({
        url: "/payouts/preview",
        params: { ...(period_start ? { period_start } : {}),
                  ...(period_end ? { period_end } : {}),
                  ...(include?.length ? { include: include.join(",") } : {}),
                  ...(commission_basis ? { commission_basis } : {}) },
      }),
      transformResponse: unwrap,
      providesTags: ["Payout"],
    }),
    generatePayouts: builder.mutation({
      query: (body) => ({ url: "/payouts/generate", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["Payout", "OwnerPayout"],
    }),
    markPayoutPaid: builder.mutation({
      query: ({ payoutId, ...body }) => ({
        url: `/payouts/${payoutId}/mark-paid`, method: "POST", body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Payout", "OwnerPayout"],
    }),
  }),
});

export const {
  useGetAllocationMethodQuery,
  useSetAllocationMethodMutation,
  useSetPayCodeMutation,
  useLazyCheckPayCodeQuery,
  useGetPaymentSourcesQuery,
  useCreatePaymentSourceMutation,
  useUpdatePaymentSourceMutation,
  useGetReviewQueueQuery,
  useGetPaymentSuggestionQuery,
  useAllocatePaymentMutation,
  useReversePaymentMutation,
  useGetAllocationAuditQuery,
  useGetCommissionRulesQuery,
  useSaveCommissionRuleMutation,
  useDeleteCommissionRuleMutation,
  usePreviewPayoutsQuery,
  useGeneratePayoutsMutation,
  useMarkPayoutPaidMutation,
} = allocationApiSlice;
