import { apiSlice } from "@/store/apiSlice";

// §4.20 — mirrors server/routes/team_routes.py (the landlord's admin side of team members).
export const teamApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // The reports that can be granted individually. Served by the backend so
    // this list cannot drift from what the report routes actually gate.
    getReportCatalogue: builder.query({
      query: () => "/team/report-catalogue",
    }),
    getTeamMembers: builder.query({
      query: (params) => ({ url: "/team", params }),
      providesTags: ["TeamMember"],
    }),
    // The role-preset catalogue (owner / caretaker / accountant / secretary).
    // Served by the backend so the two definitions cannot drift apart.
    getTeamPresets: builder.query({
      query: () => "/team/presets",
      transformResponse: (response) => response.presets ?? [],
      providesTags: ["TeamPreset"],
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
  useGetReportCatalogueQuery,
  useGetTeamMembersQuery,
  useGetTeamPresetsQuery,
  useGetTeamMemberQuery,
  useCreateTeamMemberMutation,
  useUpdateTeamMemberMutation,
  useDeleteTeamMemberMutation,
  useUpdateTeamMemberPermissionsMutation,
  useUpdateTeamMemberPropertyAccessMutation,
} = teamApiSlice;
