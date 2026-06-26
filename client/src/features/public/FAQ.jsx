import { useState } from "react";
import { ChevronDown } from "lucide-react";
import clsx from "clsx";

const FAQS = [
  { q: "Do I need a card to start my trial?", a: "No — every new landlord account starts with a free trial, no payment details required." },
  { q: "Does SahilPay support M-Pesa paybill and till?", a: "Yes, both paybill and till are supported, with automatic transaction matching and a manual status-check tool." },
  { q: "Can I give my caretaker limited access?", a: "Yes — team members get a per-module view/edit permission matrix, scoped to specific properties if needed." },
  { q: "How do tenants log in?", a: "Tenants never need a password — they log in with a one-time code sent to their phone or email." },
  { q: "Can I export my data?", a: "Yes, every report and statement can be downloaded as PDF or Excel, and scoped backups are available any time." },
];

export default function FAQ() {
  const [openIndex, setOpenIndex] = useState(0);

  return (
    <section className="mx-auto max-w-3xl px-6 py-24">
      <h1 className="animate-fade-in-up text-center text-3xl font-light text-white">Frequently asked questions</h1>
      <div className="mt-12 space-y-3">
        {FAQS.map((item, index) => {
          const isOpen = openIndex === index;
          return (
            <div key={item.q} className="glass animate-fade-in-up overflow-hidden" style={{ animationDelay: `${index * 60}ms` }}>
              <button
                onClick={() => setOpenIndex(isOpen ? -1 : index)}
                className="flex w-full items-center justify-between px-6 py-4 text-left text-sm font-medium text-white"
              >
                {item.q}
                <ChevronDown className={clsx("h-4 w-4 transition-transform duration-300", isOpen && "rotate-180")} />
              </button>
              <div className={clsx("grid transition-all duration-300", isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
                <p className="overflow-hidden px-6 pb-4 text-sm text-white/50">{item.a}</p>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
