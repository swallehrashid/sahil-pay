import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useAuth } from "@/hooks/useAuth";
import { AUTH_ROUTES } from "@/config/routePaths";
import { roleHomePath } from "@/routes/roleRedirect";
import { env } from "@/config/env";
import GoogleSignInButton from "./GoogleSignInButton";
import { useCompleteProfileMutation } from "../authApiSlice";

const ACCOUNT_TYPES = [
  { value: "landlord", label: "Individual landlord" },
  { value: "property_management", label: "Property management company" },
  { value: "gated_community", label: "Gated community" },
];

/**
 * The whole "Continue with Google" experience behind one drop-in component:
 * the branded button, the 2FA challenge if the account has it on, and the
 * one-step "finish your details" modal a brand-new one-click signup still
 * needs. Pages only choose the intent ("landlord" or "affiliate") and, on the
 * register page, pass a referral code.
 */
export default function GoogleAuthFlow({ intent = "landlord", getExtra, text = "continue_with" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [completeProfile, { isLoading: saving }] = useCompleteProfileMutation();

  const [pending2fa, setPending2fa] = useState(null);
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);

  // When a fresh Google account still needs its essentials.
  const [complete, setComplete] = useState(null); // { role }
  const [company, setCompany] = useState("");
  const [accountType, setAccountType] = useState("landlord");
  const [phone, setPhone] = useState("");

  const goHome = (role) => {
    const redirectTo = location.state?.from?.pathname || roleHomePath(role);
    navigate(redirectTo, { replace: true });
  };

  // Signed-in tokens in hand → store them and route onward.
  const landAuthenticated = (result) => {
    login({ accessToken: result.access_token, refreshToken: result.refresh_token, role: result.role });
    if (result.must_change_password) return navigate(AUTH_ROUTES.changePassword, { replace: true });
    if (result.needs_2fa_setup) return navigate(AUTH_ROUTES.twoFactorSetup, { replace: true });
    if (result.needs_profile_completion) {
      setComplete({ role: result.role });
      return;
    }
    goHome(result.role);
  };

  const onResult = (result) => {
    if (result.requires_2fa) {
      setPending2fa(result.pre_auth_token);
      return;
    }
    landAuthenticated(result);
  };

  const submitTwoFactor = async (e) => {
    e.preventDefault();
    setVerifying(true);
    try {
      const res = await fetch(`${env.apiBaseUrl}/auth/2fa/verify`, {
        method: "POST",
        headers: { Authorization: `Bearer ${pending2fa}`, "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.error || "That code isn't right.");
      login({ accessToken: result.access_token, refreshToken: result.refresh_token, role: result.role });
      goHome(result.role);
    } catch (err) {
      toast(err.message, { type: "error" });
      setCode("");
    } finally {
      setVerifying(false);
    }
  };

  const submitProfile = async () => {
    const role = complete.role;
    try {
      if (role === "affiliate") {
        await completeProfile({ phone }).unwrap();
      } else {
        await completeProfile({ company_name: company, account_type: accountType }).unwrap();
      }
      toast("All set — welcome to Sahil Pay!", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save your details — you can finish this in Settings.", { type: "error" });
    } finally {
      setComplete(null);
      goHome(role);
    }
  };

  // 2FA challenge takes over the whole panel — one obvious next action.
  if (pending2fa) {
    return (
      <form onSubmit={submitTwoFactor} className="mt-6 space-y-4">
        <div className="flex justify-center py-2">
          <ShieldCheck className="h-8 w-8 text-secondary" />
        </div>
        <p className="text-center text-sm text-white/70">
          Enter the 6-digit code from your authenticator app to finish signing in.
        </p>
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
        <button
          type="button"
          onClick={() => { setPending2fa(null); setCode(""); }}
          className="w-full text-center text-xs text-white/40 transition-colors hover:text-white/70"
        >
          Back
        </button>
      </form>
    );
  }

  const isAffiliate = complete?.role === "affiliate";

  return (
    <>
      <GoogleSignInButton intent={intent} getExtra={getExtra} onResult={onResult} text={text} />

      <Modal
        isOpen={Boolean(complete)}
        onClose={() => { const r = complete?.role; setComplete(null); goHome(r); }}
        title="One quick thing"
        footer={
          <>
            <Button variant="ghost" onClick={() => { const r = complete?.role; setComplete(null); goHome(r); }}>
              Skip for now
            </Button>
            <Button
              onClick={submitProfile}
              isLoading={saving}
              disabled={isAffiliate ? !phone : !company.trim()}
            >
              Save and continue
            </Button>
          </>
        }
      >
        {isAffiliate ? (
          <div className="space-y-4">
            <p className="text-sm text-white/70">
              Add the phone number your affiliate payouts should go to.
            </p>
            <Input
              label="Payout phone (M-Pesa)"
              placeholder="07XX XXX XXX"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
            />
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-white/70">
              Tell us your business name so your invoices and receipts are branded correctly.
            </p>
            <Input
              label="Company name"
              placeholder="e.g. Riverside Apartments"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
            />
            <Select
              label="Account type"
              options={ACCOUNT_TYPES}
              value={accountType}
              onChange={(e) => setAccountType(e.target.value)}
            />
          </div>
        )}
      </Modal>
    </>
  );
}
