import { Link } from "react-router-dom";
import {
  ShieldCheck, Globe2, HeartHandshake, Smartphone, Users, BarChart3, ArrowRight, Building2, Lock,
} from "lucide-react";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { FeatureCard, CheckItem, StatTile } from "./components/pieces";
import { useSeo } from "./useSeo";

const VALUES = [
  { icon: ShieldCheck, title: "Built on trust", text: "Every action is audit-logged — nothing happens silently, and support only ever acts with your consent." },
  { icon: Globe2, title: "Made for Kenya", text: "M-Pesa Paybill and Till, KES by default, Africa/Nairobi timezone — built around how Kenya really pays rent." },
  { icon: HeartHandshake, title: "Hands-on support", text: "Consent-based onboarding and support whenever you need it, with every assisted action logged." },
  { icon: Smartphone, title: "Mobile-first", text: "Fast and usable on the phone in your pocket — for you, your caretakers and your tenants alike." },
];

export default function About() {
  useSeo({
    title: "About Sahil Pay — Built in Kenya for Kenyan Landlords",
    description:
      "Why Sahil Pay exists: rent collection in Kenya runs on M-Pesa, WhatsApp and spreadsheets. We built one system that fits how landlords and property managers here actually work.",
    path: "/about",
  });

  return (
    <div>
      {/* 1 — Hero */}
      <section className="relative overflow-hidden px-6 pb-12 pt-20 text-center sm:pt-24">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/25 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">Our story</span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">About Sahil Pay</h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            We're on a mission to give every Kenyan landlord, property manager and caretaker one premium place to
            collect rent, run their properties and delight their tenants.
          </p>
        </div>
      </section>

      {/* 2 — The problem we set out to solve (answers replace-spreadsheets, what-is) */}
      <Section eyebrow="Why we exist" title="Rent management shouldn't live in a spreadsheet">
        <div className="mt-8 grid gap-8 lg:grid-cols-2 lg:items-center">
          <p className="text-sm leading-relaxed text-white/60">
            Sahil Pay was built for landlords and property managers across Kenya who are tired of juggling
            rent-tracking spreadsheets, paper receipts and scattered M-Pesa messages across several phones. That
            way of working loses money to missed payments, unbilled utilities and hours of manual reconciliation.
            We bring the entire rent-collection workflow — invoicing, payments, communications, maintenance and
            reporting — onto one live, reconciled platform, so nothing slips through the cracks.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>One live source of truth for every unit</CheckItem>
            <CheckItem>No more chasing M-Pesa SMS by hand</CheckItem>
            <CheckItem>Utilities and penalties never go unbilled</CheckItem>
            <CheckItem>Books that reconcile themselves</CheckItem>
          </ul>
        </div>
      </Section>

      {/* 3 — Built for Kenya (answers kenya, mpesa) */}
      <Section eyebrow="Local by design" title="Built for the Kenyan market, not adapted to it">
        <div className="mt-8 grid gap-8 lg:grid-cols-2 lg:items-center">
          <ul className="grid gap-3 sm:grid-cols-2 lg:order-last">
            <CheckItem>M-Pesa Paybill, Till & STK push</CheckItem>
            <CheckItem>KES currency by default</CheckItem>
            <CheckItem>Africa/Nairobi timezone</CheckItem>
            <CheckItem>SMS-first tenant communication</CheckItem>
          </ul>
          <p className="text-sm leading-relaxed text-white/60">
            Sahil Pay is built around M-Pesa, the shilling and the way tenants here expect to be reached. Rent comes
            in over Paybill and Till and reconciles automatically; reminders and receipts go out by SMS. It isn't a
            foreign product with M-Pesa bolted on — it's designed from the ground up for how Kenyan landlords and
            tenants actually transact.
          </p>
        </div>
      </Section>

      {/* 4 — Values */}
      <Section center eyebrow="What we believe" title="The principles behind the product">
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {VALUES.map((v, i) => (
            <FeatureCard key={v.title} icon={v.icon} title={v.title} accent={i % 2 ? "third" : "secondary"} delay={i * 70}>
              {v.text}
            </FeatureCard>
          ))}
        </div>
      </Section>

      {/* 5 — Who we serve (answers who-for, agency, multi) */}
      <Section center eyebrow="Who we serve" title="From one unit to thousands">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          <FeatureCard icon={Building2} title="Individual landlords" delay={0}>Go paperless and automate rent for a single property or a small block.</FeatureCard>
          <FeatureCard icon={Users} title="Property managers" accent="third" delay={80}>Run many owners' portfolios with scoped teams and per-landlord reporting.</FeatureCard>
          <FeatureCard icon={BarChart3} title="Agencies & enterprises" delay={160}>Scale to thousands of units with custom pricing and dedicated onboarding.</FeatureCard>
        </div>
      </Section>

      {/* 6 — Security & trust (answers secure, audit, export, support) */}
      <Section eyebrow="Security & trust" title="Your data is yours — always">
        <div className="mt-8 grid gap-8 lg:grid-cols-2 lg:items-center">
          <p className="text-sm leading-relaxed text-white/60">
            We treat your rental and tenant data as what it is: sensitive and yours. It's encrypted, access is
            permission-controlled, and every create, edit and delete is written to an immutable audit trail. Our
            support team can only ever act inside your account with your explicit consent, and every assisted
            action is logged. If you ever want to leave, you can export scoped backups of everything at any time.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>Encrypted, never-sold data</CheckItem>
            <CheckItem>Immutable audit trail of every action</CheckItem>
            <CheckItem>Consent-based support access</CheckItem>
            <CheckItem>Export scoped backups any time</CheckItem>
          </ul>
        </div>
      </Section>

      {/* 7 — By the numbers */}
      <Section className="!py-12">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile value="4" label="portals in one platform" delay={0} />
          <StatTile value="100%" label="of actions audited" delay={80} />
          <StatTile value="1→∞" label="units per account" delay={160} />
          <StatTile value="0" label="cards needed to start" delay={240} />
        </div>
      </Section>

      {/* 8 — CTA */}
      <Section className="!py-20">
        <Reveal className="glass mx-auto max-w-4xl p-10 text-center sm:p-14">
          <Lock className="mx-auto h-6 w-6 text-secondary" />
          <h2 className="mt-4 text-2xl font-light tracking-wide text-white sm:text-3xl">Join the landlords going paperless</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">Start your free trial today — no card required — and see why Sahil Pay is built different.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
            <Link to={PUBLIC_ROUTES.contact}><Button variant="ghost" size="lg">Get in touch</Button></Link>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
