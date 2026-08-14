import { useState } from "react";
import { Check, FileText, Play } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
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

export default function PayoutsPage() {
  const [range, setRange] = useState({ period_start: monthStart(), period_end: today() });
  const { data: preview, isLoading, isFetching } = usePreviewPayoutsQuery(range);
  const { data: recorded } = useGetOwnerPayoutsQuery({});
  const [generate, { isLoading: generating }] = useGeneratePayoutsMutation();
  const [payingOut, setPayingOut] = useState(null);

  const rows = toRows(recorded);

  const run = async () => {
    try {
      const created = await generate(range).unwrap();
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
      render: (row) => formatCurrency(row.commission_amount) },
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
      <PageHeader
        title="Owner payouts"
        subtitle="What each owner is owed, after commission and any withheld tax."
      />

      <div className="glass space-y-3 p-4 sm:space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input type="date" label="From" value={range.period_start}
                 onChange={(e) => setRange((r) => ({ ...r, period_start: e.target.value }))} />
          <Input type="date" label="To" value={range.period_end}
                 onChange={(e) => setRange((r) => ({ ...r, period_end: e.target.value }))} />
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" onClick={run} isLoading={generating}
                  disabled={!preview?.payouts?.length}>
            <Play size={14} className="mr-1" /> Generate payouts
          </Button>
        </div>
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
                  ["Rent (base)", row.rent_collected_base],
                  ["Commission", row.commission_amount],
                  [row.tax_withheld ? "Tax withheld" : "Tax (not deducted)", row.tax_amount],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-xs uppercase tracking-wide text-white/40">{label}</div>
                    <div className="mt-0.5 text-white/80">{formatCurrency(value)}</div>
                  </div>
                ))}
              </div>

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
              <Button type="button" variant="ghost"
                      onClick={() => window.open(`/api/payouts/${row.id}/statement.pdf`, "_blank")}>
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
