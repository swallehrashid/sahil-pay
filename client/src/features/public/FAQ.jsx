import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ArrowRight } from "lucide-react";
import clsx from "clsx";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { SEO_FAQ_CATEGORIES, SEO_QUESTIONS } from "./content/seoContent";
import { useSeo, faqJsonLd } from "./useSeo";

function FaqItem({ item, isOpen, onToggle, delay }) {
  return (
    <Reveal delay={delay} className="glass overflow-hidden">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-4 px-6 py-4 text-left text-sm font-medium text-white transition-colors hover:bg-white/5"
      >
        <span>{item.q}</span>
        <ChevronDown className={clsx("h-4 w-4 flex-shrink-0 text-secondary transition-transform duration-300", isOpen && "rotate-180")} />
      </button>
      <div className={clsx("grid transition-all duration-300", isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
        <p className="overflow-hidden px-6 pb-4 text-sm leading-relaxed text-white/55">{item.a}</p>
      </div>
    </Reveal>
  );
}

export default function FAQ() {
  // Track the single open question by its stable id (first one open by default).
  const [openId, setOpenId] = useState(SEO_QUESTIONS[0]?.id);

  // FAQPage schema over the whole question bank — the block most likely to win
  // an expanded, multi-line search result rather than a plain blue link.
  const jsonLd = useMemo(() => faqJsonLd(SEO_QUESTIONS), []);

  useSeo({
    title: "Rental Management FAQs for Kenyan Landlords | Sahil Pay",
    description:
      "Answers to the questions Kenyan landlords and property managers ask about M-Pesa rent collection, automated invoicing, utility billing, tenant portals, arrears and reporting.",
    path: "/faq",
    jsonLd,
    jsonLdId: "faq",
  });

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden px-6 pb-8 pt-20 text-center sm:pt-24">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/25 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            {SEO_QUESTIONS.length} answers
          </span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">Frequently asked questions</h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            Everything landlords and property managers ask about rent collection, M-Pesa, the tenant portal,
            teams, reporting, pricing and security — answered.
          </p>
        </div>
      </section>

      {/* One section per category */}
      {SEO_FAQ_CATEGORIES.map((cat) => (
        <Section key={cat.category} eyebrow={cat.category} title={cat.category} className="!py-12">
          <div className="mt-8 space-y-3">
            {cat.questions.map((item, i) => (
              <FaqItem
                key={item.id}
                item={item}
                delay={Math.min(i, 6) * 50}
                isOpen={openId === item.id}
                onToggle={() => setOpenId(openId === item.id ? null : item.id)}
              />
            ))}
          </div>
        </Section>
      ))}

      {/* CTA */}
      <Section className="!py-20">
        <Reveal className="glass mx-auto max-w-4xl p-10 text-center sm:p-14">
          <h2 className="text-2xl font-light tracking-wide text-white sm:text-3xl">Still have a question?</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/60">Our team is happy to help — or start a free trial and see for yourself.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}><Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>Start free trial</Button></Link>
            <Link to={PUBLIC_ROUTES.contact}><Button variant="ghost" size="lg">Contact us</Button></Link>
          </div>
        </Reveal>
      </Section>
    </div>
  );
}
