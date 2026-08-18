import { useMemo, useState } from "react";
import { AlertTriangle, Filter, Gavel } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import { usePermissions } from "@/hooks/usePermissions";
import { useGetPropertiesQuery } from "@/features/landlord/properties/propertyApiSlice";
import {
  useGetPenaltyCandidatesQuery,
  useRunBatchPenaltiesMutation,
} from "./penaltyApiSlice";

/**
 * Charge a penalty to many tenants at once, deliberately.
 *
 * The automatic engine in Settings applies a standing policy on a schedule.
 * This is the other thing: "everyone in Riverside more than ten days late gets
 * 500 this month" is a decision, not a rule, and it needs a list you can read
 * and edit before any money moves.
 *
 * Three deliberate choices in this screen:
 *
 *   Nothing is charged until the list is confirmed. The filters produce
 *   candidates; the run charges only the ticked rows, sent by id — so somebody
 *   paying between the preview and the run cannot quietly change who is fined.
 *
 *   Tenants already penalised this month are shown and unticked rather than
 *   hidden. A shorter list with no explanation just looks wrong.
 *
 *   The amount can be a percentage of what is owed, because a flat fee is
 *   punitive on a 2,000 arrear and trivial on a 200,000 one.
 */
export default function BatchPenaltyRun() {
  const { can } = usePermissions();
  const canCharge = can("penalties", "edit");

  const { data: propertiesData } = useGetPropertiesQuery();
  const properties = toRows(propertiesData);

  const [filters, setFilters] = useState({
    property_ids: "", min_balance: "", max_balance: "", min_days_overdue: "",
  });
  const [applied, setApplied] = useState({});
  const [mode, setMode] = useState("flat");
  const [flat, setFlat] = useState("500");
  const [percentage, setPercentage] = useState("5");
  const [target, setTarget] = useState("existing");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);

  const { data, isFetching } = useGetPenaltyCandidatesQuery(applied);
  const [runBatch, { isLoading: running }] = useRunBatchPenaltiesMutation();

  const candidates = useMemo(() => data?.candidates ?? [], [data]);

  // Pre-tick everyone the run would actually charge, leaving out those already
  // penalised this month — the common intent, without hiding the exceptions.
  const defaultSelection = useMemo(
    () => new Set(candidates.filter((c) => !c.already_charged_this_month)
                            .map((c) => c.tenant_id)),
    [candidates]
  );

  // DERIVED, not synced. Writing the default into state from an effect causes a
  // cascading render on every refetch, and — worse — silently discards the
  // user's ticks the moment the query revalidates. Instead the override carries
  // the result it belongs to, so a new result falls back to the fresh default
  // on its own.
  const [override, setOverride] = useState({ forData: null, ids: null });
  const selected = override.forData === data && override.ids
    ? override.ids
    : defaultSelection;

  const setSelected = (next) =>
    setOverride({ forData: data, ids: typeof next === "function" ? next(selected) : next });

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const estimate = useMemo(() => {
    const chosen = candidates.filter((c) => selected.has(c.tenant_id));
    if (mode === "percentage") {
      const rate = Number(percentage) || 0;
      return chosen.reduce((sum, c) => sum + (c.arrears * rate) / 100, 0);
    }
    return chosen.length * (Number(flat) || 0);
  }, [candidates, selected, mode, flat, percentage]);

  const applyFilters = () => {
    const next = {};
    if (filters.property_ids) next.property_ids = filters.property_ids;
    if (filters.min_balance) next.min_balance = filters.min_balance;
    if (filters.max_balance) next.max_balance = filters.max_balance;
    if (filters.min_days_overdue) next.min_days_overdue = filters.min_days_overdue;
    setApplied(next);
  };

  const doRun = async () => {
    try {
      const result = await runBatch({
        tenant_ids: [...selected],
        ...(mode === "percentage"
          ? { percentage: Number(percentage) }
          : { flat: Number(flat) }),
        target,
        note: note.trim() || undefined,
      }).unwrap();
      toast(
        `${result.charged.length} charged (${formatCurrency(result.total_charged)}), ` +
        `${result.skipped.length} skipped.`,
        { type: "success" }
      );
    } catch (err) {
      toast(err?.data?.message || "The run failed.", { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-sm leading-relaxed text-white/50">
        Charge a late fee to several tenants at once. Filter to the people you
        mean, check the list, then run it — nothing is charged until you confirm.
        For a standing rule that applies itself every month, use{" "}
        <span className="text-white/70">Settings → Penalties</span> instead.
      </p>

      {/* Filters ------------------------------------------------------- */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <h3 className="flex items-center gap-2 text-sm font-medium text-white/80">
          <Filter className="h-4 w-4" /> Who
        </h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Select
            label="Property"
            value={filters.property_ids}
            onChange={(e) => setFilters((f) => ({ ...f, property_ids: e.target.value }))}
            options={[
              { value: "", label: "All properties" },
              ...properties.map((p) => ({ value: String(p.id), label: p.name })),
            ]}
          />
          <Input
            label="Owes at least" type="number" value={filters.min_balance}
            placeholder="e.g. 5000"
            onChange={(e) => setFilters((f) => ({ ...f, min_balance: e.target.value }))}
          />
          <Input
            label="Owes at most" type="number" value={filters.max_balance}
            placeholder="no limit"
            onChange={(e) => setFilters((f) => ({ ...f, max_balance: e.target.value }))}
          />
          <Input
            label="Days overdue (min)" type="number" value={filters.min_days_overdue}
            placeholder="e.g. 10"
            hint="Counted from their oldest unpaid invoice."
            onChange={(e) => setFilters((f) => ({ ...f, min_days_overdue: e.target.value }))}
          />
        </div>
        <Button variant="ghost" onClick={applyFilters} isLoading={isFetching}>
          Find tenants
        </Button>
      </div>

      {/* The list ------------------------------------------------------ */}
      {candidates.length === 0 ? (
        <EmptyState
          title="Nobody matches"
          description="No tenant in scope owes anything under these filters."
        />
      ) : (
        <div className="glass overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 text-white/40">
                <th className="px-3 py-2">
                  <Checkbox
                    checked={selected.size === candidates.length && candidates.length > 0}
                    onChange={(e) =>
                      setSelected(e.target.checked
                        ? new Set(candidates.map((c) => c.tenant_id))
                        : new Set())
                    }
                  />
                </th>
                <th className="px-3 py-2 font-medium">Tenant</th>
                <th className="px-3 py-2 font-medium">Unit</th>
                <th className="px-3 py-2 font-medium">Owes</th>
                <th className="px-3 py-2 font-medium">Overdue</th>
                <th className="px-3 py-2 font-medium">Open invoice</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => (
                <tr key={c.tenant_id} className="border-b border-white/5 last:border-0">
                  <td className="px-3 py-2">
                    <Checkbox
                      checked={selected.has(c.tenant_id)}
                      onChange={() => toggle(c.tenant_id)}
                    />
                  </td>
                  <td className="px-3 py-2 text-white/85">
                    {c.tenant_name}
                    {c.already_charged_this_month && (
                      <Badge color="white" className="ml-2">already charged</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-white/60">
                    {c.property_name} · {c.unit_name}
                  </td>
                  <td className="px-3 py-2 text-white/85">{formatCurrency(c.arrears)}</td>
                  <td className="px-3 py-2 text-white/60">{c.days_overdue}d</td>
                  <td className="px-3 py-2 text-white/40">
                    {c.open_invoice_number || "none"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* The charge ---------------------------------------------------- */}
      {candidates.length > 0 && canCharge && (
        <div className="glass space-y-4 p-5 sm:p-6">
          <h3 className="flex items-center gap-2 text-sm font-medium text-white/80">
            <Gavel className="h-4 w-4" /> How much, and where it goes
          </h3>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Select
              label="Amount"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              options={[
                { value: "flat", label: "A flat amount each" },
                { value: "percentage", label: "% of what they owe" },
              ]}
            />
            {mode === "flat" ? (
              <Input label="Amount" type="number" value={flat}
                     onChange={(e) => setFlat(e.target.value)} />
            ) : (
              <Input label="Percentage" type="number" value={percentage}
                     hint="Proportionate across very different arrears."
                     onChange={(e) => setPercentage(e.target.value)} />
            )}
            <Select
              label="Bill it on"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              options={[
                { value: "existing", label: "Their open invoice (one bill)" },
                { value: "new", label: "A new penalty invoice" },
              ]}
            />
          </div>

          <Input
            label="Note (optional)"
            value={note}
            placeholder="e.g. August late fee"
            hint="Appears on the invoice line and in the audit trail."
            onChange={(e) => setNote(e.target.value)}
          />

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
            <p className="text-sm text-white/60">
              <span className="text-white">{selected.size}</span> tenant
              {selected.size === 1 ? "" : "s"} selected ·{" "}
              <span className="text-white">{formatCurrency(estimate)}</span> total
            </p>
            <Button onClick={() => setConfirming(true)} disabled={selected.size === 0}>
              Charge {selected.size} tenant{selected.size === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      )}

      {!canCharge && candidates.length > 0 && (
        <p className="flex items-center gap-2 text-sm text-white/40">
          <AlertTriangle className="h-4 w-4" />
          You can see who is in arrears, but not raise penalties.
        </p>
      )}

      <ConfirmDialog
        isOpen={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={doRun}
        isLoading={running}
        title={`Charge ${selected.size} tenant${selected.size === 1 ? "" : "s"}?`}
        // Spell out the consequence: this is real money on real accounts, and
        // the reversal is manual.
        description={
          `This adds ${mode === "percentage" ? `${percentage}% of what each owes` : formatCurrency(Number(flat) || 0)} ` +
          `to ${target === "existing" ? "their open invoice" : "a new penalty invoice"}, ` +
          `about ${formatCurrency(estimate)} in total. Tenants already penalised this ` +
          `month are skipped automatically.`
        }
        confirmLabel="Charge them"
      />
    </div>
  );
}
