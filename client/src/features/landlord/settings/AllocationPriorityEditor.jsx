import { ChevronUp, ChevronDown } from "lucide-react";

// Order in which an auto-allocated payment clears a tenant's charges. Highest
// (top) is paid first. Stored as a CSV of category keys on the landlord — must
// match server/services/allocation_service.py ALLOCATION_CATEGORIES.
export const ALLOCATION_CATEGORIES = [
  { key: "deposits", label: "Deposits (rent/utility/security deposits)" },
  { key: "utilities_cf", label: "Utility balances — carried forward" },
  { key: "rent_cf", label: "Rent balance — carried forward" },
  { key: "utilities_current", label: "Utilities — current month" },
  { key: "rent_current", label: "Rent — current month" },
  { key: "other", label: "Other charges (penalties, custom)" },
];

const LABELS = Object.fromEntries(ALLOCATION_CATEGORIES.map((c) => [c.key, c.label]));
const ALL_KEYS = ALLOCATION_CATEGORIES.map((c) => c.key);

function parseOrder(csv) {
  const listed = (csv || "").split(",").map((k) => k.trim()).filter((k) => ALL_KEYS.includes(k));
  for (const k of ALL_KEYS) if (!listed.includes(k)) listed.push(k);
  return listed;
}

export default function AllocationPriorityEditor({ value, onChange }) {
  const order = parseOrder(value);

  const move = (index, delta) => {
    const next = [...order];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next.join(","));
  };

  return (
    <div>
      <p className="mb-1.5 text-sm font-medium text-white/70">Auto-allocation priority</p>
      <p className="mb-3 text-xs text-white/40">
        When you auto-allocate a confirmed payment, it clears these in order — top first.
      </p>
      <ul className="space-y-2">
        {order.map((key, i) => (
          <li key={key} className="flex items-center gap-3 rounded-xl bg-white/5 px-3 py-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary/20 text-xs font-semibold text-white">{i + 1}</span>
            <span className="flex-1 text-sm text-white/80">{LABELS[key]}</span>
            <div className="flex flex-col">
              <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className="text-white/40 hover:text-white disabled:opacity-20">
                <ChevronUp className="h-4 w-4" />
              </button>
              <button type="button" onClick={() => move(i, 1)} disabled={i === order.length - 1} className="text-white/40 hover:text-white disabled:opacity-20">
                <ChevronDown className="h-4 w-4" />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
