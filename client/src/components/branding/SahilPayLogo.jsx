/**
 * SahilPay — components/branding/SahilPayLogo.jsx
 * ================================================
 * The single source of truth for rendering the Sahil Pay logo in the web app.
 * Everything is inline SVG + text driven by `currentColor`, so the logo takes
 * whatever text colour its parent has (white in dark sidebars, brand navy on
 * light surfaces) and scales crisply at any size.
 *
 *   <SahilPayMark className="h-8" />                      — house mark only (width follows height)
 *   <SahilPayLogo className="h-9" />                     — mark + wordmark + slogan
 *   <SahilPayLogo withSlogan={false} className="h-8" />  — mark + wordmark
 *
 * Size with a height class only (h-7 … h-12); width follows automatically.
 * Never stretch, never set width and height independently. `className` may
 * also carry visibility utilities (`hidden`, `sm:flex`, …) — see the note
 * on the outer span below for why those must land on their own element.
 */

export function SahilPayMark({ className = "h-8", ...props }) {
  // The mark's viewBox is a perfect square — `aspect-square` derives width from
  // whatever height class the caller passes, so a bare `h-N` (no `w-N`) never
  // collapses to the SVG's unconstrained intrinsic size.
  return (
    <svg
      viewBox="0 0 120 120"
      fill="none"
      className={`aspect-square ${className}`}
      role="img"
      aria-label="Sahil Pay"
      {...props}
    >
      <path
        d="M47 8 L86 50 C80 68 60 73 46 81 C33 88.5 25.5 97 24 112 L18 62 L6 62 Z"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinejoin="miter"
        fill="none"
      />
      <rect x="37" y="30" width="11" height="11" fill="currentColor" />
      <rect x="51" y="30" width="11" height="11" fill="currentColor" />
      <rect x="37" y="44" width="11" height="11" fill="currentColor" />
      <rect x="51" y="44" width="11" height="11" fill="currentColor" />
    </svg>
  );
}

export default function SahilPayLogo({
  className = "h-9",
  withSlogan = true,
  ...props
}) {
  // Sizing/visibility utilities the caller passes (h-N, hidden, sm:flex, …)
  // go on this OUTER span, unconditionally alone. `inline-flex` lives on an
  // INNER wrapper instead of sharing an element with `hidden` — otherwise
  // `hidden` and a hard-coded `inline-flex` are two unconditional
  // same-specificity utilities, and Tailwind v4's generated stylesheet
  // resolves that tie by class-discovery order across the whole build, not
  // by "the caller's override wins" — so `hidden` could silently lose.
  return (
    <span
      className={className}
      role="img"
      aria-label="Sahil Pay — Smart Rent Collection"
      {...props}
    >
      <span className="inline-flex h-full items-center gap-2 select-none">
        <SahilPayMark className="h-full w-auto shrink-0" aria-hidden="true" />
        <span className="flex flex-col justify-center leading-none">
          <span
            className="font-serif font-medium tracking-[0.14em] text-[1.05em]"
            style={{ fontFamily: "Cinzel, 'Playfair Display', Georgia, serif" }}
          >
            SAHIL&nbsp;PAY
          </span>
          {withSlogan && (
            <span className="mt-[0.2em] text-[0.34em] font-sans tracking-[0.42em] opacity-80">
              SMART&nbsp;RENT&nbsp;COLLECTION
            </span>
          )}
        </span>
      </span>
    </span>
  );
}
