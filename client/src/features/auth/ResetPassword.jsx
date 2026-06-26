import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Lock } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useResetPasswordMutation } from "./authApiSlice";
import { AUTH_ROUTES } from "@/config/routePaths";

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();
  const [resetPassword, { isLoading }] = useResetPasswordMutation();
  const [form, setForm] = useState({ password: "", confirmPassword: "" });
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (form.password.length < 8) {
      setError("Use at least 8 characters");
      return;
    }
    if (form.password !== form.confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    setError("");
    try {
      await resetPassword({ token, password: form.password }).unwrap();
      toast("Password updated — log in with your new password.", { type: "success" });
      navigate(AUTH_ROUTES.login);
    } catch {
      toast("This reset link is invalid or has expired.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Reset password">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="New password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          required
        />
        <Input
          label="Confirm password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.confirmPassword}
          onChange={(e) => setForm((f) => ({ ...f, confirmPassword: e.target.value }))}
          error={error}
          required
        />
        <Button type="submit" className="w-full" isLoading={isLoading}>
          Update password
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-white/50">
        <Link to={AUTH_ROUTES.login} className="text-secondary hover:underline">
          Back to login
        </Link>
      </p>
    </AuthLayout>
  );
}
