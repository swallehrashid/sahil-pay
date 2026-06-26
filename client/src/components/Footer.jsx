import { Link } from "react-router-dom";
import { PUBLIC_ROUTES } from "@/config/routePaths";

export default function Footer() {
  return (
    <footer className="border-t border-white/10 px-6 py-10 text-sm text-white/40">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 md:flex-row">
        <span className="text-base font-light tracking-wide text-white/70">
          Sahil<span className="text-secondary">Pay</span>
        </span>
        <nav className="flex flex-wrap items-center justify-center gap-5">
          <Link to={PUBLIC_ROUTES.about} className="transition-colors hover:text-white/70">About</Link>
          <Link to={PUBLIC_ROUTES.features} className="transition-colors hover:text-white/70">Features</Link>
          <Link to={PUBLIC_ROUTES.pricing} className="transition-colors hover:text-white/70">Pricing</Link>
          <Link to={PUBLIC_ROUTES.contact} className="transition-colors hover:text-white/70">Contact</Link>
          <Link to={PUBLIC_ROUTES.faq} className="transition-colors hover:text-white/70">FAQ</Link>
          <Link to={PUBLIC_ROUTES.privacy} className="transition-colors hover:text-white/70">Privacy</Link>
          <Link to={PUBLIC_ROUTES.terms} className="transition-colors hover:text-white/70">Terms</Link>
        </nav>
        <span>© {new Date().getFullYear()} SahilPay. All rights reserved.</span>
      </div>
    </footer>
  );
}
