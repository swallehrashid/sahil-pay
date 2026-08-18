import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Mail, Lock, MailCheck, ShieldCheck } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useLoginMutation, useResendVerificationMutation } from "./authApiSlice";
import { useAuth } from "@/hooks/useAuth";
import { AUTH_ROUTES } from "@/config/routePaths";
import { roleHomePath } from "@/routes/roleRedirect";
import { isRequired, isValidEmail } from "@/utils/validators";
import { env } from "@/config/env";

// Email + password login for admin, landlord/PM and team member roles.
export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [loginMutation, { isLoading }] = useLoginMutation();
  const [form, setForm] = useState({ email: "", password: "", remember_me: false });
  const [errors, setErrors] = useState({});
  // Set when the password was right but a second factor is still owed.
  // The pre-auth token it holds opens nothing except /auth/2fa/verify.
  const [pending2fa, setPending2fa] = useState(null);
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  // Right password, unconfirmed address — offer a fresh link rather than a
  // refusal the person cannot act on.
  const [needsVerification, setNeedsVerification] = useState(false);
  const [resendVerification, { isLoading: resending }] = useResendVerificationMutation();

  const handleResend = async () => {
    try {
      await resendVerification({ email: form.email }).unwrap();
    } catch {
      // The endpoint answers the same way whether or not the address exists, so
      // there is nothing here worth telling the user apart from the success note.
    }
    toast(
      "If that address needs verifying, a new link is on its way. Check your inbox and spam folder.",
      { type: "info" }
    );
  };

  /** Finish a 2FA sign-in: swap the pre-auth token + code for real tokens. */
  const completeTwoFactor = async (e) => {
    e.preventDefault();
    setVerifying(true);
    try {
      const res = await fetch(`${env.apiBaseUrl}/auth/2fa/verify`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${pending2fa}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ code }),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || "That code isn't right.");

      login({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        role: result.role,
      });
      if (result.used_backup_code) {
        toast(
          `Signed in with a backup code — ${result.backup_codes_remaining} left.`,
          { type: "info" }
        );
      }
      navigate(roleHomePath(result.role), { replace: true });
    } catch (err) {
      toast(err.message, { type: "error" });
      setCode("");
    } finally {
      setVerifying(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isRequired(form.password)) nextErrors.password = "Password is required";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    try {
      const result = await loginMutation(form).unwrap();

      // Password correct, second factor still owed.
      if (result.requires_2fa) {
        setPending2fa(result.pre_auth_token);
        return;
      }

      login({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        role: result.role,
      });
      // Team members (and anyone on a system-issued temporary password) must set a
      // real password before they can use the app.
      if (result.must_change_password) {
        navigate(AUTH_ROUTES.changePassword, { replace: true });
        return;
      }
      // Enrolled users are challenged above (requires_2fa). This is the other
      // half: an admin who has never enrolled signs in normally but every
      // /api/admin/* route refuses them with `2fa_required`, so send them
      // straight to enrolment rather than to a portal that cannot load.
      if (result.needs_2fa_setup) {
        navigate(AUTH_ROUTES.twoFactorSetup, { replace: true });
        return;
      }
      const redirectTo = location.state?.from?.pathname || roleHomePath(result.role);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      // The password was right but the address was never confirmed. A toast
      // alone would be a dead end — the link is often long expired or was never
      // received — so switch the form into a state that can send a fresh one.
      if (err?.status === 403 && err?.data?.needs_verification) {
        setNeedsVerification(true);
        return;
      }
      // Surface the ACTUAL failure instead of always blaming the credentials —
      // a network/CORS failure (status "FETCH_ERROR", no HTTP status) is a very
      // different problem from a genuine 401, and showing the same message for
      // both hides server-down / CORS issues during local testing.
      let message;
      if (err?.status === "FETCH_ERROR") {
        message = "Cannot reach the server. Is the backend running on :5000?";
      } else if (err?.status === 401) {
        message = "Invalid email or password.";
      } else if (err?.status === 429) {
        message = "Too many attempts. Please wait a moment and try again.";
      } else {
        message = err?.data?.error || err?.data?.message || "Login failed. Please try again.";
      }
      toast(message, { type: "error" });
    }
  };

  // The second-factor challenge replaces the password form entirely — showing
  // both at once invites people to retype their password into the code box.
  if (pending2fa) {
    return (
      <AuthLayout
        title="One more step"
        subtitle="Enter the code from your authenticator app"
      >
        <form onSubmit={completeTwoFactor} className="space-y-4">
          <div className="flex justify-center py-2">
            <ShieldCheck className="h-8 w-8 text-secondary" />
          </div>
          <Input
            label="6-digit code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\s/g, "").slice(0, 20))}
            placeholder="123456"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            required
          />
          <Button type="submit" className="w-full" isLoading={verifying} disabled={!code}>
            Verify and sign in
          </Button>
          <p className="text-center text-xs leading-relaxed text-white/45">
            Lost your phone? Enter one of your backup codes instead — each works
            once.
          </p>
          <button
            type="button"
            onClick={() => { setPending2fa(null); setCode(""); }}
            className="w-full text-center text-xs text-white/40 transition-colors hover:text-white/70"
          >
            Back to sign-in
          </button>
        </form>
      </AuthLayout>
    );
  }

  // Same reasoning as the 2FA challenge above: replace the form rather than
  // appending a banner to it, so there is one obvious next action.
  if (needsVerification) {
    return (
      <AuthLayout
        title="Confirm your email"
        subtitle="Your password was correct — this address just needs verifying"
      >
        <div className="space-y-4">
          <div className="flex justify-center py-2">
            <MailCheck className="h-8 w-8 text-secondary" />
          </div>
          <p className="text-center text-sm leading-relaxed text-white/70">
            We sent a verification link to{" "}
            <span className="text-white">{form.email}</span>. Click it once and
            you'll be able to sign in.
          </p>
          <Button className="w-full" onClick={handleResend} isLoading={resending}>
            Send me a new link
          </Button>
          <button
            type="button"
            onClick={() => setNeedsVerification(false)}
            className="w-full text-center text-xs text-white/40 transition-colors hover:text-white/70"
          >
            Back to sign-in
          </button>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Welcome back" subtitle="Log in to your Sahil Pay account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          leftIcon={<Mail className="h-4 w-4" />}
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          error={errors.email}
          required
        />
        {/* autoComplete matters more than usual here: team members arrive with a
            12-character system-generated temp password they are meant to paste. */}
        <Input
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          error={errors.password}
          required
        />
        <div className="flex items-center justify-between gap-3">
          <Checkbox
            label="Keep me logged in (24 hours)"
            checked={form.remember_me}
            onChange={(e) => setForm((f) => ({ ...f, remember_me: e.target.checked }))}
          />
          <Link to={AUTH_ROUTES.forgotPassword} className="text-sm text-secondary hover:underline">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" className="w-full" isLoading={isLoading}>
          Log in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-white/50">
        New landlord?{" "}
        <Link to={AUTH_ROUTES.register} className="text-secondary hover:underline">
          Create an account
        </Link>
      </p>
      <p className="mt-2 text-center text-sm text-white/50">
        Tenant?{" "}
        <Link to={AUTH_ROUTES.tenantLogin} className="text-secondary hover:underline">
          Log in with OTP
        </Link>
      </p>
    </AuthLayout>
  );
}
