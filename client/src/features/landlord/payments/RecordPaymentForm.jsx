import { useMemo, useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { PAYMENT_STATUSES } from "@/utils/constants";
import { isRequired, validateMoneyField } from "@/utils/validators";
import { formatCurrency } from "@/utils/currencyFormatter";

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
  const [allocations, setAllocations] = useState({});
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const tenantInvoices = useMemo(
    () => invoices.filter((inv) => String(inv.tenant_id) === String(form.tenant_id) && inv.status !== "paid" && inv.status !== "void"),
    [invoices, form.tenant_id]
  );

  const allocatedTotal = Object.values(allocations).reduce((sum, v) => sum + Number(v || 0), 0);

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.tenant_id)) nextErrors.tenant_id = "Select a tenant";
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) nextErrors.amount = amountError;
    if (allocatedTotal > Number(form.amount || 0)) nextErrors.allocations = "Allocated amount cannot exceed the payment amount";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    const payment_allocations = Object.entries(allocations)
      .filter(([, amount]) => Number(amount) > 0)
      .map(([invoice_id, amount_allocated]) => ({ invoice_id, amount_allocated: Number(amount_allocated) }));

    onSubmit({ ...form, payment_allocations });
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
      />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Amount" type="number" step="0.01" value={form.amount} onChange={update("amount")} error={errors.amount} required />
        <DatePicker label="Payment date" value={form.payment_date} onChange={update("payment_date")} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Payment method" value={form.payment_method} onChange={update("payment_method")} placeholder="Cash, bank transfer, M-Pesa…" />
        <Select label="Status" value={form.status} onChange={update("status")} options={PAYMENT_STATUSES.map((s) => ({ value: s, label: s }))} />
      </div>
      <Input label="M-Pesa reference" value={form.mpesa_reference} onChange={update("mpesa_reference")} hint="Optional" />

      {form.tenant_id && (
        <div className="border-t border-white/10 pt-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-white/40">Allocate to invoices</p>
          {errors.allocations && <p className="mb-2 text-xs text-secondary-300">{errors.allocations}</p>}
          {tenantInvoices.length === 0 ? (
            <p className="text-sm text-white/40">No open invoices for this tenant — the full amount becomes an advance.</p>
          ) : (
            <div className="space-y-2">
              {tenantInvoices.map((inv) => (
                <div key={inv.id} className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2">
                  <span className="text-sm text-white/70">
                    {inv.invoice_number} · {formatCurrency(inv.balance)} due
                  </span>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    value={allocations[inv.id] ?? ""}
                    onChange={(e) => setAllocations((prev) => ({ ...prev, [inv.id]: e.target.value }))}
                    className="glass-input w-28 text-right"
                  />
                </div>
              ))}
              <p className="text-right text-xs text-white/40">
                Allocated: {formatCurrency(allocatedTotal)} of {formatCurrency(form.amount || 0)}
              </p>
            </div>
          )}
        </div>
      )}

      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Record payment
        </Button>
      </div>
    </form>
  );
}
