import clsx from "clsx";
import { useEffect, useState } from "react";

// The dashboard stat tile used for arrears/occupancy/totals everywhere. Pass a pre-formatted
// string (e.g. via currencyFormatter) for money, or a plain number with isCountUp for %/counts.
export default function SummaryCard({ label, value, icon, accent = "secondary", trend, isCountUp = false }) {
  const [animatedValue, setAnimatedValue] = useState(0);
  const shouldAnimate = isCountUp && typeof value === "number";

  useEffect(() => {
    if (!shouldAnimate) return;
    const duration = 600;
    const start = performance.now();
    let frame;
    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration);
      setAnimatedValue(Math.round(value * progress));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, shouldAnimate]);

  const display = shouldAnimate ? animatedValue : value;

  return (
    <div className="glass card-hover animate-fade-in-up p-6">
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-white/50">{label}</p>
        {icon && (
          <span
            className={clsx(
              "rounded-xl p-2",
              accent === "secondary" ? "bg-secondary/15 text-secondary-200" : "bg-third/15 text-third-100"
            )}
          >
            {icon}
          </span>
        )}
      </div>
      <p className="mt-3 text-2xl font-light tracking-wide text-white">{display}</p>
      {trend && (
        <p className={clsx("mt-2 text-xs font-medium", trend.positive ? "text-emerald-400" : "text-secondary-300")}>
          {trend.label}
        </p>
      )}
    </div>
  );
}
