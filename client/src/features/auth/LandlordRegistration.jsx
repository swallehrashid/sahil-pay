import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Mail, Lock, Building2, Phone, Gift, ChevronDown } from "lucide-react";
import clsx from "clsx";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useRegisterMutation } from "./authApiSlice";
import { AUTH_ROUTES } from "@/config/routePaths";
import { isRequired, isValidEmail, isValidPhone } from "@/utils/validators";
import { captureReferralFromUrl, getStoredReferral } from "@/utils/referralStorage";

// Self-signup — creates users + landlords and starts the free trial.
export default function LandlordRegistration() {
  const navigate = useNavigate();
  const [registerMutation, { isLoading }] = useRegisterMutation();
  // A visitor can land here directly via a shared ?ref= link (bypassing
  // PublicLayout's capture), or arrive with a code already stored from
  // browsing Pricing/Home first — captured once, synchronously, in this lazy
  // initializer (no effect needed for a one-time external-storage read).
  const [form, setForm] = useState(() => {
    captureReferralFromUrl();
    return { company_name: "", email: "", phone: "", password: "", referral_code: getStoredReferral() };
  });
  const [errors, setErrors] = useState({});
  const [showReferral, setShowReferral] = useState(() => Boolean(getStoredReferral()));

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.company_name)) nextErrors.company_name = "Company name is required";
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isValidPhone(form.phone)) nextErrors.phone = "Enter a valid phone number";
    if (!form.password || form.password.length < 8) nextErrors.password = "Use at least 8 characters";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    try {
      await registerMutation(form).unwrap();
      toast("Account created — check your email to verify.", { type: "success" });
      navigate(AUTH_ROUTES.login);
    } catch {
      toast("Could not create your account. Try a different email.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Start your free trial" subtitle="Set up your SahilPay landlord account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Company name"
          leftIcon={<Building2 className="h-4 w-4" />}
          value={form.company_name}
          onChange={update("company_name")}
          error={errors.company_name}
          required
        />
        <Input
          label="Email"
          type="email"
          leftIcon={<Mail className="h-4 w-4" />}
          value={form.email}
          onChange={update("email")}
          error={errors.email}
          required
        />
        <Input label="Phone" leftIcon={<Phone className="h-4 w-4" />} value={form.phone} onChange={update("phone")} error={errors.phone} />
        <Input
          label="Password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.password}
          onChange={update("password")}
          error={errors.password}
          required
        />

        <div>
          <button
            type="button"
            onClick={() => setShowReferral((s) => !s)}
            className="flex items-center gap-1.5 text-sm text-white/50 transition-colors hover:text-white/80"
          >
            <ChevronDown className={clsx("h-3.5 w-3.5 transition-transform", showReferral && "rotate-180")} />
            Have a referral code?
          </button>
          {showReferral && (
            <div className="mt-2">
              <Input
                leftIcon={<Gift className="h-4 w-4" />}
                placeholder="e.g. SAH-7K3F"
                value={form.referral_code}
                onChange={update("referral_code")}
              />
            </div>
          )}
        </div>

        <Button type="submit" className="w-full" isLoading={isLoading}>
          Create account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-white/50">
        Already have an account?{" "}
        <Link to={AUTH_ROUTES.login} className="text-secondary hover:underline">
          Log in
        </Link>
      </p>
    </AuthLayout>
  );
}
