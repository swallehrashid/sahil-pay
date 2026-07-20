import { apiSlice } from "@/store/apiSlice";

// §4.7 — mirrors server/routes/unit_routes.py.
export const unitApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getUnits: builder.query({
      query: (params) => ({ url: "/units", params }),
      providesTags: ["Unit"],
    }),
    getUnit: builder.query({
      query: (id) => `/units/${id}`,
      providesTags: (result, error, id) => [{ type: "Unit", id }],
    }),
    createUnit: builder.mutation({
      query: (body) => ({ url: "/units", method: "POST", body }),
      invalidatesTags: ["Unit", "Property"],
    }),
    updateUnit: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/units/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Unit", id }, "Unit"],
    }),
    deleteUnit: builder.mutation({
      query: (id) => ({ url: `/units/${id}`, method: "DELETE" }),
      invalidatesTags: ["Unit", "Property"],
    }),
  }),
});

export const { useGetUnitsQuery, useGetUnitQuery, useCreateUnitMutation, useUpdateUnitMutation, useDeleteUnitMutation } = unitApiSlice;
