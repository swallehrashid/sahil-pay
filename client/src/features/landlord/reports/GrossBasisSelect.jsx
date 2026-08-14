import Select from "@/components/ui/Select";

/**
 * Which collections count as the GROSS a report nets expenses and tax against.
 *
 *   All collections   every shilling of income — how a landlord running their
 *                     own block reads their books.
 *   Rent only         this month's rent plus rent arrears, and nothing else —
 *                     the base a Kenyan managing agent may charge commission
 *                     on. Deposits are the tenant's refundable money and
 *                     utilities are collected on the owner's behalf, so
 *                     neither may be commissioned.
 *
 * Deposits are excluded from BOTH options: held money is never income. The
 * choice only moves utilities and other charges in or out.
 *
 * `remember` persists the selection to the landlord's settings, so a manager
 * who always works rent-only sets it once instead of on every report.
 */

export const GROSS_BASIS_OPTIONS = [
  { value: "all", label: "All collections" },
  { value: "rent_only", label: "Rent only (excl. deposits)" },
];

export default function GrossBasisSelect({ value, onChange, className }) {
  return (
    <div className={className}>
      <Select
        label="Gross basis"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        options={GROSS_BASIS_OPTIONS}
      />
      {value === "rent_only" && (
        <p className="mt-1.5 text-xs leading-relaxed text-white/45">
          Commission is calculated on rent collected only — never on deposits.
        </p>
      )}
    </div>
  );
}
