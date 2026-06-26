import { Link } from "react-router-dom";
import { PUBLIC_ROUTES } from "@/config/routePaths";

// Minimal logo-only navbar for auth screens.
export default function AuthNavbar() {
  return (
    <header className="flex items-center justify-center py-6">
      <Link to={PUBLIC_ROUTES.home} className="text-xl font-light tracking-wide text-white">
        Sahil<span className="text-secondary">Pay</span>
      </Link>
    </header>
  );
}
