import { useMemo, useState } from "react";
import clsx from "clsx";
import { Check, FileText, Play } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Checkbox from "@/components/ui/Checkbox";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { useGetOwnerPayoutsQuery } from "@/features/landlord/ownerPayoutApiSlice";
import {
  usePreviewPayoutsQuery,
  useGeneratePayoutsMutation,
  useMarkPayoutPaidMutation,
} from "./allocationApiSlice";

// sahilpay_payment_allocation_spec.md §4.10 — the payout dashboard.
//
// Preview what each owner is owed for a period, generate the payouts, then mark
// them paid with a method and M-Pesa code. v1 is TRACK-ONLY: no B2C automation,
// the manager still sends the money themselves.
//
// Mobile-first: previews are stacked cards with the figures in a two-column
// grid, and the recorded payouts go through ResponsiveTable.

function monthStart() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

const PAID_METHODS = [
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank transfer" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

function MarkPaidModal({ payout, onClose }) {
  const [markPaid, { isLoading }] = useMarkPayoutPaidMutation();
  const [form, setForm] = useState({ method: "mpesa", reference: "", paid_on: today() });

  const submit = async () => {
    try {
      await markPaid({ payoutId: payout.id, ...form }).unwrap();
      toast("Marked paid.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not mark that payout paid.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Mark payout #${payout.id} paid`} size="md">
      <div className="space-y-4">
        <p className="text-sm text-white/50">
          Recording that you&apos;ve sent {formatCurrency(payout.net_payable ?? payout.amount)}
          {payout.owner_name ? ` to ${payout.owner_name}` : ""}.
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Select label="Method" value={form.method} options={PAID_METHODS}
                  onChange={(e) => setForm((f) => ({ ...f, method: e.target.value }))} />
          <Input type="date" label="Paid on" value={form.paid_on}
                 onChange={(e) => setForm((f) => ({ ...f, paid_on: e.target.value }))} />
        </div>
        <Input label="Reference" value={form.reference} placeholder="M-Pesa code"
               onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))} />
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="button" onClick={submit} isLoading={isLoading}>Mark paid</Button>
        </div>
      </div>
    </Modal>
  );
}

const BASIS_OPTIONS = [
  { value: "rent", label: "Rent only",
    hint: "Rent balance brought forward plus this month's rent." },
  { value: "collected", label: "Total collected",
    hint: "Every charge type ticked above." },
];

/**
 * What counts as "Collected", and what commission is charged on.
 *
 * Both are decisions, not arithmetic. A managing agent does not necessarily
 * remit the water float or a deposit they are holding, and whether commission
 * comes off rent alone or off everything is a commercial term that differs per
 * account. Leaving either as an invisible constant meant the Collected column
 * silently disagreed with what the agent actually owed.
 *
 * Rent is fixed on: a payout with no rent in it is not a payout, and the rent
 * figure is what tax is computed on regardless. It is rendered as a ticked,
 * disabled box rather than hidden, so the total on screen is fully accounted
 * for by the boxes above it.
 */
