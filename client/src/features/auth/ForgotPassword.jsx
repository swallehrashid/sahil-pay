import { useState } from "react";
import { Link } from "react-router-dom";
import { Mail } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useForgotPasswordMutation } from "./authApiSlice";
import { AUTH_ROUTES } from "@/config/routePaths";
import { isRequired, isValidEmail } from "@/utils/validators";

export default function ForgotPassword() {
  const [forgotPassword, { isLoading }] = useForgotPasswordMutation();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isRequired(email) || !isValidEmail(email)) {
      setError("Enter a valid email");
      return;
    }
    setError("");
    try {
      await forgotPassword({ email }).unwrap();
      setSent(true);
    } catch {
      toast("Could not send reset link. Try again.", { type: "error" });
    }
  };

  return (
    <AuthLayout title="Forgot password" subtitle="We'll email you a reset link">
      {sent ? (
        <p className="text-center text-sm text-white/70">
          If an account exists for {email}, a reset link is on its way.
        </p>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input
            label="Email"
            type="email"
            leftIcon={<Mail className="h-4 w-4" />}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={error}
            required
          />
          <Button type="submit" className="w-full" isLoading={isLoading}>
            Send reset link
          </Button>
        </form>
      )}
      <p className="mt-6 text-center text-sm text-white/50">
        <Link to={AUTH_ROUTES.login} className="text-secondary hover:underline">
          Back to login
        </Link>
      </p>
    </AuthLayout>
  );
}
