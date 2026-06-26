import { apiSlice } from "@/store/apiSlice";

// Section 5 — mirrors server/routes/teammember_routes.py. Only the team member's OWN
// session concerns live here; data routes (invoices/payments/etc.) are the landlord
// routes re-mounted under permission guards, not duplicated.
export const teamMemberApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getMyPermissions: builder.query({
      query: () => "/team-member/me/permissions",
      providesTags: ["TeamMemberPermission"],
    }),
    getMyPropertyAccess: builder.query({
      query: () => "/team-member/me/property-access",
      providesTags: ["TeamMember"],
    }),
    getMyProfile: builder.query({
      query: () => "/team-member/me/profile",
      providesTags: ["TeamMember"],
    }),
    updateMyProfile: builder.mutation({
      query: (body) => ({ url: "/team-member/me/profile", method: "PUT", body }),
      invalidatesTags: ["TeamMember", "Me"],
    }),
  }),
});

export const { useGetMyPermissionsQuery, useGetMyPropertyAccessQuery, useGetMyProfileQuery, useUpdateMyProfileMutation } = teamMemberApiSlice;
