import { apiSlice } from "@/store/apiSlice";

// §7.2 — mirrors server/routes/admin_pricing_routes.py.
export const adminPricingApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPackages: builder.query({
      query: () => "/admin/pricing/packages",
      providesTags: ["Package"],
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
  }),
});

export const {
  useGetPackagesQuery,
  useCreatePackageMutation,
  useUpdatePackageMutation,
  useDeletePackageMutation,
  useUpdateLandlordPerUnitPriceMutation,
} = adminPricingApiSlice;
