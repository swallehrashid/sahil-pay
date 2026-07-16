import { Link } from "react-router-dom";
import { Mail, Phone, MapPin } from "lucide-react";
import SahilPayLogo from "@/components/branding/SahilPayLogo";
import { PUBLIC_ROUTES, AUTH_ROUTES } from "@/config/routePaths";

const COLUMNS = [
  {
    heading: "Product",
    links: [
      { to: PUBLIC_ROUTES.features, label: "Features" },
      { to: PUBLIC_ROUTES.pricing, label: "Pricing" },
      { to: PUBLIC_ROUTES.faq, label: "FAQ" },
      { to: AUTH_ROUTES.register, label: "Start free trial" },
    ],
  },
  {
    heading: "Company",
    links: [
      { to: PUBLIC_ROUTES.about, label: "About" },
      { to: PUBLIC_ROUTES.contact, label: "Contact" },
      { to: PUBLIC_ROUTES.becomeAffiliate, label: "Become an affiliate" },
      { to: AUTH_ROUTES.login, label: "Log in" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { to: PUBLIC_ROUTES.privacy, label: "Privacy Policy" },
      { to: PUBLIC_ROUTES.terms, label: "Terms of Service" },
    ],
  },
];

export default function Footer() {
  return (
    <footer className="mt-10 border-t border-white/10 px-6 pb-10 pt-14 text-sm text-white/50">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          {/* Brand + contact */}
          <div>
            <SahilPayLogo className="h-10 text-white/90" />
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-white/45">
              The all-in-one rental management platform built for Kenya — M-Pesa rent collection, invoicing,
              a tenant portal and reporting in one place.
            </p>
            <div className="mt-4 space-y-2 text-xs text-white/45">
              <span className="flex items-center gap-2"><Mail className="h-3.5 w-3.5 text-secondary" /> hello@sahilpay.co.ke</span>
              <span className="flex items-center gap-2"><Phone className="h-3.5 w-3.5 text-secondary" /> 0114 129 809</span>
              <span className="flex items-center gap-2"><MapPin className="h-3.5 w-3.5 text-secondary" /> Nairobi, Kenya</span>
            </div>
          </div>

          {/* Link columns */}
          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <p className="text-xs font-medium uppercase tracking-wider text-white/40">{col.heading}</p>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      to={link.to}
                      className="inline-block text-white/55 transition-all duration-200 hover:translate-x-0.5 hover:text-white"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-white/10 pt-6 text-xs text-white/40 md:flex-row">
          <span>© {new Date().getFullYear()} Sahil Pay. All rights reserved.</span>
          <span>Made for landlords &amp; property managers across Kenya 🇰🇪</span>
        </div>
      </div>
    </footer>
  );
}
