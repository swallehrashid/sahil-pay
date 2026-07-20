import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { Lock, User } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useTeamActivateMutation } from "./authApiSlice";
import { AUTH_ROUTES } from "@/config/routePaths";

// Team member sets a username + password from the activation email link.
export default function TeamActivation() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [teamActivate, { isLoading }] = useTeamActivateMutation();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (form.password.length < 8) {
      setError("Use at least 8 characters");
      return;
    }
    setError("");
    try {
      await teamActivate({ token, ...form }).unwrap();
      toast("Account activated — log in to continue.", { type: "success" });
      navigate(AUTH_ROUTES.login);
    } catch {
      toast("This activation link is invalid or has expired.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Activate your account" subtitle="Set a username and password to get started">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="Username"
          leftIcon={<User className="h-4 w-4" />}
          value={form.username}
          onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
          required
        />
        <Input
          label="Password"
          type="password"
          leftIcon={<Lock className="h-4 w-4" />}
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          error={error}
          required
        />
        <Button type="submit" className="w-full" isLoading={isLoading}>
          Activate account
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
