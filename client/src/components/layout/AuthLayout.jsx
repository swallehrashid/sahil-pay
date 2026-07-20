import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PUBLIC_ROUTES } from "@/config/routePaths";
import SahilPayLogo from "@/components/branding/SahilPayLogo";

// Centered glass card shell for login/register/OTP, over the gradient bg, scaleIn reveal.
export default function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="app-bg relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div className="absolute -left-24 top-10 h-72 w-72 animate-float-blob rounded-full bg-third/30 blur-3xl" />
      <div className="absolute -right-24 bottom-10 h-72 w-72 animate-float-blob rounded-full bg-secondary/20 blur-3xl" />

      <div className="glass relative z-10 w-full max-w-md animate-scale-in p-8">
        <Link to={PUBLIC_ROUTES.home} className="mb-4 inline-flex items-center gap-1.5 text-sm text-white/50 transition-colors hover:text-white">
          <ArrowLeft className="h-4 w-4" /> Back to home
        </Link>
        <Link to={PUBLIC_ROUTES.home} className="mb-6 flex justify-center text-white">
          <SahilPayLogo className="h-11" />
        </Link>
        {title && <h1 className="text-center text-xl font-light text-white">{title}</h1>}
        {subtitle && <p className="mt-1 text-center text-sm text-white/50">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </div>
  );
}
