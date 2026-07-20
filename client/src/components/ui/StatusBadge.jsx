import clsx from "clsx";
import { STATUS_BADGE_MAP, STATUS_BADGE_COLOR_CLASSES } from "@/utils/constants";

// Renders ANY status enum (invoice/payment/expense/maintenance/subscription/etc.) with its
// exact platform-wide color + label. Never hardcode a status color inline on a page.
export default function StatusBadge({ status, className }) {
  const entry = STATUS_BADGE_MAP[status] ?? { label: status ?? "—", color: "slate" };
  const colorClasses = STATUS_BADGE_COLOR_CLASSES[entry.color] ?? STATUS_BADGE_COLOR_CLASSES.slate;

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium capitalize",
        colorClasses,
        className
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {entry.label}
    </span>
  );
}
