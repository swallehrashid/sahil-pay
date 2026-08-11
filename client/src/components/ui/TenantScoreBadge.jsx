import clsx from "clsx";

/**
 * A tenant's payment score, 0–100.
 *
 * Shown in all four portals, so it lives in the shared component folder and is
 * the ONE place the colour thresholds are defined — a score that reads
 * "Excellent" green on the landlord's list and amber on the admin's would make
 * the number useless.
 *
 * `null` is not zero. A tenant with under two completed months has no record to
 * judge, and is shown as a neutral "New" — scoring them 100 would flatter
 * someone nobody has any evidence about, which is exactly backwards when the
 * number is meant to support a credit decision.
 */

const BANDS = [
  { min: 90, label: "Excellent", classes: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", ring: "text-emerald-400" },
  { min: 75, label: "Good",      classes: "bg-lime-500/15 text-lime-300 border-lime-500/30",          ring: "text-lime-400" },
  { min: 60, label: "Fair",      classes: "bg-amber-500/15 text-amber-300 border-amber-500/30",       ring: "text-amber-400" },
  { min: 40, label: "Poor",      classes: "bg-orange-500/15 text-orange-300 border-orange-500/30",    ring: "text-orange-400" },
  { min: 0,  label: "High risk", classes: "bg-red-500/15 text-red-300 border-red-500/30",             ring: "text-red-400" },
];

const NEW_TENANT = {
  label: "New",
  classes: "bg-white/8 text-white/50 border-white/15",
  ring: "text-white/30",
};

export function scoreBand(score) {
  if (score === null || score === undefined) return NEW_TENANT;
  return BANDS.find((b) => score >= b.min) ?? BANDS[BANDS.length - 1];
}

/** Compact pill — for table cells and lists. */
export default function TenantScoreBadge({ score, showLabel = true, className }) {
  const band = scoreBand(score);
  const isNew = score === null || score === undefined;

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
        band.classes,
        className
      )}
      title={
        isNew
          ? "Not enough payment history yet — a score needs at least two completed months."
          : `Payment score ${score} out of 100 — ${band.label.toLowerCase()}`
      }
    >
      <span className="font-semibold tabular-nums">{isNew ? "—" : score}</span>
      {showLabel && <span className="opacity-80">{band.label}</span>}
    </span>
  );
}

/**
 * The larger dial, for a tenant's detail header and their own portal dashboard.
 * Drawn with an SVG arc rather than a bar so the number reads as a rating
 * rather than as progress toward something.
 */
export function TenantScoreDial({ score, size = 96, className }) {
  const band = scoreBand(score);
  const isNew = score === null || score === undefined;
  const value = isNew ? 0 : Math.max(0, Math.min(100, score));

  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (value / 100) * circumference;

  return (
    <div className={clsx("inline-flex flex-col items-center gap-2", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" strokeWidth={stroke}
            className="text-white/10" stroke="currentColor"
          />
          {!isNew && (
            <circle
              cx={size / 2} cy={size / 2} r={radius}
              fill="none" strokeWidth={stroke} strokeLinecap="round"
              strokeDasharray={`${dash} ${circumference - dash}`}
              className={band.ring} stroke="currentColor"
            />
          )}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-light tabular-nums text-white">
            {isNew ? "—" : value}
          </span>
          {!isNew && <span className="text-[10px] uppercase tracking-wider text-white/40">out of 100</span>}
        </div>
      </div>
      <span className={clsx("rounded-full border px-2.5 py-0.5 text-xs font-medium", band.classes)}>
        {band.label}
      </span>
    </div>
  );
}
