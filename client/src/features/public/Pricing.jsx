import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import clsx from "clsx";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES } from "@/config/routePaths";

const TIERS = [
  { name: "Starter", units: "Up to 20 units", price: "KES 100", per: "per unit / month", features: ["Invoicing & payments", "Tenant portal", "Email support"] },
  {
    name: "Growth",
    units: "21 – 70 units",
    price: "KES 80",
    per: "per unit / month",
    features: ["Everything in Starter", "Team members & permissions", "Priority support"],
    highlighted: true,
  },
  { name: "Portfolio", units: "70+ units", price: "Custom", per: "talk to us", features: ["Everything in Growth", "Dedicated onboarding", "Custom per-unit pricing"] },
];

// Public-facing reflection of the admin-configured packages (§10.3). Static copy —
// no public endpoint is exposed for live package data.
export default function Pricing() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-24">
      <h1 className="animate-fade-in-up text-center text-3xl font-light text-white">Simple, unit-based pricing</h1>
      <p className="mx-auto mt-3 max-w-xl animate-fade-in-up text-center text-white/60" style={{ animationDelay: "80ms" }}>
        Pay monthly, save with quarterly (10% off) or annual (15% off) billing. Every plan
        starts with a free trial — no card required.
      </p>
      <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {TIERS.map((tier, index) => (
          <div
            key={tier.name}
            className={clsx("glass animate-fade-in-up p-8", tier.highlighted && "border-secondary/50 shadow-glow")}
            style={{ animationDelay: `${index * 100}ms` }}
          >
            <h3 className="text-lg font-medium text-white">{tier.name}</h3>
            <p className="mt-1 text-sm text-white/50">{tier.units}</p>
            <p className="mt-6 text-3xl font-light text-white">{tier.price}</p>
            <p className="text-xs text-white/40">{tier.per}</p>
            <ul className="mt-6 space-y-2 text-sm text-white/60">
              {tier.features.map((feature) => (
                <li key={feature} className="flex items-center gap-2">
                  <Check className="h-4 w-4 text-secondary" /> {feature}
                </li>
              ))}
            </ul>
            <Link to={AUTH_ROUTES.register} className="mt-8 block">
              <Button variant={tier.highlighted ? "primary" : "ghost"} className="w-full">
                Start free trial
              </Button>
            </Link>
          </div>
        ))}
      </div>
    </section>
  );
}
