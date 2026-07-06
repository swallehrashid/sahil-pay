import clsx from "clsx";

const COLOR_CLASSES = {
  white: "bg-white/10 text-white/80 border border-white/15",
  secondary: "bg-secondary/20 text-secondary-100 border border-secondary/40",
  third: "bg-third/20 text-third-100 border border-third/40",
  emerald: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  amber: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
};

export default function Badge({ children, color = "white", className }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        COLOR_CLASSES[color] ?? COLOR_CLASSES.white,
        className
      )}
    >
      {children}
    </span>
  );
}
