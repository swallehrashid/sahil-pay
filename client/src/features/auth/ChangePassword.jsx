import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { Lock } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useAuth } from "@/hooks/useAuth";
import { setCredentials } from "@/features/auth/authSlice";
import { useUpdateAccountSettingsMutation } from "@/features/landlord/settings/settingsApiSlice";
import { roleHomePath } from "@/routes/roleRedirect";

// Forced password change. Reached right after a team member's first login on their
// system-issued temporary password (login returns must_change_password=true, and
// ProtectedRoutes routes them here until they set their own password). Also usable
// voluntarily by any signed-in user. On success /me refetches (mutation invalidates
// the "Me" tag), must_change_password clears, and we send them to their portal.
export default function ChangePassword() {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { role, user } = useAuth();
  const [updateAccount, { isLoading }] = useUpdateAccountSettingsMutation();
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const next = {};
    if (!form.current_password) next.current_password = "Enter your current (temporary) password";
    if (!form.new_password || form.new_password.length < 8) next.new_password = "Use at least 8 characters";
    if (form.new_password && form.new_password === form.current_password) next.new_password = "Choose a password different from the temporary one";
    if (form.confirm !== form.new_password) next.confirm = "Passwords don't match";
    setErrors(next);
    if (Object.keys(next).length) return;

    try {
      await updateAccount({
        current_password: form.current_password,
        new_password: form.new_password,
      }).unwrap();
      // Clear the flag in the store immediately so the ProtectedRoutes guard doesn't
      // bounce us back here while the invalidated /me query is still refetching.
      if (user) dispatch(setCredentials({ user: { ...user, must_change_password: false } }));
      toast("Password updated. Welcome to SahilPay!", { type: "success" });
      navigate(roleHomePath(role), { replace: true });
    } catch (err) {
      toast(err?.data?.error || "Could not update your password. Check your current password and try again.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Set your password" subtitle="Choose a new password to finish setting up your account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Current (temporary) password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.current_password}
          onChange={update("current_password")}
          error={errors.current_password}
          required
        />
        <Input
          label="New password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.new_password}
          onChange={update("new_password")}
          error={errors.new_password}
          hint="At least 8 characters"
          required
        />
        <Input
          label="Confirm new password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.confirm}
          onChange={update("confirm")}
          error={errors.confirm}
          required
        />
        <Button type="submit" className="w-full" isLoading={isLoading}>
          Save new password
        </Button>
      </form>
    </AuthLayout>
  );
}
