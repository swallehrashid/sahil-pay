import { apiSlice } from "@/store/apiSlice";

// §7.2 — mirrors server/routes/admin_pricing_routes.py.
export const adminPricingApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPackages: builder.query({
      query: () => "/admin/pricing/packages",
      providesTags: ["Package"],
    }),
    getPackageAnalytics: builder.query({
      query: ({ id, ...params }) => ({ url: `/admin/pricing/packages/${id}/analytics`, params }),
      providesTags: (result, error, arg) => [{ type: "Package", id: arg?.id }],
    }),
    createPackage: builder.mutation({
      query: (body) => ({ url: "/admin/pricing/packages", method: "POST", body }),
      invalidatesTags: ["Package"],
    }),
    updatePackage: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/pricing/packages/${id}`, method: "PUT", body }),
      invalidatesTags: ["Package"],
    }),
    deletePackage: builder.mutation({
      query: (id) => ({ url: `/admin/pricing/packages/${id}`, method: "DELETE" }),
      invalidatesTags: ["Package"],
    }),
    updateLandlordPerUnitPrice: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/pricing/landlords/${id}/per-unit-price`, method: "PUT", body }),
      invalidatesTags: ["AdminLandlord"],
    }),
    // #16 — landlord billing detail + admin overrides
    getLandlordBilling: builder.query({
      query: (id) => `/admin/pricing/landlords/${id}/billing`,
      providesTags: (r, e, id) => [{ type: "AdminLandlord", id }],
    }),
    updateLandlordBilling: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/pricing/landlords/${id}/billing`, method: "PUT", body }),
      invalidatesTags: (r, e, arg) => [{ type: "AdminLandlord", id: arg?.id }, "AdminLandlord", "Package"],
    }),
    // #17 — add a landlord to the Custom package at a negotiated per-unit price
    addLandlordToCustom: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/admin/pricing/landlords/${id}/custom`, method: "POST", body }),
      invalidatesTags: (r, e, arg) => [{ type: "AdminLandlord", id: arg?.id }, "AdminLandlord", "Package"],
    }),
  }),
});

export const {
  useGetPackagesQuery,
  useGetPackageAnalyticsQuery,
  useCreatePackageMutation,
  useUpdatePackageMutation,
  useDeletePackageMutation,
  useUpdateLandlordPerUnitPriceMutation,
  useGetLandlordBillingQuery,
  useUpdateLandlordBillingMutation,
  useAddLandlordToCustomMutation,
} = adminPricingApiSlice;
