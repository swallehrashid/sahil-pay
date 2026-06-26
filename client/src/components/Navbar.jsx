import { Link } from "react-router-dom";
import { PUBLIC_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import Button from "./ui/Button";

// Minimal, portal-agnostic top bar (distinct from the richer PublicNavbar used on the
// marketing site) — a bare logo + auth CTA, for wherever that's all that's needed.
export default function Navbar() {
  return (
    <header className="flex items-center justify-between px-6 py-4">
      <Link to={PUBLIC_ROUTES.home} className="text-lg font-light tracking-wide text-white">
        Sahil<span className="text-secondary">Pay</span>
      </Link>
      <div className="flex items-center gap-3">
        <Link to={AUTH_ROUTES.login}>
          <Button variant="ghost" size="sm">Log in</Button>
        </Link>
        <Link to={AUTH_ROUTES.register}>
          <Button variant="primary" size="sm">Get started</Button>
        </Link>
      </div>
    </header>
  );
}
