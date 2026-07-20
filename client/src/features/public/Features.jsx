import { Link } from "react-router-dom";
import {
  Building2, Receipt, Wallet, Wrench, MessageSquare, ShieldCheck,
  Home as HomeIcon, Gauge, Droplet, FileText, Bell, Users, ArrowRight, BarChart3,
} from "lucide-react";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { FeatureCard, CheckItem } from "./components/pieces";

export default function Features() {
  return (
    <div>
      {/* 1 — Hero */}
      <section className="relative overflow-hidden px-6 pb-16 pt-20 text-center sm:pt-24">
        <div className="absolute -right-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/25 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            The complete toolkit
          </span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">Built for the whole portfolio</h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            Every module your landlords, teams and tenants need — property and tenancy, invoicing, M-Pesa
            payments, communications, maintenance, reporting and governance — under one premium roof.
          </p>
        </div>
      </section>

      {/* 2 — Property & tenancy (answers multi, groups, lifecycle, lease-expiry, vacancy) */}
      <Section eyebrow="Property & tenancy" title="Your whole portfolio, organised">
        <div className="mt-10 grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-start">
          <p className="text-sm leading-relaxed text-white/60">
            Manage unlimited properties and units, and group them by estate, location or owner. Track the full
            tenant lifecycle — move-in, unit transfers, lease terms and documents, right through to move-out — with
            a complete shift history per unit. Live occupancy and vacancy tell you which units are earning and
            which are empty, and lease-expiry alerts fire before a unit falls vacant.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>Unlimited properties, units & property groups</CheckItem>
            <CheckItem>Full tenant lifecycle with unit shift history</CheckItem>
            <CheckItem>Live occupancy & vacancy per property and portfolio</CheckItem>
            <CheckItem>Lease-expiry alerts ahead of time</CheckItem>
            <CheckItem>Tenant documents & templates</CheckItem>
            <CheckItem>Per-property and grouped reporting</CheckItem>
          </ul>
        </div>
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-3">
          <FeatureCard icon={Building2} title="Properties & units" delay={0}>Structure your estates, buildings and units exactly as they are on the ground.</FeatureCard>
          <FeatureCard icon={HomeIcon} title="Tenant lifecycle" accent="third" delay={80}>Onboard, transfer and off-board tenants with a full audit of every move.</FeatureCard>
          <FeatureCard icon={Gauge} title="Occupancy insight" delay={160}>Know your vacancy rate and earning units at a glance.</FeatureCard>
        </div>
      </Section>

      {/* 3 — Invoicing & rent (answers auto-invoice, utilities, penalties, bulk, deposit, statements) */}
      <Section eyebrow="Invoicing" title="Invoices that raise themselves">
        <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_1.1fr] lg:items-start">
          <ul className="grid gap-3 sm:grid-cols-2 lg:order-last">
            <CheckItem>Automated monthly rent invoices</CheckItem>
            <CheckItem>Utility billing from meter readings</CheckItem>
            <CheckItem>Automatic late-payment penalties</CheckItem>
            <CheckItem>Bulk generation across a property or portfolio</CheckItem>
            <CheckItem>Deposit tracking & move-out refunds</CheckItem>
            <CheckItem>Branded PDF & Excel statements</CheckItem>
          </ul>
          <p className="text-sm leading-relaxed text-white/60">
            Set rent once and Sahil Pay generates and sends monthly invoices automatically — including recurring
            utility charges, service fees and custom line items. Turn water and electricity meter readings into
            billed line items using your per-unit rates, apply late-payment penalties on overdue invoices, and
            bulk-generate invoices for a whole property in one click. Deposits are tracked and reconciled on
            move-out, and every tenant has a downloadable statement.
          </p>
        </div>
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-3">
          <FeatureCard icon={Receipt} title="Recurring invoices" delay={0}>Rent, service charges and custom fees on the schedule you set.</FeatureCard>
          <FeatureCard icon={Droplet} title="Utility billing" accent="third" delay={80}>Meter readings become invoice line items automatically.</FeatureCard>
          <FeatureCard icon={FileText} title="Statements" delay={160}>Full tenant statements exportable as PDF or Excel.</FeatureCard>
        </div>
      </Section>

      {/* 4 — Payments (answers mpesa, reconcile, bank, partial, manual, receipt) */}
      <Section eyebrow="Payments" title="M-Pesa, bank and cash — reconciled">
        <div className="mt-10 grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-start">
          <p className="text-sm leading-relaxed text-white/60">
            Sahil Pay is M-Pesa native: Paybill, Till and STK push, with incoming payments matched to the right
            tenant and invoice automatically. Reconcile bank-statement payments for cheque and transfer rents,
            record cash manually with proof, and let Sahil Pay handle partial payments and split a single payment
            across multiple invoices. Every payment produces an instant receipt.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>M-Pesa Paybill, Till & STK push</CheckItem>
            <CheckItem>Automatic transaction matching</CheckItem>
            <CheckItem>Bank-statement reconciliation</CheckItem>
            <CheckItem>Manual & cash payment recording</CheckItem>
            <CheckItem>Partial payments & multi-invoice allocation</CheckItem>
            <CheckItem>Instant tenant receipts</CheckItem>
          </ul>
        </div>
      </Section>

      {/* 5 — Communications (answers sms, channels, own-sender, automate-reminders) */}
      <Section eyebrow="Communications" title="Reach every tenant, your way">
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <FeatureCard icon={MessageSquare} title="SMS reminders" delay={0}>Send rent reminders and notices one-to-one or in bulk, with templates.</FeatureCard>
          <FeatureCard icon={Bell} title="Email & WhatsApp" accent="third" delay={80}>Reach tenants across channels with delivery tracking on each message.</FeatureCard>
          <FeatureCard icon={Wallet} title="Your own sender ID" delay={160}>Send under your own registered sender ID, or use ours and top up credits.</FeatureCard>
          <FeatureCard icon={Receipt} title="Automated nudges" accent="third" delay={240}>Reminders on a schedule and thank-yous on payment, sent for you.</FeatureCard>
        </div>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CheckItem>Reusable templates with tenant variables</CheckItem>
          <CheckItem>Bulk sends to a property or portfolio</CheckItem>
          <CheckItem>Per-message delivery status</CheckItem>
          <CheckItem>Tenant document templates</CheckItem>
        </ul>
      </Section>

      {/* 6 — Operations (answers maintenance, expenses, recurring-bills, vacancy) */}
      <Section eyebrow="Operations" title="Maintenance and expenses in one flow">
        <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_1.1fr] lg:items-start">
          <ul className="grid gap-3 sm:grid-cols-2 lg:order-last">
            <CheckItem>Tenant-raised maintenance requests</CheckItem>
            <CheckItem>Track by status & category, assign & resolve</CheckItem>
            <CheckItem>Link repair cost as a property expense</CheckItem>
            <CheckItem>One-off & recurring expenses</CheckItem>
            <CheckItem>Expense categories & profitability</CheckItem>
            <CheckItem>Utility readings feed straight into invoices</CheckItem>
          </ul>
          <p className="text-sm leading-relaxed text-white/60">
            Tenants log maintenance requests from their portal; you track them by status and category, assign
            them, and link the cost as an expense — so repairs and spending never live in separate places. Record
            one-off and recurring expenses per property, categorise them, and Sahil Pay nets them against rent
            collected to show real income and profitability per property and across the portfolio.
          </p>
        </div>
      </Section>

      {/* 7 — Reports & analytics (answers reports, download, tax, arrears, letterhead) */}
      <Section eyebrow="Reports & analytics" title="Insight, then export">
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <FeatureCard icon={BarChart3} title="On-demand reports" delay={0}>Rent-roll, arrears, expenses, occupancy, month-on-month and year-on-year.</FeatureCard>
          <FeatureCard icon={FileText} title="Custom columns" accent="third" delay={80}>Preview, choose the columns you want, then export to PDF or Excel.</FeatureCard>
          <FeatureCard icon={ShieldCheck} title="Tax-ready" delay={160}>Per-property tax rates and downloadable tax receipts for filing.</FeatureCard>
        </div>
        <ul className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CheckItem>Arrears report ranked by who owes most</CheckItem>
          <CheckItem>Occupancy & vacancy analytics</CheckItem>
          <CheckItem>Your branding on every document</CheckItem>
          <CheckItem>Scoped Excel / PDF backups any time</CheckItem>
        </ul>
      </Section>

      {/* 8 — Governance (answers caretaker, roles, audit, scope, secure, export) */}
      <Section eyebrow="Governance & security" title="Delegate safely, keep control">
        <div className="mt-10 grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-start">
          <p className="text-sm leading-relaxed text-white/60">
            Add property managers and caretakers as team members with a fine-grained view/edit permission matrix
            per module, scoped to only the properties they manage. Every create, edit and delete — by you, your
            team or our support — is written to a full, immutable audit trail, so nothing happens silently. Your
            data is encrypted, never sold, and you can export scoped backups whenever you like.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>Per-module permission matrix</CheckItem>
            <CheckItem>Property-scoped team access</CheckItem>
            <CheckItem>Full, immutable audit trail</CheckItem>
            <CheckItem>Consent-based support access</CheckItem>
            <CheckItem>Encrypted, never-sold data</CheckItem>
            <CheckItem>Export scoped backups any time</CheckItem>
          </ul>
        </div>
        <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-3">
          <FeatureCard icon={Users} title="Team roles" delay={0}>Owners, managers, caretakers and support — each with the right access.</FeatureCard>
          <FeatureCard icon={ShieldCheck} title="Audit trail" accent="third" delay={80}>See exactly who did what, and when, across your account.</FeatureCard>
          <FeatureCard icon={Wrench} title="Backups & export" delay={160}>Your data is yours — download it as Excel or PDF whenever.</FeatureCard>
        </div>
      </Section>

      {/* 9 — CTA */}
      <Section className="!py-20">
        <Reveal className="glass mx-auto max-w-4xl p-10 text-center sm:p-14">
          <h2 className="text-2xl font-light tracking-wide text-white sm:text-3xl">See every module in action</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">Start a free trial and set up your first property in minutes — no card required.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
            <Link to={PUBLIC_ROUTES.pricing}><Button variant="ghost" size="lg">View pricing</Button></Link>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
