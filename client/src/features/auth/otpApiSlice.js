import { apiSlice } from "@/store/apiSlice";

// Passwordless OTP login for tenants only — kept separate from authApiSlice because it
// is channel-specific (SMS/email) and heavily rate-limited server-side.
export const otpApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    otpRequest: builder.mutation({
      query: (body) => ({ url: "/otp/request", method: "POST", body }),
    }),
    otpVerify: builder.mutation({
      query: (body) => ({ url: "/otp/verify", method: "POST", body }),
      invalidatesTags: ["Me"],
    }),
    otpResend: builder.mutation({
      query: (body) => ({ url: "/otp/resend", method: "POST", body }),
    }),
  }),
});

export const { useOtpRequestMutation, useOtpVerifyMutation, useOtpResendMutation } = otpApiSlice;
