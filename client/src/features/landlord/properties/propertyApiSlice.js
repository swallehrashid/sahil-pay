import { apiSlice } from "@/store/apiSlice";

// §4.6 — mirrors server/routes/property_routes.py.
export const propertyApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getProperties: builder.query({
      query: (params) => ({ url: "/properties", params }),
      providesTags: ["Property"],
    }),
    getProperty: builder.query({
      query: (id) => `/properties/${id}`,
      providesTags: (result, error, id) => [{ type: "Property", id }],
    }),
    createProperty: builder.mutation({
      query: (body) => ({ url: "/properties", method: "POST", body }),
      invalidatesTags: ["Property"],
    }),
    updateProperty: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/properties/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Property", id }, "Property"],
    }),
    deleteProperty: builder.mutation({
      query: (id) => ({ url: `/properties/${id}`, method: "DELETE" }),
      invalidatesTags: ["Property"],
    }),
    addUnitsToProperty: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/properties/${id}/units`, method: "POST", body }),
      invalidatesTags: ["Property", "Unit"],
    }),
  }),
});

export const {
  useGetPropertiesQuery,
  useGetPropertyQuery,
  useCreatePropertyMutation,
  useUpdatePropertyMutation,
  useDeletePropertyMutation,
  useAddUnitsToPropertyMutation,
} = propertyApiSlice;
