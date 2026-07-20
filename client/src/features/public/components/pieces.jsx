import clsx from "clsx";
import { Check } from "lucide-react";
import Reveal from "./Reveal";

// Small shared building blocks for the marketing pages, so every card, bullet
// and stat looks identical across Home / Features / Pricing / About / Contact.

export function FeatureCard({ icon: Icon, title, children, accent = "secondary", delay = 0 }) {
  return (
    <Reveal
      delay={delay}
      className="glass card-hover group h-full p-6"
    >
      <span
        className={clsx(
          "inline-flex rounded-xl p-3 transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-3",
          accent === "third" ? "bg-third/15 text-third-100" : "bg-secondary/15 text-secondary-200"
        )}
      >
        <Icon className="h-5 w-5" />
      </span>
      <h3 className="mt-4 text-base font-medium text-white">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-white/55">{children}</p>
    </Reveal>
  );
}

export function CheckItem({ children, className }) {
  return (
    <li className={clsx("flex items-start gap-2.5 text-sm text-white/70", className)}>
      <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-secondary" />
      <span>{children}</span>
    </li>
  );
}

export function StatTile({ value, label, delay = 0 }) {
  return (
    <Reveal delay={delay} className="glass card-hover p-6 text-center">
      <p className="bg-gradient-to-br from-white to-secondary-200 bg-clip-text text-3xl font-light text-transparent sm:text-4xl">
        {value}
      </p>
      <p className="mt-2 text-xs uppercase tracking-wider text-white/45">{label}</p>
    </Reveal>
  );
}

// A glass "product panel" that stands in for a screenshot — a titled card with
// a list of rows, used in the alternating split sections.
export function MockPanel({ title, rows = [], accent = "secondary" }) {
  return (
    <Reveal className="glass relative overflow-hidden p-6">
      <div
        className={clsx(
          "absolute -right-16 -top-16 h-40 w-40 rounded-full blur-3xl",
          accent === "third" ? "bg-third/30" : "bg-secondary/25"
        )}
      />
      <div className="relative">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-secondary/70" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
          <span className="ml-2 text-xs font-medium text-white/50">{title}</span>
        </div>
        <div className="mt-4 space-y-2.5">
          {rows.map((row, i) => (
            <div
              key={i}
              className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm transition-colors hover:bg-white/10"
            >
              <span className="text-white/70">{row.label}</span>
              <span className={clsx("font-medium", row.strong ? "text-secondary-100" : "text-white/50")}>{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </Reveal>
  );
}
