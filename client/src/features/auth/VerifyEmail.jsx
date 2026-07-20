import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { CheckCircle2, XCircle } from "lucide-react";
import AuthLayout from "@/components/layout/AuthLayout";
import Spinner from "@/components/ui/Spinner";
import Button from "@/components/ui/Button";
import { useVerifyEmailMutation } from "./authApiSlice";
import { AUTH_ROUTES } from "@/config/routePaths";

export default function VerifyEmail() {
  const { token } = useParams();
  const [verifyEmail] = useVerifyEmailMutation();
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    verifyEmail(token)
      .unwrap()
      .then(() => setStatus("success"))
      .catch(() => setStatus("error"));
  }, [token, verifyEmail]);

  return (
    <AuthLayout title="Email verification">
      <div className="flex flex-col items-center gap-4 py-4 text-center">
        {status === "loading" && <Spinner size="lg" />}
        {status === "success" && (
          <>
            <CheckCircle2 className="h-10 w-10 text-emerald-400" />
            <p className="text-sm text-white/70">Your email has been verified.</p>
          </>
        )}
        {status === "error" && (
          <>
            <XCircle className="h-10 w-10 text-secondary" />
            <p className="text-sm text-white/70">This verification link is invalid or has expired.</p>
          </>
        )}
        {status !== "loading" && (
          <Link to={AUTH_ROUTES.login}>
            <Button>Go to login</Button>
          </Link>
        )}
      </div>
    </AuthLayout>
  );
}
