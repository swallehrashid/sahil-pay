import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Mail, Lock } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useLoginMutation } from "./authApiSlice";
import { useAuth } from "@/hooks/useAuth";
import { AUTH_ROUTES } from "@/config/routePaths";
import { roleHomePath } from "@/routes/roleRedirect";
import { isRequired, isValidEmail } from "@/utils/validators";

// Email + password login for admin, landlord/PM and team member roles.
export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [loginMutation, { isLoading }] = useLoginMutation();
  const [form, setForm] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState({});

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isRequired(form.password)) nextErrors.password = "Password is required";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    try {
      const result = await loginMutation(form).unwrap();
      login({
        accessToken: result.access_token,
        refreshToken: result.refresh_token,
        role: result.role,
      });
      const redirectTo = location.state?.from?.pathname || roleHomePath(result.role);
      navigate(redirectTo, { replace: true });
    } catch {
      toast("Invalid email or password.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Welcome back" subtitle="Log in to your SahilPay account">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Email"
          type="email"
          leftIcon={<Mail className="h-4 w-4" />}
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          error={errors.email}
          required
        />
        <Input
          label="Password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          error={errors.password}
          required
        />
        <div className="flex justify-end">
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
