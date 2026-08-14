import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AuthLayout from "@/components/layout/AuthLayout";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { useAuth } from "@/hooks/useAuth";
import { env } from "@/config/env";
import { getAccessToken } from "@/utils/tokenStorage";
import { roleHomePath } from "@/routes/roleRedirect";
import TwoFactorSetup from "./TwoFactorSetup";

// The enrolment interstitial for two-factor authentication.
//
// Admins are sent here by Login.jsx when the server answers `needs_2fa_setup`:
// they hold a real token, but decorators.require_role refuses every
// /api/admin/* route with `2fa_required` until they enrol, so the admin portal
// is unusable until this is finished. Landlords may also reach it voluntarily
// from Settings → Account.
//
// The page asks the server whether 2FA is required rather than trusting the
// route it was reached by — someone who navigates here directly, or who has
// already enrolled in another tab, must not be shown a second enrolment.
export default function TwoFactorSetupPage() {
  const navigate = useNavigate();
  const { role } = useAuth();
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${env.apiBaseUrl}/auth/2fa/status`, {
          headers: { Authorization: `Bearer ${getAccessToken()}` },
        });
        const data = await res.json().catch(() => ({}));
        if (cancelled) return;
        // Already enrolled — there is nothing to do here, so don't strand them
        // on a dead-end screen.
        if (res.ok && data.enabled) {
          navigate(roleHomePath(role), { replace: true });
          return;
        }
        setStatus(res.ok ? data : { required: false });
      } catch {
        // A network failure shouldn't trap the user on a blank screen; fall
        // back to the optional wording and let the enrolment call surface any
        // real error.
        if (!cancelled) setStatus({ required: false });
      }
    })();
    return () => { cancelled = true; };
  }, [navigate, role]);

  if (!status) {
    return (
      <AuthLayout title="Two-factor authentication" subtitle="Checking your account…">
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      </AuthLayout>
    );
  }

  const required = Boolean(status.required);

  const handleComplete = () => {
    toast("Two-factor authentication is on.", { type: "success" });
    navigate(roleHomePath(role), { replace: true });
  };

  return (
    <AuthLayout
      title={required ? "One more step before you continue" : "Two-factor authentication"}
      subtitle={required
        ? "Your account needs a second factor before the portal opens."
        : "Add a second step to your sign-in."}
    >
      <TwoFactorSetup required={required} onComplete={handleComplete} />
      {!required && (
        <button
          type="button"
          onClick={() => navigate(roleHomePath(role), { replace: true })}
          className="mt-4 w-full text-center text-sm text-white/45 transition-colors hover:text-white"
        >
          Not now
        </button>
      )}
    </AuthLayout>
  );
}
