import { useState } from "react";
import clsx from "clsx";
import { Building2, ChevronDown, Check, Info } from "lucide-react";
import { useGetPortalContextQuery } from "../tenantPortalApiSlice";
import { setSelectedTenantId } from "@/utils/tenantUnitStorage";
import { formatCurrency } from "@/utils/currencyFormatter";

/**
 * Switches between the units one person rents.
 *
 * A tenant can hold two units in one block and another under a completely
 * different landlord. Those are separate tenancies with separate account
 * numbers, invoices and balances — so this shows ONE at a time and groups the
 * list by landlord, rather than pretending there is a combined account.
 *
 * Renders nothing when the person rents a single unit, which is almost
 * everybody: no reason to add a control that does nothing.
 */
export default function UnitSwitcher({ className }) {
  const { data, isLoading } = useGetPortalContextQuery();
  const [open, setOpen] = useState(false);

  if (isLoading || !data || data.unit_count <= 1) return null;

  const current = data.units.find((u) => u.tenant_id === data.current_tenant_id);

  // Group by landlord: two units from the same company belong together, and a
  // unit from another landlord is genuinely a separate relationship.
  const groups = data.units.reduce((acc, unit) => {
    const key = unit.landlord_name || "Your landlord";
    (acc[key] ??= []).push(unit);
    return acc;
  }, {});

  function choose(unit) {
    setSelectedTenantId(unit.tenant_id);
    setOpen(false);
    // Everything on screen belongs to the old unit — reload so no stale
    // balance from the previous tenancy is left showing.
    window.location.reload();
  }

  return (
    <div className={clsx("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        className="glass flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors hover:bg-white/5"
      >
        <span className="flex min-w-0 items-center gap-3">
          <Building2 className="h-4 w-4 flex-shrink-0 text-secondary" />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-white">
              {current?.unit_name ?? "Select a unit"}
            </span>
            <span className="block truncate text-xs text-white/50">
              {current?.property_name}
              {current?.landlord_name ? ` · ${current.landlord_name}` : ""}
            </span>
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-medium text-white/60">
            {data.unit_count} units
          </span>
          <ChevronDown className={clsx("h-4 w-4 text-white/40 transition-transform", open && "rotate-180")} />
        </span>
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 right-0 z-30 mt-2 overflow-hidden rounded-xl border border-white/15 bg-primary-900 shadow-2xl"
        >
          {Object.entries(groups).map(([landlordName, units]) => (
            <div key={landlordName}>
              <div className="border-b border-white/10 bg-white/[0.03] px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-white/40">
                {landlordName}
              </div>
              {units.map((unit) => {
                const selected = unit.tenant_id === data.current_tenant_id;
                const owing = unit.balance < 0;
                return (
                  <button
                    key={unit.tenant_id}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => choose(unit)}
                    className={clsx(
                      "flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors",
                      selected ? "bg-secondary/10" : "hover:bg-white/5"
                    )}
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 text-sm text-white">
                        {unit.unit_name}
                        {selected && <Check className="h-3 w-3 text-secondary" />}
                      </span>
                      <span className="block truncate text-xs text-white/45">
                        {unit.property_name} · Acct {unit.account_number}
                      </span>
                    </span>
                    <span
                      className={clsx(
                        "flex-shrink-0 text-xs font-medium tabular-nums",
                        owing ? "text-amber-300" : "text-emerald-300"
                      )}
                    >
                      {owing
                        ? `${formatCurrency(Math.abs(unit.balance))} due`
                        : "Cleared"}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}

          {data.note && (
            <p className="flex items-start gap-2 border-t border-white/10 bg-white/[0.02] px-4 py-3 text-xs leading-relaxed text-white/50">
              <Info className="mt-0.5 h-3 w-3 flex-shrink-0 text-white/40" />
              {data.note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
