import { ShieldCheck, Globe2, HeartHandshake } from "lucide-react";

const VALUES = [
  { icon: ShieldCheck, title: "Built on trust", text: "Every action is audit-logged — nothing happens silently." },
  { icon: Globe2, title: "Made for Kenya", text: "M-Pesa paybill/till, KES by default, Africa/Nairobi timezone." },
  { icon: HeartHandshake, title: "Hands-on support", text: "Consent-based onboarding assistance whenever you need it." },
];

export default function About() {
  return (
    <section className="mx-auto max-w-4xl px-6 py-24">
      <h1 className="animate-fade-in-up text-3xl font-light text-white">About SahilPay</h1>
      <p className="mt-4 animate-fade-in-up text-white/60" style={{ animationDelay: "80ms" }}>
        SahilPay was built for landlords, property managers and caretakers across Kenya who are
        tired of juggling spreadsheets, paper receipts and scattered M-Pesa messages. We bring
        the entire rent-collection workflow — invoicing, payments, communications, maintenance
        and reporting — onto one premium, mobile-friendly platform.
      </p>
      <div className="mt-12 grid gap-6 sm:grid-cols-3">
        {VALUES.map((item, index) => (
          <div key={item.title} className="glass animate-fade-in-up p-6" style={{ animationDelay: `${160 + index * 80}ms` }}>
            <item.icon className="h-6 w-6 text-secondary" />
            <h3 className="mt-3 text-base font-medium text-white">{item.title}</h3>
            <p className="mt-2 text-sm text-white/50">{item.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
