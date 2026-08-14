import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { AUTH_ROUTES } from "@/config/routePaths";
import { env } from "@/config/env";
import { getAccessToken } from "@/utils/tokenStorage";
import Input from "@/components/ui/Input";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import {
  useGetAccountSettingsQuery,
  useUpdateAccountSettingsMutation,
  useChangePasswordMutation,
} from "./settingsApiSlice";

// §4.17 — profile, signature, and a DEDICATED change-password pipeline.
// The password is never displayed or pre-filled anywhere (the server never
// returns it); changing it is its own verified flow (current → new → confirm),
// separate from saving the profile.
export default function AccountSettings() {
  const { data, isLoading } = useGetAccountSettingsQuery();
  const [updateAccount, { isLoading: isSaving }] = useUpdateAccountSettingsMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    setForm(data);
  }

  const [signature, setSignature] = useState(null);

  if (isLoading || !form) return <SkeletonForm fields={6} />;

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleProfileSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateAccount({ ...form, signature }).unwrap();
      toast("Account updated.", { type: "success" });
    } catch {
      toast("Could not update your account.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <form onSubmit={handleProfileSubmit} className="space-y-6">
        <div className="glass space-y-4 p-6">
          <h3 className="text-base font-medium text-white">Profile</h3>
          <div className="grid grid-cols-2 gap-4">
            <Input label="Username" value={form.username ?? ""} onChange={update("username")} />
            <Input label="Email" type="email" value={form.email ?? ""} onChange={update("email")} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Input label="First name" value={form.first_name ?? ""} onChange={update("first_name")} />
            <Input label="Last name" value={form.last_name ?? ""} onChange={update("last_name")} />
          </div>
          <FileUpload label="Signature" accept="image/*" value={signature} onChange={setSignature} hint="Appears on statements and receipts" />
        </div>

        <div className="flex justify-end">
          <Button type="submit" isLoading={isSaving}>
            Save account
          </Button>
        </div>
      </form>

      <ChangePasswordCard />
      <TwoFactorCard />
    </div>
  );
}

// Two-factor is optional for landlords (mandatory for admins, who are routed
// to enrolment at login instead). Without an entry point here a landlord has
// no way to opt in at all, so this card is the only door to the feature for
// them. Status is read from the server rather than assumed, so a landlord who
// enrolled on another device sees the truth.
function TwoFactorCard() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${env.apiBaseUrl}/auth/2fa/status`, {
          headers: { Authorization: `Bearer ${getAccessToken()}` },
        });
        const data = await res.json().catch(() => ({}));
        if (!cancelled && res.ok) setStatus(data);
      } catch {
        // Leave the card in its loading state rather than claiming 2FA is off
        // when we simply could not ask.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="glass space-y-4 p-6">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-secondary-200" />
        <h3 className="text-base font-medium text-white">Two-factor authentication</h3>
      </div>
      <p className="text-sm text-white/50">
        Ask for a 6-digit code from your phone at sign-in, so a stolen password
        on its own isn't enough to get into your account.
      </p>

      {status?.enabled ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs text-emerald-300">
            On
          </span>
          <span className="text-sm text-white/45">
            {status.backup_codes_remaining} backup code
            {status.backup_codes_remaining === 1 ? "" : "s"} left
          </span>
        </div>
      ) : (
        <Link to={AUTH_ROUTES.twoFactorSetup}>
          <Button type="button" variant="secondary">Turn on two-factor</Button>
        </Link>
      )}
    </div>
  );
}

// Dedicated change-password pipeline: verify current password, require a new
// password + matching confirmation, all in a self-contained form. Fields are
// always masked (type="password"); nothing is ever pre-filled from the server.
function ChangePasswordCard() {
  const [changePassword, { isLoading }] = useChangePasswordMutation();
  const [fields, setFields] = useState({ current_password: "", new_password: "", confirm_password: "" });

  const set = (key) => (e) => setFields((f) => ({ ...f, [key]: e.target.value }));

  const mismatch =
    fields.confirm_password.length > 0 && fields.new_password !== fields.confirm_password;
  const tooShort = fields.new_password.length > 0 && fields.new_password.length < 8;
  const canSubmit =
    fields.current_password &&
    fields.new_password.length >= 8 &&
    fields.new_password === fields.confirm_password;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    try {
      await changePassword(fields).unwrap();
      toast("Password changed successfully.", { type: "success" });
      setFields({ current_password: "", new_password: "", confirm_password: "" });
    } catch (err) {
      toast(err?.data?.error || "Could not change your password.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="glass space-y-4 p-6">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-secondary-200" />
        <h3 className="text-base font-medium text-white">Change password</h3>
      </div>
      <p className="text-sm text-white/50">
        For your security, your password is never shown. Enter your current password, then choose a new one.
      </p>
      <Input
        label="Current password"
        type="password"
        autoComplete="current-password"
        value={fields.current_password}
        onChange={set("current_password")}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          label="New password"
          type="password"
          autoComplete="new-password"
          value={fields.new_password}
          onChange={set("new_password")}
          error={tooShort ? "At least 8 characters." : undefined}
        />
        <Input
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          value={fields.confirm_password}
          onChange={set("confirm_password")}
          error={mismatch ? "Passwords don't match." : undefined}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" isLoading={isLoading} disabled={!canSubmit}>
          Change password
        </Button>
      </div>
    </form>
  );
}
