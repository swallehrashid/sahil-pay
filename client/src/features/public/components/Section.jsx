import clsx from "clsx";
import Reveal from "./Reveal";

// A consistent marketing section: eyebrow + heading + lede, then children.
// Every public page is composed of these so spacing, rhythm and reveal
// animations stay identical across Home / Features / Pricing / About / Contact.
export default function Section({ id, eyebrow, title, lede, className, innerClassName, children, center = false }) {
  return (
    <section id={id} className={clsx("px-6 py-16 sm:py-20", className)}>
      <div className={clsx("mx-auto max-w-6xl", innerClassName)}>
        {(eyebrow || title || lede) && (
          <Reveal className={clsx("max-w-2xl", center && "mx-auto text-center")}>
            {eyebrow && (
              <span className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium uppercase tracking-wider text-secondary-100">
                {eyebrow}
              </span>
            )}
            {title && <h2 className="mt-4 text-2xl font-light tracking-wide text-white sm:text-3xl md:text-4xl">{title}</h2>}
            {lede && <p className="mt-4 text-sm leading-relaxed text-white/60 sm:text-base">{lede}</p>}
          </Reveal>
        )}
        {children}
      </div>
    </section>
  );
}
