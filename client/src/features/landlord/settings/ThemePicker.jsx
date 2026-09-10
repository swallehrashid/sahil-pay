import clsx from "clsx";
import { Check } from "lucide-react";

/**
 * Pick the two colours every receipt, statement and report is drawn in.
 *
 * Two colours with fixed ROLES rather than a free colour picker, and a closed
 * palette rather than a hex field. Both constraints exist for the same reason:
 * these end up as ink on white paper, printed on an office laser and then
 * photographed by a tenant. A free picker produces pale yellow on white, and
 * nobody finds out until a tenant says they cannot read their receipt.
 *
 * Fills behind table headers and total rows are DERIVED from the primary, not
 * chosen — which is what makes all 36 combinations legible without anyone
 * having checked 36 combinations.
 */
function Swatch({ color, selected, onSelect, disabled, disabledReason }) {
  return (
    <button
      type="button"
      title={disabled ? disabledReason : color.label}
      aria-label={color.label}
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => onSelect(color.hex)}
      className={clsx(
        "relative h-8 w-8 rounded-full border transition-all",
        selected ? "border-white ring-2 ring-white/70" : "border-white/25 hover:border-white/60",
        disabled && "cursor-not-allowed opacity-25"
      )}
      style={{ backgroundColor: color.hex }}
    >
      {selected && (
        <Check className="absolute inset-0 m-auto h-4 w-4 text-white drop-shadow" strokeWidth={3} />
      )}
    </button>
  );
}

function Row({ role, label, description, value, otherValue, families, onChange }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-white/80">{label}</p>
        <span className="font-mono text-xs text-white/40">{value}</span>
      </div>
      <p className="text-xs leading-snug text-white/45">{description}</p>
      <div className="space-y-2">
        {families.map((family) => (
          <div key={family.name} className="flex flex-wrap items-center gap-1.5">
            <span className="w-14 flex-shrink-0 text-[10px] uppercase tracking-wider text-white/30">
              {family.name}
            </span>
            {family.colors.map((color) => (
              <Swatch
                key={color.key}
                color={color}
                selected={value?.toLowerCase() === color.hex.toLowerCase()}
                disabled={otherValue?.toLowerCase() === color.hex.toLowerCase()}
                disabledReason={`Already used as the ${role === "primary" ? "secondary" : "primary"} colour`}
                onSelect={(hex) => onChange(hex)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ThemePicker({ palette, theme, isDefault, onChange }) {
  if (!palette || !theme) return null;

  return (
    <section className="glass space-y-5 p-5">
      <div>
        <h3 className="text-sm font-medium text-white">Colours</h3>
        <p className="mt-1 text-xs leading-relaxed text-white/45">
          Applies to <strong className="text-white/70">every receipt, statement and
          report</strong> — not just receipts, so a statement and a receipt from you
          never come out looking like two different companies.
          {isDefault && " You are currently on the Sahil Pay default."}
        </p>
      </div>

      {/* What the two colours will look like together, before rendering a PDF. */}
      <div className="overflow-hidden rounded-lg bg-white">
        <div className="px-3 py-2" style={{ borderBottom: `2px solid ${theme.secondary}` }}>
          <div className="text-sm font-semibold" style={{ color: theme.primary }}>
            Your Company Ltd
          </div>
          <div className="text-[10px]" style={{ color: theme.primary, opacity: 0.6 }}>
            Payment Receipt
          </div>
        </div>
        <table className="w-full text-[11px]">
          <thead>
            <tr style={{ background: `${theme.primary}14`, color: theme.primary }}>
              <th className="px-3 py-1 text-left font-semibold">Item</th>
              <th className="px-3 py-1 text-right font-semibold">Paid</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ color: theme.primary }}>
              <td className="px-3 py-1">Rent — this month</td>
              <td className="px-3 py-1 text-right">KES 25,000.00</td>
            </tr>
            <tr style={{ color: theme.primary, borderTop: `2px solid ${theme.secondary}`, background: `${theme.secondary}0d` }}>
              <td className="px-3 py-1 font-bold">Amount paid</td>
              <td className="px-3 py-1 text-right font-bold">KES 25,000.00</td>
            </tr>
          </tbody>
        </table>
      </div>

      <Row
        role="primary"
        label="Primary"
        description={palette.roles.primary}
        value={theme.primary}
        otherValue={theme.secondary}
        families={palette.families}
        onChange={(hex) => onChange({ ...theme, primary: hex })}
      />
      <Row
        role="secondary"
        label="Secondary"
        description={palette.roles.secondary}
        value={theme.secondary}
        otherValue={theme.primary}
        families={palette.families}
        onChange={(hex) => onChange({ ...theme, secondary: hex })}
      />

      <button
        type="button"
        onClick={() => onChange({ ...palette.default })}
        className="text-xs text-white/40 underline-offset-2 hover:text-secondary hover:underline"
      >
        Reset to the Sahil Pay colours
      </button>
    </section>
  );
}
