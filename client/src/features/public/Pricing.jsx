import { useMemo } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { Check, Star, Sparkles, MessageSquare, ShieldCheck, ArrowRight, Calendar } from "lucide-react";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetPublicPackagesQuery } from "./publicApiSlice";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { CheckItem } from "./components/pieces";
import { useSeo, softwareApplicationJsonLd } from "./useSeo";

const INCLUDED = [
  "M-Pesa Paybill & Till collection",
  "Automated rent & utility invoicing",
  "Tenant self-service portal",
  "SMS, email & WhatsApp messaging",
  "Maintenance tracking",
  "Full reports & tax receipts",
  "Team members & permissions",
  "Audit trail & scoped backups",
];

const CYCLES = [
  { icon: Calendar, name: "Monthly", tag: "Pay as you go", note: "Full flexibility — change or cancel any time." },
  { icon: Calendar, name: "Quarterly", tag: "Save 10%", note: "A discount for billing every three months." },
  { icon: Calendar, name: "Annual", tag: "Save 15%", note: "Best value — one payment for the whole year." },
];

const PRICING_FAQS = [
  { q: "Is there a free trial and do I need a card?", a: "Yes — every new landlord starts with a free trial and no card is required to begin." },
  { q: "Do I pay per unit or a flat fee?", a: "Pricing is per unit per month by default, with lower rates as you grow. Large portfolios can arrange a flat or custom per-unit rate." },
  { q: "Are there discounts for paying annually?", a: "Yes — quarterly billing saves 10% and annual billing saves 15% versus paying monthly." },
  { q: "Can I change or cancel my plan anytime?", a: "Yes. Your plan tier adjusts automatically as your unit count changes, and you're never locked in." },
  { q: "Are there any hidden fees?", a: "No. You pay your per-unit subscription and only pay extra for SMS credits you choose to buy — everything else is included." },
  { q: "How much does it cost for a small landlord?", a: "Because it's per unit, a landlord with a few units pays very little, while larger portfolios unlock lower per-unit pricing." },
];

function priceParts(pkg) {
  if (pkg.price_per_unit != null) return { amount: formatCurrency(pkg.price_per_unit), per: "per unit / month" };
  if (pkg.flat_price != null) return { amount: formatCurrency(pkg.flat_price), per: "per month" };
  return { amount: "Custom", per: "talk to us" };
}

function bandLabel(pkg) {
  if (pkg.min_units && pkg.max_units) return `${pkg.min_units}–${pkg.max_units} units`;
  if (pkg.min_units && !pkg.max_units) return `${pkg.min_units}+ units`;
  return "Any size";
}

