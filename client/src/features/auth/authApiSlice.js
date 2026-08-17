import { apiSlice } from "@/store/apiSlice";

// Password-based auth for the three non-tenant roles (admin, landlord/PM, team member).
// Mirrors server/routes/auth_routes.py exactly.
export const authApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    register: builder.mutation({
      query: (body) => ({ url: "/auth/register", method: "POST", body }),
    }),
    login: builder.mutation({
      query: (body) => ({ url: "/auth/login", method: "POST", body }),
      invalidatesTags: ["Me"],
    }),
    refresh: builder.mutation({
      query: (body) => ({ url: "/auth/refresh", method: "POST", body }),
    }),
    logout: builder.mutation({
      query: () => ({ url: "/auth/logout", method: "POST" }),
      invalidatesTags: ["Me"],
    }),
    verifyEmail: builder.mutation({
      query: (token) => ({ url: `/auth/verify-email/${token}`, method: "GET" }),
    }),
    resendVerification: builder.mutation({
      query: (body) => ({ url: "/auth/resend-verification", method: "POST", body }),
    }),
    forgotPassword: builder.mutation({
      query: (body) => ({ url: "/auth/forgot-password", method: "POST", body }),
    }),
    resetPassword: builder.mutation({
      query: (body) => ({ url: "/auth/reset-password", method: "POST", body }),
    }),
    teamActivate: builder.mutation({
      query: ({ token, ...body }) => ({ url: `/auth/team-activate/${token}`, method: "POST", body }),
    }),
    getMe: builder.query({
      query: () => "/auth/me",
      providesTags: ["Me"],
    }),
  }),
});

export const {
  useRegisterMutation,
  useLoginMutation,
  useRefreshMutation,
  useLogoutMutation,
  useVerifyEmailMutation,
  useResendVerificationMutation,
  useForgotPasswordMutation,
  useResetPasswordMutation,
  useTeamActivateMutation,
  useGetMeQuery,
} = authApiSlice;
