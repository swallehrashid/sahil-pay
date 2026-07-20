import { Link } from "react-router-dom";
import { PUBLIC_ROUTES } from "@/config/routePaths";
import SahilPayLogo from "@/components/branding/SahilPayLogo";

// Minimal logo-only navbar for auth screens.
export default function AuthNavbar() {
  return (
    <header className="flex items-center justify-center py-6">
      <Link to={PUBLIC_ROUTES.home} className="text-white">
        <SahilPayLogo withSlogan={false} className="h-8" />
      </Link>
    </header>
  );
}
