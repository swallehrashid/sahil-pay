import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/etims_routes.py — the manual-first KRA/eTIMS layer.
//
// Every read here is safe to fire from any account: a landlord who has never
// enabled the feature gets `enabled: false` and empty lists, and the UI is
// expected to render NOTHING rather than an empty state. See the spec's §0
// golden rule — absence is invisible, never flagged.
// server/utils.py::success() wraps every payload as {success, data, message}.
// Unwrapped once here so no component has to reach through `.data.data`.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const etimsApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // --- Settings ---------------------------------------------------------
    getEtimsSettings: builder.query({
      query: () => "/etims/settings",
      transformResponse: unwrap,
      providesTags: ["EtimsSettings"],
    }),
    updateEtimsSettings: builder.mutation({
      query: (body) => ({ url: "/etims/settings", method: "PATCH", body }),
      transformResponse: unwrap,
      invalidatesTags: ["EtimsSettings", "EtimsScope", "Me"],
    }),
    updatePropertyEtimsSettings: builder.mutation({
      query: ({ propertyId, ...body }) => ({
        url: `/properties/${propertyId}/etims-settings`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["EtimsSettings", "EtimsScope", "Property", "EtimsRegister"],
    }),

    // The navigation gate: an empty `properties` array means the eTIMS
    // Register and KRA report must not appear in the sidebar at all.
    getEtimsScope: builder.query({
      query: () => "/etims/scope",
      transformResponse: unwrap,
      providesTags: ["EtimsScope"],
    }),

    // --- Property owners --------------------------------------------------
    getPropertyOwners: builder.query({
      query: () => "/property-owners",
      transformResponse: unwrap,
      providesTags: ["PropertyOwner"],
    }),
    createPropertyOwner: builder.mutation({
      query: (body) => ({ url: "/property-owners", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["PropertyOwner", "EtimsSettings"],
    }),
    updatePropertyOwner: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `/property-owners/${id}`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["PropertyOwner", "EtimsSettings", "KraReport"],
    }),

    // --- Recording numbers ------------------------------------------------
    setPaymentEtims: builder.mutation({
      query: ({ paymentId, ...body }) => ({
        url: `/payments/${paymentId}/etims`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Payment", "EtimsRegister", "KraReport"],
    }),
    clearPaymentEtims: builder.mutation({
      query: (paymentId) => ({
        url: `/payments/${paymentId}/etims`,
        method: "DELETE",
      }),
      transformResponse: unwrap,
      invalidatesTags: ["Payment", "EtimsRegister", "KraReport"],
    }),
    setPayoutEtims: builder.mutation({
      query: ({ payoutId, ...body }) => ({
        url: `/owner-payouts/${payoutId}/etims`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["OwnerPayout", "EtimsRegister"],
    }),

    // Batch save from the Register. Always resolves 200 — per-row outcomes are
    // in `data.saved` / `data.errors`, because a partial save is the normal
    // case here and must not surface as a failed request.
    bulkEtims: builder.mutation({
      query: (records) => ({ url: "/etims/bulk", method: "POST", body: { records } }),
      transformResponse: unwrap,
      invalidatesTags: ["EtimsRegister", "Payment", "OwnerPayout", "KraReport"],
    }),

    // --- Register ---------------------------------------------------------
    getEtimsRegister: builder.query({
      query: ({ scope = "payments", propertyIds = [], month, status = "all" } = {}) => ({
        url: "/etims/register",
        params: {
          scope,
          status,
          ...(month ? { month } : {}),
          ...(propertyIds.length ? { property_ids: propertyIds.join(",") } : {}),
        },
      }),
      transformResponse: unwrap,
      providesTags: ["EtimsRegister"],
    }),

    // --- KRA Monthly Report -----------------------------------------------
    getKraMonthlyReport: builder.query({
      query: ({ month, propertyId, ownerId, consolidated = true } = {}) => ({
        url: "/reports/kra-monthly",
        params: {
          consolidated: consolidated ? "true" : "false",
          ...(month ? { month } : {}),
          ...(propertyId ? { property_id: propertyId } : {}),
          ...(ownerId ? { owner_id: ownerId } : {}),
        },
      }),
      transformResponse: unwrap,
      providesTags: ["KraReport"],
    }),

    // --- Team-member tax grants -------------------------------------------
    getTaxPermissions: builder.query({
      query: (memberId) => `/team-members/${memberId}/tax-permissions`,
      transformResponse: unwrap,
      providesTags: ["TaxPermission"],
    }),
    setTaxPermissions: builder.mutation({
      query: ({ memberId, propertyIds }) => ({
        url: `/team-members/${memberId}/tax-permissions`,
        method: "PUT",
        body: { property_ids: propertyIds },
      }),
      transformResponse: unwrap,
      invalidatesTags: ["TaxPermission", "EtimsScope"],
    }),
  }),
});

export const {
  useGetEtimsSettingsQuery,
  useUpdateEtimsSettingsMutation,
  useUpdatePropertyEtimsSettingsMutation,
  useGetEtimsScopeQuery,
  useGetPropertyOwnersQuery,
  useCreatePropertyOwnerMutation,
  useUpdatePropertyOwnerMutation,
  useSetPaymentEtimsMutation,
  useClearPaymentEtimsMutation,
  useSetPayoutEtimsMutation,
  useBulkEtimsMutation,
  useGetEtimsRegisterQuery,
  useGetKraMonthlyReportQuery,
  useGetTaxPermissionsQuery,
  useSetTaxPermissionsMutation,
} = etimsApiSlice;
