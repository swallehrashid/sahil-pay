import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGenerateCustomInvoicesMutation } from "./invoiceApiSlice";
import { validateMoneyField } from "@/utils/validators";

// Applies one custom charge (item + amount) across any number of selected tenants at once.
export default function GenerateCustomInvoices({ isOpen, onClose, tenants = [] }) {
  const [generate, { isLoading }] = useGenerateCustomInvoicesMutation();
  const [form, setForm] = useState({ tenant_ids: [], item: "", amount: "", due_date: "", description: "" });
  const [error, setError] = useState("");

  const toggleTenant = (id) => {
    setForm((f) => ({
      ...f,
      tenant_ids: f.tenant_ids.includes(id) ? f.tenant_ids.filter((t) => t !== id) : [...f.tenant_ids, id],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.tenant_ids.length) {
      setError("Select at least one tenant");
      return;
    }
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) {
      setError(amountError);
      return;
    }
    setError("");
    try {
      const result = await generate({
        tenant_ids: form.tenant_ids,
        issue_date: new Date().toISOString().slice(0, 10),
        due_date: form.due_date || undefined,
        title: form.item,
        line_items: [{ item: form.item, description: form.description || undefined, unit_price: form.amount, quantity: 1 }],
      }).unwrap();
      toast(`${result?.created ?? "Custom"} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not generate custom invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Generate custom invoices" size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <p className="mb-1.5 text-sm font-medium text-white/70">Tenants</p>
          <div className="glass max-h-40 space-y-1 overflow-y-auto p-3">
            {tenants.map((tenant) => (
              <label key={tenant.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-white/70 hover:bg-white/5">
                <input type="checkbox" checked={form.tenant_ids.includes(tenant.id)} onChange={() => toggleTenant(tenant.id)} />
                {tenant.first_name} {tenant.last_name}
              </label>
            ))}
          </div>
        </div>
        <Input label="Item" value={form.item} onChange={(e) => setForm((f) => ({ ...f, item: e.target.value }))} required />
        <div className="grid grid-cols-2 gap-4">
          <Input label="Amount" type="number" step="0.01" value={form.amount} onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))} required />
          <DatePicker label="Due date" value={form.due_date} onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))} />
        </div>
        <Textarea label="Description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
        {error && <p className="text-xs text-secondary-300">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Generate
          </Button>
        </div>
      </form>
    </Modal>
  );
}