function CollectedPicker({ categories, included, onToggle, basis, onBasis }) {
  if (!categories.length) return null;

  return (
    <div className="glass space-y-4 p-4 sm:p-5">
      <div>
        <h3 className="text-sm font-medium text-white/80">What counts as collected</h3>
        <p className="mt-1 text-xs text-white/40">
          Tick the charge types to include. The Collected column, and every
          payout you generate, is the sum of these.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {/* A div, not a label. Checkbox renders its own <label>, and nesting
            one inside another is invalid HTML whose click behaviour differs
            between browsers — exactly the wrong thing under a money total. */}
        {categories.map((cat) => (
          <div
            key={cat.key}
            className={clsx(
              "flex items-center justify-between gap-3 rounded-xl border px-3 py-2.5 transition-colors",
              cat.required
                ? "border-secondary/40 bg-secondary/10"
                : "border-white/10 bg-white/5 hover:border-white/25",
            )}
          >
            <Checkbox
              id={`collected-${cat.key}`}
              checked={cat.required || included.includes(cat.key)}
              disabled={cat.required}
              onChange={() => onToggle(cat.key)}
              className="min-w-0"
              label={
                <span className="min-w-0">
                  <span className="block truncate text-white/85">{cat.label}</span>
                  {cat.required && (
                    <span className="block text-[11px] text-secondary/80">Always included</span>
                  )}
                </span>
              }
            />
            <span className="flex-shrink-0 text-sm tabular-nums text-white/60">
              {formatCurrency(cat.amount)}
            </span>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10 pt-4">
        <h3 className="text-sm font-medium text-white/80">Charge commission on</h3>
        <p className="mt-1 text-xs text-white/40">
          Commission is charged on rent by default, which is ordinary practice.
          Switch it to the total only if that is what you have agreed with the
          owner — it changes what they are invoiced.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {BASIS_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={basis === option.value}
              onClick={() => onBasis(option.value)}
              className={clsx(
                "rounded-xl border px-3 py-2.5 text-left transition-colors duration-200",
                basis === option.value
                  ? "border-secondary bg-secondary/15 text-white"
                  : "border-white/10 bg-white/5 text-white/60 hover:border-white/25 hover:text-white/85",
              )}
            >
              <span className="block text-sm font-medium">{option.label}</span>
              <span className="mt-0.5 block text-[11px] text-white/45">{option.hint}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function PayoutsPage() {
  const [range, setRange] = useState({ period_start: monthStart(), period_end: today() });
  // Which charge types count, and what commission is charged on. Rent is not
  // held here — the server forces it in regardless, so keeping it in local
  // state would just be a second place for it to be wrong.
  const [included, setIncluded] = useState(["rent"]);
  const [basis, setBasis] = useState("rent");

  const query = useMemo(
    () => ({ ...range, include: included, commission_basis: basis }),
    [range, included, basis],
  );
  const { data: preview, isLoading, isFetching } = usePreviewPayoutsQuery(query);
  const { data: recorded } = useGetOwnerPayoutsQuery({});
  const [generate, { isLoading: generating }] = useGeneratePayoutsMutation();
  const [payingOut, setPayingOut] = useState(null);

  const categories = useMemo(() => preview?.available_categories ?? [], [preview]);

  // A different period offers different charge types. What is SENT is narrowed
  // to the ones the period actually has, derived at render rather than written
  // back into state: a tick the operator made for July is theirs to keep when
  // they look at July again, and it simply does not count in August.
  const effectiveIncluded = useMemo(() => {
    if (!categories.length) return included;
    const keys = new Set(categories.map((c) => c.key));
    return included.filter((key) => keys.has(key));
  }, [categories, included]);

  const toggle = (key) =>
    setIncluded((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]);

  const rows = toRows(recorded);

  const downloadStatement = async (row) => {
    try {
      await downloadFile(`/payouts/${row.id}/statement.pdf`, {
        filename: `payout-${row.owner_name || row.property_name || row.id}.pdf`,
      });
    } catch {
      toast("Could not fetch that statement.", { type: "error" });
    }
  };

  const run = async () => {
    try {
      const created = await generate({
        ...range, include_categories: effectiveIncluded, commission_basis: basis,
      }).unwrap();
      toast(`Generated ${created.length} ${created.length === 1 ? "payout" : "payouts"}.`,
            { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not generate payouts.", { type: "error" });
    }
  };

  const columns = [
    { key: "owner_name", header: "Owner",
      render: (row) => row.owner_name || row.property_name || "—" },
    { key: "period", header: "Period", render: (row) => row.period || "—" },
    { key: "total_collected", header: "Collected", className: "text-right",
      render: (row) => formatCurrency(row.total_collected ?? row.amount) },
    { key: "commission_amount", header: "Commission", className: "text-right",
      render: (row) => (
        <span>
          {formatCurrency(row.commission_amount)}
          <span className="block text-[11px] text-white/35">
            on {row.commission_basis === "collected" ? "total" : "rent"}
          </span>
        </span>
      ) },
    { key: "net_payable", header: "Net", className: "text-right",
      render: (row) => formatCurrency(row.net_payable ?? row.amount) },
    { key: "status", header: "Status",
      render: (row) => (
        <Badge color={row.status === "paid" ? "third" : "amber"}>
          {row.status === "paid" ? "Paid" : "Pending"}
        </Badge>
      ) },
  ];

  return (
    <div className="space-y-6">
      {/* No PageHeader here — PayoutsLayout owns the title for both tabs. */}
      <p className="text-sm text-white/50">
        What each owner is owed for the period, after commission and any
        withheld tax. Generating a run records the payouts; you still send the
        money yourself and mark them paid.
      </p>

      <div className="glass space-y-3 p-4 sm:space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input type="date" label="From" value={range.period_start}
                 onChange={(e) => setRange((r) => ({ ...r, period_start: e.target.value }))} />
          <Input type="date" label="To" value={range.period_end}
                 onChange={(e) => setRange((r) => ({ ...r, period_end: e.target.value }))} />
        </div>
      </div>

      <CollectedPicker
        categories={categories}
        included={effectiveIncluded}
        onToggle={toggle}
        basis={basis}
        onBasis={setBasis}
      />

      <div className="glass flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <p className="text-xs text-white/45">
          Commission on{" "}
          <span className="text-white/75">
            {basis === "collected" ? "the total collected" : "rent only"}
          </span>
          . Recorded with each payout, so the statement can say which base it used.
        </p>
        <Button type="button" onClick={run} isLoading={generating}
                disabled={!preview?.payouts?.length}>
          <Play size={14} className="mr-1" /> Generate payouts
        </Button>
      </div>

      {/* Preview */}
      {isLoading || isFetching ? (
        <SkeletonForm fields={4} />
      ) : !preview?.payouts?.length ? (
        <EmptyState
          title="Nothing collected in this period"
          description="Choose a different date range above."
        />
      ) : (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-white/70">Preview</h3>
          {preview.payouts.map((row) => (
            <div key={row.key} className="glass space-y-3 p-5 sm:p-6">
              <div>
                <div className="text-base font-medium text-white">{row.owner_name}</div>
                <div className="text-xs text-white/40">{row.property_names.join(", ")}</div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                {[
                  ["Collected", row.total_collected],
                  ["Rent (tax base)", row.rent_collected_base],
                  [row.commission_basis === "collected"
                    ? "Commission (on total)"
                    : "Commission (on rent)", row.commission_amount],
                  [row.tax_withheld ? "Tax withheld" : "Tax (not deducted)", row.tax_amount],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
                    <div className="mt-0.5 text-white/80">{formatCurrency(value)}</div>
                  </div>
                ))}
              </div>

              {row.collected_breakdown?.length > 1 && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-white/10 pt-3 text-xs text-white/45">
                  {row.collected_breakdown.map((part) => (
                    <span key={part.key}>
                      {part.label}{" "}
                      <span className="tabular-nums text-white/70">
                        {formatCurrency(part.amount)}
                      </span>
                    </span>
                  ))}
                </div>
              )}

              <div className="border-t border-white/10 pt-3">
                <div className="text-xs uppercase tracking-wide text-white/40">Net payable</div>
                <div className="text-xl font-light text-secondary">
                  {formatCurrency(row.net_payable)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Recorded payouts */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-white/70">Recorded payouts</h3>
        <ResponsiveTable
          columns={columns}
          rows={rows}
          keyField="id"
          rowActions={(row) => (
            <div className="flex flex-col gap-2 sm:flex-row">
              {/* downloadFile, not window.open. The statement endpoint is
                  jwt_required, and a popup carries no Authorization header —
                  nor does a bare "/api/..." path point at the API, which lives
                  on its own origin. The button opened the SPA's own 404 page
                  and never produced a statement at all. */}
              <Button type="button" variant="ghost"
                      onClick={() => downloadStatement(row)}>
                <FileText size={14} className="mr-1" /> Statement
              </Button>
              {row.status !== "paid" && (
                <Button type="button" variant="ghost" onClick={() => setPayingOut(row)}>
                  <Check size={14} className="mr-1" /> Mark paid
                </Button>
              )}
            </div>
          )}
          emptyState={
            <EmptyState title="No payouts recorded yet"
                        description="Generate them from a period above." />
          }
        />
      </div>

      {payingOut && <MarkPaidModal payout={payingOut} onClose={() => setPayingOut(null)} />}
    </div>
  );
}
