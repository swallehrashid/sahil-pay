import { apiSlice } from "@/store/apiSlice";

// §4.20 — mirrors server/routes/team_routes.py (the landlord's admin side of team members).
export const teamApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getTeamMembers: builder.query({
      query: () => "/team",
      providesTags: ["TeamMember"],
    }),
    getTeamMember: builder.query({
      query: (id) => `/team/${id}`,
      providesTags: (result, error, id) => [{ type: "TeamMember", id }],
    }),
    createTeamMember: builder.mutation({
      query: (body) => ({ url: "/team", method: "POST", body }),
      invalidatesTags: ["TeamMember"],
    }),
    updateTeamMember: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/team/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "TeamMember", id }, "TeamMember"],
    }),
    deleteTeamMember: builder.mutation({
      query: (id) => ({ url: `/team/${id}`, method: "DELETE" }),
      invalidatesTags: ["TeamMember"],
    }),
    updateTeamMemberPermissions: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/team/${id}/permissions`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "TeamMember", id }, "TeamMemberPermission"],
    }),
    updateTeamMemberPropertyAccess: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/team/${id}/property-access`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "TeamMember", id }],
    }),
  }),
});

export const {
  useGetTeamMembersQuery,
  useGetTeamMemberQuery,
  useCreateTeamMemberMutation,
  useUpdateTeamMemberMutation,
  useDeleteTeamMemberMutation,
  useUpdateTeamMemberPermissionsMutation,
  useUpdateTeamMemberPropertyAccessMutation,
} = teamApiSlice;