export default function Pricing() {
  const { data: packages = [], isLoading } = useGetPublicPackagesQuery();

  // Product schema with the live tiers as Offers — this is what lets a search
  // result show the price directly, which is the whole reason someone searching
  // "rental management software Kenya price" clicks one listing over another.
  const jsonLd = useMemo(() => softwareApplicationJsonLd(packages), [packages]);

  useSeo({
    title: "Pricing — Per Unit, Per Month | Sahil Pay",
    description:
      "Simple per-unit pricing for Kenyan landlords and property managers. No setup fees, no contracts, unlimited team members — pay only for the units you manage.",
    path: "/pricing",
    jsonLd,
    jsonLdId: "pricing",
  });

  return (
    <div>
      {/* 1 — Hero */}
      <section className="relative overflow-hidden px-6 pb-12 pt-20 text-center sm:pt-24">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-secondary/20 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            <Sparkles className="h-3.5 w-3.5 text-secondary" /> Simple, unit-based pricing
          </span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">Pay only for what you manage</h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            Pricing is per unit per month, so a single landlord pays little and large portfolios unlock lower
            rates. Every plan starts with a free trial — no card required.
          </p>
        </div>
      </section>

      {/* 2 — Live admin-controlled plans */}
      <Section className="!pt-8">
        {isLoading ? (
          <Spinner className="mx-auto my-10" />
        ) : packages.length === 0 ? (
          <Reveal className="glass mx-auto max-w-lg p-10 text-center">
            <p className="text-white/60">Our plans are being updated — please check back shortly or contact us for a quote.</p>
            <Link to={PUBLIC_ROUTES.contact} className="mt-4 inline-block text-sm text-secondary-100 hover:text-secondary-200">Contact us →</Link>
          </Reveal>
        ) : (
          <div className={clsx("grid grid-cols-1 gap-6", packages.length >= 3 ? "lg:grid-cols-3" : "sm:grid-cols-2")}>
            {packages.map((pkg, i) => {
              const { amount, per } = priceParts(pkg);
              const highlight = pkg.is_recommended || pkg.is_popular;
              return (
                <Reveal
                  key={pkg.id}
                  delay={i * 90}
                  className={clsx(
                    "glass card-hover relative flex flex-col p-8",
                    highlight && "border-secondary/50 shadow-glow"
                  )}
                >
                  {(pkg.is_recommended || pkg.is_popular) && (
                    <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-secondary px-3 py-1 text-xs font-medium text-white shadow-glow">
                      {pkg.is_recommended ? "Recommended" : "Most popular"}
                    </span>
                  )}
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-medium text-white">{pkg.name}</h3>
                    <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white/50">{bandLabel(pkg)}</span>
                  </div>
                  {pkg.public_description && <p className="mt-2 text-sm leading-relaxed text-white/50">{pkg.public_description}</p>}
                  <p className="mt-6 text-3xl font-light text-white">{amount}</p>
                  <p className="text-xs text-white/40">{per}</p>
                  <ul className="mt-6 flex-1 space-y-2.5">
                    {(pkg.feature_list ?? []).map((feat) => (
                      <li key={feat} className="flex items-start gap-2 text-sm text-white/60">
                        <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-secondary" /> {feat}
                      </li>
                    ))}
                  </ul>
                  <Link to={AUTH_ROUTES.register} className="mt-8 block">
                    <Button variant={highlight ? "primary" : "ghost"} className="w-full">Start free trial</Button>
                  </Link>
                </Reveal>
              );
            })}
          </div>
        )}
        <p className="mt-8 text-center text-xs text-white/40">
          Managing a large portfolio or an agency?{" "}
          <Link to={PUBLIC_ROUTES.contact} className="text-secondary-100 hover:text-secondary-200">Talk to us about custom pricing.</Link>
        </p>
      </Section>

      {/* 3 — Everything included (answers hidden, per-unit, trial) */}
      <Section center eyebrow="Every plan includes" title="No feature paywalls">
        <p className="mx-auto -mt-2 max-w-xl text-center text-sm text-white/55">
          Whatever plan you're on, you get the whole platform. You only pay your per-unit subscription — plus
          optional SMS credits. There are no hidden fees and no feature locked behind a higher tier.
        </p>
        <ul className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-3 sm:grid-cols-2">
          {INCLUDED.map((item) => (
            <CheckItem key={item}>{item}</CheckItem>
          ))}
        </ul>
      </Section>

      {/* 4 — Billing cycles & discounts (answers discounts, cancel, how-priced) */}
      <Section center eyebrow="Billing cycles" title="Save more the longer you commit">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          {CYCLES.map((c, i) => (
            <Reveal key={c.name} delay={i * 80} className="glass card-hover p-6 text-center">
              <c.icon className="mx-auto h-6 w-6 text-secondary" />
              <h3 className="mt-3 text-base font-medium text-white">{c.name}</h3>
              <p className="mt-1 text-sm font-medium text-secondary-100">{c.tag}</p>
              <p className="mt-2 text-sm text-white/50">{c.note}</p>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 5 — SMS credits (answers own-sender, sms) */}
      <Section eyebrow="SMS credits" title="Messaging that scales with you">
        <div className="mt-8 grid gap-8 lg:grid-cols-2">
          <Reveal className="glass p-6">
            <MessageSquare className="h-6 w-6 text-secondary" />
            <h3 className="mt-3 text-base font-medium text-white">Use our sender ID</h3>
            <p className="mt-2 text-sm leading-relaxed text-white/55">
              Send SMS rent reminders through Sahil Pay's shared sender ID and simply top up credits — pay only
              for the SMS you send, priced per message with no monthly commitment.
            </p>
          </Reveal>
          <Reveal delay={90} className="glass p-6">
            <ShieldCheck className="h-6 w-6 text-third-100" />
            <h3 className="mt-3 text-base font-medium text-white">Bring your own sender ID</h3>
            <p className="mt-2 text-sm leading-relaxed text-white/55">
              Prefer to send under your own brand? Connect your own registered sender ID and messages go
              out as your business — you're always in control of how you reach tenants.
            </p>
          </Reveal>
        </div>
      </Section>

      {/* 6 — Who each plan is for (answers agency, grow, multi) */}
      <Section center eyebrow="Right-sized" title="A plan for every stage">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          <Reveal className="glass card-hover p-6">
            <h3 className="text-base font-medium text-white">Individual landlords</h3>
            <p className="mt-2 text-sm text-white/55">A property or two? Go paperless, automate rent and give tenants a portal — for very little per month.</p>
          </Reveal>
          <Reveal delay={90} className="glass card-hover p-6">
            <h3 className="text-base font-medium text-white">Growing portfolios</h3>
            <p className="mt-2 text-sm text-white/55">Add caretakers and managers with scoped access, bulk-invoice and unlock lower per-unit pricing as you scale.</p>
          </Reveal>
          <Reveal delay={180} className="glass card-hover p-6">
            <h3 className="text-base font-medium text-white">Agencies & enterprises</h3>
            <p className="mt-2 text-sm text-white/55">Manage many owners' portfolios with per-landlord reporting, custom per-unit pricing and dedicated onboarding.</p>
          </Reveal>
        </div>
      </Section>

      {/* 7 — Pricing FAQ */}
      <Section center eyebrow="Pricing questions" title="Everything about billing">
        <div className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-2">
          {PRICING_FAQS.map((f, i) => (
            <Reveal key={f.q} delay={i * 60} className="glass p-6 text-left">
              <h3 className="text-sm font-medium text-white">{f.q}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{f.a}</p>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 8 — CTA */}
      <Section className="!py-20">
        <Reveal className="glass mx-auto max-w-4xl p-10 text-center sm:p-14">
          <div className="flex justify-center gap-1 text-secondary">
            {Array.from({ length: 5 }).map((_, i) => <Star key={i} className="h-4 w-4 fill-current" />)}
          </div>
          <h2 className="mt-5 text-2xl font-light tracking-wide text-white sm:text-3xl">Start free, upgrade only as you grow</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">No card required to begin. Bring your whole portfolio onto one platform today.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
            <Link to={PUBLIC_ROUTES.contact}><Button variant="ghost" size="lg">Contact sales</Button></Link>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
