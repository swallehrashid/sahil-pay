import { useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { PAYMENT_STATUSES, RECEIPT_CHANNELS } from "@/utils/constants";
import { isRequired, validateMoneyField } from "@/utils/validators";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetTenantOutstandingItemsQuery } from "../chargeCategoryApiSlice";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

// "Jun 2026" from an issue date (handles ISO + RFC date strings the API returns).
function monthLabel(d) {
  if (!d) return "";
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? "" : dt.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

// Manual payment entry — allocates part/all of the amount across the tenant's open
// invoices via payment_allocations; any unallocated remainder becomes a tenant advance.
export default function RecordPaymentForm({ initialValues, tenants = [], invoices = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    tenant_id: "",
    amount: "",
    payment_date: new Date().toISOString().slice(0, 10),
    payment_method: "",
    status: "confirmed",
    mpesa_reference: "",
    notes: "",
    ...initialValues,
  });
  const [allocations, setAllocations] = useState({}); // line_item_id -> amount string
  // #5 — 'auto' follows the landlord's Settings priority; 'manual' lets them split the
  // payment across individual invoice items by hand (one screen, all outstanding items).
  const [allocationMode, setAllocationMode] = useState("auto");
  const [sendReceipt, setSendReceipt] = useState(false);
  const [receiptChannels, setReceiptChannels] = useState(["email"]);
  const [errors, setErrors] = useState({});

  const toggleChannel = (value) =>
    setReceiptChannels((prev) => (prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]));

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  // Line-level outstanding items for the selected tenant (all invoices, one screen).
  const { data: outstanding } = useGetTenantOutstandingItemsQuery(form.tenant_id, {
    skip: !form.tenant_id,
  });
  const outstandingInvoices = outstanding?.invoices ?? [];
  const creditBalance = outstanding?.credit_balance ?? 0;

  const allocatedTotal = Object.values(allocations).reduce((sum, v) => sum + Number(v || 0), 0);

  // "pay this" fills the line with the rest of the still-unallocated payment, capped at
  // the line's own remaining balance.
  const payLine = (line) => {
    setAllocations((prev) => {
      const others = Object.entries(prev)
        .filter(([id]) => String(id) !== String(line.line_item_id))
        .reduce((sum, [, v]) => sum + Number(v || 0), 0);
      const left = Math.max(Number(form.amount || 0) - others, 0);
      const take = Math.min(left, Number(line.remaining || 0));
      return { ...prev, [line.line_item_id]: take || "" };
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.tenant_id)) nextErrors.tenant_id = "Select a tenant";
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) nextErrors.amount = amountError;
    if (allocationMode === "manual" && allocatedTotal > Number(form.amount || 0)) {
      nextErrors.allocations = "Allocated amount cannot exceed the payment amount";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    // Backend (POST /payments) reads `allocation_mode` + line-level
    // `allocations: [{ line_item_id, amount }]`.
    const allocationsPayload =
      allocationMode === "manual"
        ? Object.entries(allocations)
            .filter(([, amount]) => Number(amount) > 0)
            .map(([line_item_id, amount]) => ({ line_item_id: Number(line_item_id), amount: Number(amount) }))
        : [];

    onSubmit({
      ...form,
      allocation_mode: allocationMode,
      allocations: allocationsPayload,
      send_receipt: sendReceipt,
      receipt_channels: sendReceipt ? receiptChannels : [],
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Select
        label="Tenant"
        value={form.tenant_id}
        onChange={update("tenant_id")}
        error={errors.tenant_id}
        options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
        required
        data-tour={ANCHORS.payments.tenantSelect}
      />
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Amount"
          type="number"
          step="0.01"
          value={form.amount}
          onChange={update("amount")}
          error={errors.amount}
          required
          data-tour={ANCHORS.payments.amountField}
        />
        <DatePicker label="Payment date" value={form.payment_date} onChange={update("payment_date")} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Payment method" value={form.payment_method} onChange={update("payment_method")} placeholder="Cash, bank transfer, M-Pesa…" />
        <Select label="Status" value={form.status} onChange={update("status")} options={PAYMENT_STATUSES.map((s) => ({ value: s, label: s }))} />
      </div>
      <Input label="M-Pesa reference" value={form.mpesa_reference} onChange={update("mpesa_reference")} hint="Optional" />

      {form.tenant_id && (
        <div className="border-t border-white/10 pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-white/40">Allocation</p>

          {/* #5 — auto vs manual allocation */}
          <div className="mb-3 inline-flex rounded-xl bg-white/5 p-1">
            {[
              { value: "auto", label: "Automatic" },
              { value: "manual", label: "Manual" },
            ].map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setAllocationMode(opt.value)}
                className={
                  "rounded-lg px-4 py-1.5 text-sm transition-colors " +
                  (allocationMode === opt.value ? "bg-secondary text-white" : "text-white/60 hover:text-white")
                }
              >
                {opt.label}
              </button>
            ))}
          </div>

          {creditBalance > 0 && (
            <p className="mb-2 text-xs text-emerald-300">
              Tenant credit available: {formatCurrency(creditBalance)} (applied to future bills).
            </p>
          )}

          {allocationMode === "auto" ? (
            <p className="text-sm text-white/40">
              The payment will clear this tenant's charges automatically, following your
              Settings → Payments allocation priority. Any remainder becomes tenant credit.
            </p>
          ) : (
            <>
              {errors.allocations && <p className="mb-2 text-xs text-secondary-300">{errors.allocations}</p>}
              {outstandingInvoices.length === 0 ? (
                <p className="text-sm text-white/40">No outstanding items for this tenant — the full amount becomes tenant credit.</p>
              ) : (
                <div className="space-y-3">
                  {outstandingInvoices.map((inv) => (
                    <div key={inv.invoice_id} className="rounded-lg bg-white/5 p-3">
                      <div className="mb-2 text-xs text-white/40">
                        {inv.invoice_number}
                        {monthLabel(inv.issue_date) ? ` · ${monthLabel(inv.issue_date)}` : ""}
                      </div>
                      <div className="space-y-1.5">
                        {inv.lines.map((line) => (
                          <div key={line.line_item_id} className="flex items-center justify-between gap-3">
                            <div className="min-w-0 text-sm text-white/80">
                              <span className="truncate">{line.label}</span>
                              <span className="ml-2 text-xs text-white/40">{formatCurrency(line.remaining)} due</span>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <button
                                type="button"
                                onClick={() => payLine(line)}
                                className="text-[11px] text-white/40 underline-offset-2 hover:text-secondary hover:underline"
                              >
                                pay this
                              </button>
                              <input
                                type="number"
                                step="0.01"
                                placeholder="0.00"
                                value={allocations[line.line_item_id] ?? ""}
                                onChange={(e) => setAllocations((prev) => ({ ...prev, [line.line_item_id]: e.target.value }))}
                                className="glass-input w-28 text-right"
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  <p className="text-right text-xs text-white/40">
                    Allocated: {formatCurrency(allocatedTotal)} of {formatCurrency(form.amount || 0)}
                    {allocatedTotal < Number(form.amount || 0) && (
                      <> · {formatCurrency(Number(form.amount || 0) - allocatedTotal)} → credit</>
                    )}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />

      <div className="border-t border-white/10 pt-4">
        <Checkbox
          name="send_receipt"
          label="Send a receipt to the tenant"
          checked={sendReceipt}
          onChange={(e) => setSendReceipt(e.target.checked)}
        />
        {sendReceipt && (
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 pl-1">
            {RECEIPT_CHANNELS.map((ch) => (
              <Checkbox
                key={ch.value}
                name={`receipt_${ch.value}`}
                label={ch.label}
                disabled={!ch.enabled}
                className={!ch.enabled ? "opacity-40" : ""}
                checked={ch.enabled && receiptChannels.includes(ch.value)}
                onChange={() => ch.enabled && toggleChannel(ch.value)}
              />
            ))}
          </div>
        )}
        {sendReceipt && receiptChannels.length === 0 && (
          <p className="mt-2 text-xs text-secondary-300">Pick at least one channel.</p>
        )}
      </div>

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" data-tour={ANCHORS.payments.saveButton} isLoading={isSubmitting}>
          Record payment
        </Button>
      </div>
    </form>
  );
}
