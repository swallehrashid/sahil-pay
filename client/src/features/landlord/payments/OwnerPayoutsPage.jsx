import { useState } from "react";
import { Plus, Trash2, Send } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Modal from "@/components/ui/Modal";
import Spinner from "@/components/ui/Spinner";
import EmptyState from "@/components/ui/EmptyState";
import Pagination from "@/components/ui/Pagination";
import SummaryCard from "@/components/ui/SummaryCard";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import {
  useGetOwnerPayoutsQuery,
  useCreateOwnerPayoutMutation,
  useDeleteOwnerPayoutMutation,
} from "../ownerPayoutApiSlice";

/**
 * Money remitted to each property's owner.
 *
 * A property manager collects every tenant's rent into one paybill, then pays
 * each landlord their share. This is the record of those remittances, so a
 * property statement can close the loop: net income − remitted = retained.
 *
 * A payout is NOT an expense — it is the owner's own money changing hands — so
 * it never touches expense totals, tax, or the commission base.
 */

const METHODS = [
  { value: "mpesa", label: "M-Pesa" },
  { value: "bank", label: "Bank transfer" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

const EMPTY = {
  property_id: "",
  amount: "",
  payout_date: new Date().toISOString().slice(0, 10),
  period: "",
  method: "bank",
  reference: "",
  notes: "",
};

export default function OwnerPayoutsPage({ properties = [] }) {
  const [page, setPage] = useState(1);
  const [propertyFilter, setPropertyFilter] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading } = useGetOwnerPayoutsQuery({
    page,
    per_page: 20,
    ...(propertyFilter ? { property_id: propertyFilter } : {}),
  });
  const [createPayout, { isLoading: isSaving }] = useCreateOwnerPayoutMutation();
  const [deletePayout] = useDeleteOwnerPayoutMutation();

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  async function save() {
    if (!form.property_id || !form.amount || !form.payout_date) {
      toast("Property, amount and date are required.", { type: "error" });
      return;
    }
    try {
      await createPayout({
        ...form,
        amount: Number(form.amount),
        // Default the accounting period to the month the money went out.
        period: form.period || form.payout_date.slice(0, 7),
      }).unwrap();
      toast("Payout recorded.", { type: "success" });
      setForm(EMPTY);
      setIsOpen(false);
    } catch (err) {
      toast(err?.data?.error || "Could not record the payout.", { type: "error" });
    }
  }

  async function remove(id) {
    try {
      await deletePayout(id).unwrap();
      toast("Payout deleted.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not delete the payout.", { type: "error" });
    }
  }

  const payouts = data?.payouts ?? [];

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-light tracking-wide text-white">Owner payouts</h1>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-white/50">
            What you've remitted to each property's owner. Recorded here, these
            appear on the property statement as "Remitted to owner" — they are
            not expenses and never affect tax or commission.
          </p>
        </div>
        <Button leftIcon={<Plus className="h-4 w-4" />} onClick={() => setIsOpen(true)}>
          Record payout
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <SummaryCard
          label="Total remitted"
          value={formatCurrency(data?.total_amount ?? 0)}
          icon={<Send className="h-5 w-5" />}
        />
        <div className="sm:col-span-2">
          <Select
            label="Filter by property"
            value={propertyFilter}
            onChange={(e) => {
              setPropertyFilter(e.target.value);
              setPage(1);
            }}
            options={[
              { value: "", label: "All properties" },
              ...properties.map((p) => ({ value: p.id, label: p.name })),
            ]}
          />
        </div>
      </div>

      <div className="glass overflow-hidden">
        {isLoading ? (
          <Spinner className="mx-auto my-10" />
        ) : payouts.length === 0 ? (
          <EmptyState
            title="No payouts recorded yet"
            description="Record what you've paid each owner so their statement shows what was remitted and what you retained."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-white/40">
                <tr>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Property</th>
                  <th className="px-4 py-3">Period</th>
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Reference</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {payouts.map((row) => (
                  <tr key={row.id} className="border-b border-white/5 hover:bg-white/[0.03]">
                    <td className="px-4 py-3 text-white/70">{formatDate(row.payout_date)}</td>
                    <td className="px-4 py-3 text-white">{row.property_name}</td>
                    <td className="px-4 py-3 text-white/60">{row.period ?? "—"}</td>
                    <td className="px-4 py-3 capitalize text-white/60">{row.method ?? "—"}</td>
                    <td className="px-4 py-3 text-white/60">{row.reference ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-medium tabular-nums text-white">
                      {formatCurrency(row.amount)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => remove(row.id)}
                        className="text-white/30 transition-colors hover:text-red-400"
                        aria-label="Delete payout"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {(data?.total ?? 0) > 20 && (
        <Pagination
          page={data.current_page}
          perPage={20}
          total={data.total}
          onPageChange={setPage}
        />
      )}

      <Modal isOpen={isOpen} onClose={() => setIsOpen(false)} title="Record an owner payout">
        <div className="space-y-4">
          <Select
            label="Property"
            value={form.property_id}
            onChange={update("property_id")}
            options={properties.map((p) => ({ value: p.id, label: p.name }))}
            required
          />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="Amount"
              type="number"
              step="0.01"
              value={form.amount}
              onChange={update("amount")}
              required
            />
            <DatePicker label="Date paid" value={form.payout_date} onChange={update("payout_date")} required />
            <Input
              label="Period"
              placeholder="2026-07"
              value={form.period}
              onChange={update("period")}
              hint="Which month this covers — defaults to the payout month"
            />
            <Select label="Method" value={form.method} onChange={update("method")} options={METHODS} />
          </div>
          <Input label="Reference" value={form.reference} onChange={update("reference")} />
          <Textarea label="Notes" value={form.notes} onChange={update("notes")} />

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setIsOpen(false)}>Cancel</Button>
            <Button onClick={save} isLoading={isSaving}>Record payout</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
