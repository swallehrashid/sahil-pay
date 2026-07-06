import { useState } from "react";
import { Link } from "react-router-dom";
import { Mail, Phone, MapPin, Clock, MessageSquare, LifeBuoy, ArrowRight, Users } from "lucide-react";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { isRequired, isValidEmail } from "@/utils/validators";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { FeatureCard, CheckItem } from "./components/pieces";

const CONTACT_FAQS = [
  { q: "Is there a free trial and do I need a card?", a: "Yes — start free, no card required. You only pay once your trial ends and you choose a plan." },
  { q: "Can you help me import my existing tenants?", a: "Yes. Our team offers consent-based onboarding help to get your properties, units and tenants set up quickly." },
  { q: "Does SahilPay support M-Pesa?", a: "Yes — Paybill, Till and STK push, with automatic reconciliation to tenants and invoices." },
  { q: "Is my data secure and private?", a: "Yes. Data is encrypted, permission-controlled, fully audited and never sold — and you can export it any time." },
];

export default function Contact() {
  const [form, setForm] = useState({ name: "", email: "", message: "" });
  const [errors, setErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.name)) nextErrors.name = "Your name is required";
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isRequired(form.message)) nextErrors.message = "Tell us a little about your portfolio";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      setForm({ name: "", email: "", message: "" });
      toast("Thanks — we'll be in touch shortly.", { type: "success" });
    }, 600);
  };

  return (
    <div>
      {/* 1 — Hero */}
      <section className="relative overflow-hidden px-6 pb-8 pt-20 text-center sm:pt-24">
        <div className="absolute -right-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-secondary/20 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">We'd love to hear from you</span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">Get in touch</h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            Questions about features, pricing or migrating your portfolio? Send us a message and our team will get
            back to you — usually within one business day.
          </p>
        </div>
      </section>

      {/* 2 — Contact methods + form */}
      <Section className="!pt-8">
        <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
          <Reveal className="space-y-5">
            <div className="glass row-hover flex items-center gap-3 p-4">
              <Mail className="h-5 w-5 text-secondary" />
              <span className="text-sm text-white/70">hello@sahilpay.com</span>
            </div>
            <div className="glass row-hover flex items-center gap-3 p-4">
              <Phone className="h-5 w-5 text-secondary" />
              <span className="text-sm text-white/70">+254 700 000 000</span>
            </div>
            <div className="glass row-hover flex items-center gap-3 p-4">
              <MapPin className="h-5 w-5 text-secondary" />
              <span className="text-sm text-white/70">Nairobi, Kenya</span>
            </div>
            <div className="glass row-hover flex items-center gap-3 p-4">
              <Clock className="h-5 w-5 text-secondary" />
              <span className="text-sm text-white/70">Mon–Sat, 8am–6pm EAT</span>
            </div>
          </Reveal>

          <Reveal delay={100}>
            <form onSubmit={handleSubmit} className="glass space-y-4 p-8">
              <Input label="Name" value={form.name} onChange={update("name")} error={errors.name} required />
              <Input label="Email" type="email" value={form.email} onChange={update("email")} error={errors.email} required />
              <Textarea label="Message" rows={5} value={form.message} onChange={update("message")} error={errors.message} required />
              <Button type="submit" className="w-full" isLoading={isSubmitting}>Send message</Button>
            </form>
          </Reveal>
        </div>
      </Section>

      {/* 3 — What to expect (answers support) */}
      <Section center eyebrow="What happens next" title="Real people, fast answers">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          <FeatureCard icon={MessageSquare} title="We reply quickly" delay={0}>Most messages get a personal response within one business day.</FeatureCard>
          <FeatureCard icon={LifeBuoy} title="Onboarding help" accent="third" delay={80}>We can help you import properties, units and tenants to get started fast.</FeatureCard>
          <FeatureCard icon={Users} title="Consent-based support" delay={160}>With your permission, we can step into your account to help — every action logged.</FeatureCard>
        </div>
      </Section>

      {/* 4 — For agencies & large portfolios (answers agency, how-priced) */}
      <Section eyebrow="For teams & agencies" title="Migrating a big portfolio?">
        <div className="mt-8 grid gap-8 lg:grid-cols-2 lg:items-center">
          <p className="text-sm leading-relaxed text-white/60">
            If you manage hundreds or thousands of units, or run a property-management agency handling many
            owners, we'll help you plan the move — bulk data import, team setup with scoped permissions,
            per-landlord reporting and custom per-unit pricing. Tell us about your portfolio and we'll tailor a
            rollout that fits.
          </p>
          <ul className="grid gap-3 sm:grid-cols-2">
            <CheckItem>Bulk import of properties & tenants</CheckItem>
            <CheckItem>Team roles & property scoping</CheckItem>
            <CheckItem>Per-landlord & grouped reporting</CheckItem>
            <CheckItem>Custom per-unit pricing</CheckItem>
          </ul>
        </div>
      </Section>

      {/* 5 — Try it yourself */}
      <Section center eyebrow="Prefer to explore first?" title="You don't have to wait for us">
        <p className="mx-auto -mt-2 max-w-xl text-center text-sm text-white/55">
          Start a free trial right now — no card required — and set up your first property in minutes. You can
          always reach out later if you'd like a hand.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
          <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
          <Link to={PUBLIC_ROUTES.features}><Button variant="ghost" size="lg">Explore features</Button></Link>
        </div>
      </Section>

      {/* 6 — Quick answers (answers trial, mpesa, secure, support) */}
      <Section center eyebrow="Quick answers" title="Before you write to us">
        <div className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-4 sm:grid-cols-2">
          {CONTACT_FAQS.map((f, i) => (
            <Reveal key={f.q} delay={i * 70} className="glass p-6 text-left">
              <h3 className="text-sm font-medium text-white">{f.q}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{f.a}</p>
            </Reveal>
          ))}
        </div>
        <div className="mt-8 text-center">
          <Link to={PUBLIC_ROUTES.faq} className="text-sm text-secondary-100 transition-colors hover:text-secondary-200">See all FAQs →</Link>
        </div>
      </Section>

      {/* 7 — Coverage */}
      <Section eyebrow="Where we work" title="Kenya-wide, one platform">
        <Reveal className="glass mt-8 p-8">
          <p className="text-sm leading-relaxed text-white/60">
            SahilPay serves landlords and property managers across Kenya — from single apartments in Nairobi to
            estates and mixed-use portfolios up-country. Because it's cloud-based, you and your caretakers can
            manage properties from anywhere, on any device, and your tenants can pay and self-serve wherever they
            are. All you need is a browser.
          </p>
        </Reveal>
      </Section>

      {/* 8 — CTA */}
      <Section className="!py-20">
        <Reveal className="glass mx-auto max-w-4xl p-10 text-center sm:p-14">
          <h2 className="text-2xl font-light tracking-wide text-white sm:text-3xl">Let's get your rent collection sorted</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">Message us, or jump straight in with a free trial — no card required.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
            <Link to={PUBLIC_ROUTES.pricing}><Button variant="ghost" size="lg">See pricing</Button></Link>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
