import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Phone } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import OtpInput from "./components/OtpInput";
import { useOtpRequestMutation, useOtpVerifyMutation, useOtpResendMutation } from "./otpApiSlice";
import { useAuth } from "@/hooks/useAuth";
import { TENANT_ROUTES } from "@/config/routePaths";
import { isRequired } from "@/utils/validators";

// Passwordless tenant login (phone/email → OTP → verify). This is the deep-link target
// from invoice SMS/email reminders.
export default function TenantOtpLogin() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [otpRequest, { isLoading: isRequesting }] = useOtpRequestMutation();
  const [otpVerify, { isLoading: isVerifying }] = useOtpVerifyMutation();
  const [otpResend] = useOtpResendMutation();

  const [step, setStep] = useState("identify");
  const [identifier, setIdentifier] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  const handleRequest = async (e) => {
    e.preventDefault();
    if (!isRequired(identifier)) {
      setError("Enter your phone or email");
      return;
    }
    setError("");
    try {
      await otpRequest({ identifier }).unwrap();
      setStep("verify");
    } catch {
      toast("We couldn't find a tenant account with that detail.", { type: "error" });
    }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    if (code.length < 6) {
      setError("Enter the 6-digit code");
      return;
    }
    setError("");
    try {
      const result = await otpVerify({ identifier, code }).unwrap();
      login({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        role: result.role,
      });
      navigate(TENANT_ROUTES.dashboard, { replace: true });
    } catch {
      toast("That code is invalid or has expired.", { type: "error" });
    }
  };

  const handleResend = async () => {
    try {
      await otpResend({ identifier }).unwrap();
      toast("A new code has been sent.", { type: "success" });
    } catch {
      toast("Could not resend the code.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Tenant login" subtitle="No password needed — just a one-time code">
      {step === "identify" ? (
        <form onSubmit={handleRequest} className="space-y-4">
          <Input
            label="Phone or email"
            leftIcon={<Phone className="h-4 w-4" />}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            error={error}
            placeholder="0712 345 678 or you@example.com"
            required
          />
          <Button type="submit" className="w-full" isLoading={isRequesting}>
            Send code
          </Button>
        </form>
      ) : (
        <form onSubmit={handleVerify} className="space-y-5">
          <p className="text-center text-sm text-white/50">Enter the code sent to {identifier}</p>
          <OtpInput value={code} onChange={setCode} />
          {error && <p className="text-center text-xs text-secondary-300">{error}</p>}
          <Button type="submit" className="w-full" isLoading={isVerifying}>
            Verify &amp; log in
          </Button>
          <button
            type="button"
            onClick={handleResend}
            className="block w-full text-center text-sm text-secondary hover:underline"
          >
            Resend code
          </button>
        </form>
      )}
    </AuthLayout>
  );
}
