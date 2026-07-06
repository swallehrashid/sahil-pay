import { Link } from "react-router-dom";
import {
  ShieldCheck, Smartphone, BarChart3, Users, Banknote, FileText, ArrowRight,
  Wrench, CheckCircle2, Star, Sparkles,
} from "lucide-react";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { FeatureCard, CheckItem, StatTile, MockPanel } from "./components/pieces";

const FEATURES = [
  { icon: Banknote, title: "M-Pesa rent collection", text: "Paybill & Till matching, STK push and automatic reconciliation of every shilling to the right tenant and invoice." },
  { icon: FileText, title: "Invoicing on autopilot", text: "Rent, water, electricity, penalties and recurring bills — generated in bulk and sent by SMS, email or WhatsApp." },
  { icon: Smartphone, title: "A portal tenants actually use", text: "Passwordless OTP login, live balance breakdowns, instant receipts and maintenance requests." },
  { icon: Users, title: "Teams & caretakers", text: "Give managers and caretakers a scoped, permissioned view of only the properties they run." },
  { icon: BarChart3, title: "Reports, not spreadsheets", text: "Rent-roll, arrears, occupancy and month-on-month performance — downloadable as branded PDF or Excel." },
  { icon: ShieldCheck, title: "Audited, always", text: "Every action — yours, your team's, our support's — is logged, permissioned and reversible." },
];

const STEPS = [
  { n: "1", title: "Create your free account", text: "Sign up in minutes — no card required. Add your properties, units and tenants, or import them in bulk." },
  { n: "2", title: "Connect M-Pesa", text: "Link your Paybill or Till and SahilPay starts matching incoming rent to tenants and invoices automatically." },
  { n: "3", title: "Collect, remind & report", text: "Invoices and reminders go out on schedule, tenants pay and self-serve, and your books reconcile themselves." },
];

const HOME_FAQS = [
  { q: "Is there a free trial and do I need a card?", a: "Yes — every new landlord starts with a free trial and no card is required to begin." },
  { q: "Does SahilPay support M-Pesa Paybill and Till?", a: "Both, with automatic transaction matching to the right tenant and invoice, plus a manual match tool for edge cases." },
  { q: "Do I need to install anything?", a: "No. SahilPay is cloud-based and mobile-first — you and your tenants only need a browser." },
  { q: "Can it replace my rent spreadsheets?", a: "Completely. Units, tenants, invoices and payments stay live and reconciled in one place." },
];

