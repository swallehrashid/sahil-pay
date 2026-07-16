import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { Menu, X } from "lucide-react";
import clsx from "clsx";
import Button from "@/components/ui/Button";
import SahilPayLogo, { SahilPayMark } from "@/components/branding/SahilPayLogo";
import { PUBLIC_ROUTES, AUTH_ROUTES } from "@/config/routePaths";

const LINKS = [
  { to: PUBLIC_ROUTES.home, label: "Home" },
  { to: PUBLIC_ROUTES.features, label: "Features" },
  { to: PUBLIC_ROUTES.pricing, label: "Pricing" },
  { to: PUBLIC_ROUTES.about, label: "About" },
  { to: PUBLIC_ROUTES.contact, label: "Contact" },
];

export default function PublicNavbar() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setIsScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={clsx(
        "sticky top-0 z-40 transition-all duration-300",
        isScrolled ? "glass-dark mx-4 mt-4 rounded-2xl px-6 py-3" : "px-6 py-5"
      )}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <Link to={PUBLIC_ROUTES.home} className="text-white">
          <SahilPayLogo withSlogan={false} className="hidden h-8 sm:flex md:h-9" />
          <SahilPayMark className="h-8 sm:hidden" />
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                clsx(
                  "group relative text-sm transition-colors duration-200",
                  isActive ? "text-white" : "text-white/60 hover:text-white"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {link.label}
                  <span
                    className={clsx(
                      "absolute -bottom-1.5 left-0 h-0.5 rounded-full bg-secondary transition-all duration-300",
                      isActive ? "w-full" : "w-0 group-hover:w-full"
                    )}
                  />
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <Link to={AUTH_ROUTES.login}>
            <Button variant="ghost" size="sm">Log in</Button>
          </Link>
          <Link to={AUTH_ROUTES.register}>
            <Button variant="primary" size="sm">Get started</Button>
          </Link>
        </div>

        <button className="text-white/70 md:hidden" onClick={() => setIsMenuOpen((open) => !open)}>
          {isMenuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>

      {isMenuOpen && (
        <nav className="glass mt-4 flex flex-col gap-1 p-4 animate-fade-in-up md:hidden">
          {LINKS.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              onClick={() => setIsMenuOpen(false)}
              className="rounded-lg px-3 py-2 text-sm text-white/70 hover:bg-white/10"
            >
              {link.label}
            </Link>
          ))}
          <div className="mt-2 flex gap-3 px-3">
            <Link to={AUTH_ROUTES.login} className="flex-1">
              <Button variant="ghost" size="sm" className="w-full">Log in</Button>
            </Link>
            <Link to={AUTH_ROUTES.register} className="flex-1">
              <Button variant="primary" size="sm" className="w-full">Get started</Button>
            </Link>
          </div>
        </nav>
      )}
    </header>
  );
}
