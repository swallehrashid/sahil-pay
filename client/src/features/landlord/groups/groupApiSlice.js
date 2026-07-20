import { apiSlice } from "@/store/apiSlice";

// §4.10 — mirrors server/routes/property_group_routes.py.
export const groupApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPropertyGroups: builder.query({
      query: () => "/property-groups",
      providesTags: ["PropertyGroup"],
    }),
    createPropertyGroup: builder.mutation({
      query: (body) => ({ url: "/property-groups", method: "POST", body }),
      invalidatesTags: ["PropertyGroup"],
    }),
    updatePropertyGroup: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/property-groups/${id}`, method: "PUT", body }),
      invalidatesTags: ["PropertyGroup"],
    }),
    deletePropertyGroup: builder.mutation({
      query: (id) => ({ url: `/property-groups/${id}`, method: "DELETE" }),
      invalidatesTags: ["PropertyGroup"],
    }),
    assignGroupManager: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/property-groups/${id}/assign-manager`, method: "POST", body }),
      invalidatesTags: ["PropertyGroup", "ManagerAssignment"],
    }),
  }),
});

export const {
  useGetPropertyGroupsQuery,
  useCreatePropertyGroupMutation,
  useUpdatePropertyGroupMutation,
  useDeletePropertyGroupMutation,
  useAssignGroupManagerMutation,
} = groupApiSlice;