export default function Home() {
  return (
    <div>
      {/* 1 — Hero */}
      <section className="relative overflow-hidden px-6 pb-24 pt-20 text-center sm:pt-28">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/30 blur-3xl" />
        <div className="absolute -right-32 top-40 h-96 w-96 animate-float-blob rounded-full bg-secondary/20 blur-3xl" style={{ animationDelay: "3s" }} />

        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            <Sparkles className="h-3.5 w-3.5 text-secondary" /> Property management, reimagined for Kenya
          </span>
          <h1 className="mt-6 text-4xl font-light leading-tight tracking-wide text-white sm:text-6xl">
            Rent collection that feels <span className="bg-gradient-to-r from-secondary-200 to-secondary bg-clip-text text-transparent">effortless</span>.
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-base leading-relaxed text-white/60">
            SahilPay is the all-in-one rental management platform built for Kenya — M-Pesa rent collection,
            automated invoicing, a tenant portal, maintenance and reporting, for one unit or thousands.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}>
              <Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button>
            </Link>
            <Link to={PUBLIC_ROUTES.features}>
              <Button variant="ghost" size="lg">Explore features</Button>
            </Link>
          </div>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-white/45">
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-secondary" /> No card required</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-secondary" /> M-Pesa native</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-secondary" /> Nothing to install</span>
          </div>
        </div>
      </section>

      {/* 2 — Stat strip */}
      <Section className="!py-10">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile value="100%" label="M-Pesa reconciled" delay={0} />
          <StatTile value="4" label="portals in one" delay={80} />
          <StatTile value="1→∞" label="units per account" delay={160} />
          <StatTile value="KES" label="built for Kenya" delay={240} />
        </div>
      </Section>

      {/* 3 — Everything a portfolio needs */}
      <Section
        center
        eyebrow="One platform"
        title="Everything a portfolio needs"
        lede="Stop stitching together spreadsheets, paper receipts and scattered M-Pesa messages. SahilPay puts collection, invoicing, communications, maintenance and reporting under one roof."
      >
        <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <FeatureCard key={f.title} icon={f.icon} title={f.title} accent={i % 2 ? "third" : "secondary"} delay={i * 70}>
              {f.text}
            </FeatureCard>
          ))}
        </div>
      </Section>

      {/* 4 — M-Pesa deep dive (answers mpesa, reconcile, bank, partial, receipt) */}
      <Section eyebrow="M-Pesa native" title="Every shilling matched to the right tenant">
        <div className="mt-10 grid items-center gap-10 lg:grid-cols-2">
          <div>
            <p className="text-sm leading-relaxed text-white/60">
              SahilPay is built around how Kenya actually pays rent. Connect your Paybill or Till and incoming
              M-Pesa payments are matched to the right tenant and invoice automatically — including partial
              payments and one payment split across several invoices. Bank-statement and cash payments reconcile
              the same way, and every tenant gets an instant receipt.
            </p>
            <ul className="mt-6 space-y-3">
              <CheckItem>Paybill, Till & STK push, with automatic transaction matching</CheckItem>
              <CheckItem>Bank-statement reconciliation for cheque and transfer rents</CheckItem>
              <CheckItem>Partial payments and multi-invoice allocation handled for you</CheckItem>
              <CheckItem>Instant, downloadable receipts sent to every tenant</CheckItem>
            </ul>
          </div>
          <MockPanel
            title="Payments — auto-reconciled"
            rows={[
              { label: "MPESA · QK8… · Unit A3", value: "KES 25,000", strong: true },
              { label: "Bank transfer · Unit B1", value: "KES 18,000" },
              { label: "Partial · Unit C2", value: "KES 6,000" },
              { label: "Unmatched — review", value: "1" },
            ]}
          />
        </div>
      </Section>

      {/* 5 — Tenant portal (answers portal, tenant-login, balance, receipt, lease-expiry) */}
      <Section eyebrow="Tenant portal" title="A portal your tenants actually use">
        <div className="mt-10 grid items-center gap-10 lg:grid-cols-2">
          <MockPanel
            accent="third"
            title="Tenant — Unit A3"
            rows={[
              { label: "Current balance", value: "KES 0 · paid", strong: true },
              { label: "October rent", value: "Receipt ↓" },
              { label: "Water (12 units)", value: "KES 1,200" },
              { label: "Lease expires", value: "in 45 days" },
            ]}
          />
          <div className="lg:order-first">
            <p className="text-sm leading-relaxed text-white/60">
              Tenants log in with a one-time code sent to their phone or email — no passwords to forget or reset.
              Inside, they see a live balance breakdown, every invoice and payment, downloadable receipts, and can
              raise maintenance requests. You get lease-expiry alerts before a unit falls vacant.
            </p>
            <ul className="mt-6 space-y-3">
              <CheckItem>Passwordless OTP login by SMS or email</CheckItem>
              <CheckItem>Live balance: rent, utilities, penalties and credit</CheckItem>
              <CheckItem>Instant receipts and full payment history</CheckItem>
              <CheckItem>Lease-expiry alerts so you renew before a vacancy</CheckItem>
            </ul>
          </div>
        </div>
      </Section>

      {/* 6 — Teams & governance (answers caretaker, roles, audit, scope) */}
      <Section
        center
        eyebrow="Teams & governance"
        title="Delegate without losing control"
        lede="Add property managers and caretakers with exactly the access they need — and see every action they take."
      >
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <FeatureCard icon={Users} title="Scoped team access" delay={0}>Managers and caretakers see only the properties they're assigned to.</FeatureCard>
          <FeatureCard icon={ShieldCheck} title="Permission matrix" accent="third" delay={70}>Per-module view/edit permissions for every team member.</FeatureCard>
          <FeatureCard icon={FileText} title="Full audit trail" delay={140}>Every create, edit and delete is logged and reversible.</FeatureCard>
          <FeatureCard icon={Wrench} title="Maintenance workflow" accent="third" delay={210}>Track requests by status and link the cost as an expense.</FeatureCard>
        </div>
      </Section>

      {/* 7 — Reports & tax (answers reports, download, tax, arrears, letterhead) */}
      <Section eyebrow="Reports & tax" title="Numbers ready for your accountant">
        <div className="mt-10 grid items-center gap-10 lg:grid-cols-2">
          <div>
            <p className="text-sm leading-relaxed text-white/60">
              Generate rent-roll, arrears, expenses, occupancy and month-on-month reports on demand. Preview each
              one, choose the columns you want, and download it as a branded PDF or Excel — on your own letterhead.
              Per-property tax rates and downloadable tax receipts make filing rental income tax straightforward.
            </p>
            <ul className="mt-6 space-y-3">
              <CheckItem>Rent-roll, arrears, occupancy, month-on-month & year-on-year</CheckItem>
              <CheckItem>Customisable columns, then PDF or Excel export</CheckItem>
              <CheckItem>Per-property tax rate and downloadable tax receipts</CheckItem>
              <CheckItem>Your logo, company details and signature on every document</CheckItem>
            </ul>
          </div>
          <MockPanel
            title="Arrears report"
            rows={[
              { label: "Total arrears", value: "KES 84,500", strong: true },
              { label: "Sunrise Estates · 3 tenants", value: "KES 52,000" },
              { label: "Riverside · 2 tenants", value: "KES 32,500" },
              { label: "Export", value: "PDF · Excel" },
            ]}
          />
        </div>
      </Section>

      {/* 8 — How it works (answers how-start, need-install, trial, replace-spreadsheets) */}
      <Section center eyebrow="How it works" title="Up and running today">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <Reveal key={s.n} delay={i * 90} className="glass card-hover p-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-secondary/20 text-lg font-light text-secondary-100">{s.n}</span>
              <h3 className="mt-4 text-base font-medium text-white">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{s.text}</p>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 9 — Testimonial */}
      <Section className="!py-16">
        <Reveal className="glass mx-auto max-w-3xl p-10 text-center">
          <div className="flex justify-center gap-1 text-secondary">
            {Array.from({ length: 5 }).map((_, i) => <Star key={i} className="h-4 w-4 fill-current" />)}
          </div>
          <p className="mt-5 text-lg font-light leading-relaxed text-white/80">
            “We went from chasing M-Pesa messages across three phones to one dashboard that reconciles itself.
            Rent collection, reminders and reports that used to take days now take minutes.”
          </p>
          <p className="mt-4 text-sm text-white/50">Property manager · 240 units · Nairobi</p>
        </Reveal>
      </Section>

      {/* 10 — FAQ teaser */}
      <Section center eyebrow="Questions" title="Answers before you ask">
        <div className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-2">
          {HOME_FAQS.map((f, i) => (
            <Reveal key={f.q} delay={i * 70} className="glass p-6 text-left">
              <h3 className="text-sm font-medium text-white">{f.q}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{f.a}</p>
            </Reveal>
          ))}
        </div>
        <div className="mt-8 text-center">
          <Link to={PUBLIC_ROUTES.faq} className="text-sm text-secondary-100 transition-colors hover:text-secondary-200">
            See all frequently asked questions →
          </Link>
        </div>
      </Section>

      {/* 11 — Final CTA */}
      <Section className="!py-20">
        <Reveal className="glass relative mx-auto max-w-4xl overflow-hidden p-10 text-center sm:p-14">
          <div className="absolute -left-20 -top-20 h-56 w-56 animate-float-blob rounded-full bg-secondary/25 blur-3xl" />
          <div className="absolute -bottom-24 -right-16 h-56 w-56 animate-float-blob rounded-full bg-third/25 blur-3xl" style={{ animationDelay: "2s" }} />
          <div className="relative">
            <h2 className="text-2xl font-light tracking-wide text-white sm:text-3xl">Ready to collect rent the easy way?</h2>
            <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">
              Set up your account in minutes — no card required during your free trial. Bring your whole
              portfolio, your team and your tenants onto one premium platform.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
              <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Get started for free</Button></Link>
              <Link to={PUBLIC_ROUTES.pricing}><Button variant="ghost" size="lg">See pricing</Button></Link>
            </div>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
