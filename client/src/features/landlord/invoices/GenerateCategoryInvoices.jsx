import { useMemo, useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGenerateCustomInvoicesMutation } from "./invoiceApiSlice";
import { validateMoneyField } from "@/utils/validators";

// D3 — one generator modal, parameterised by whichever invoice-kind ChargeCategory the
// landlord clicked in the Generate dropdown. Filters tenants by property/group/all,
// defaults the amount from the category's default_rate (if any), and bulk-creates one
// invoice per selected tenant, tagging each line with (category_id, subcategory) so it
// participates in allocation priority exactly like every other categorised charge.
export default function GenerateCategoryInvoices({ isOpen, onClose, category, tenants = [], properties = [] }) {
  const [generate, { isLoading }] = useGenerateCustomInvoicesMutation();
  const [propertyId, setPropertyId] = useState("");
  const [tenantIds, setTenantIds] = useState([]);
  const [amount, setAmount] = useState(category?.default_rate ?? "");
  const [subcategory, setSubcategory] = useState("current");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().slice(0, 10));
  const [dueDate, setDueDate] = useState("");
  const [error, setError] = useState("");

  const scopedTenants = useMemo(
    () => tenants.filter((t) => !propertyId || String(t.property_id) === String(propertyId)),
    [tenants, propertyId]
  );

  const toggleTenant = (id) =>
    setTenantIds((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  const selectAllScoped = () => setTenantIds(scopedTenants.map((t) => t.id));
  const clearTenants = () => setTenantIds([]);

  if (!category) return null;

  const subLabel = { deposit: "Deposit", balance: "Balance", current: "This month" };
  const lineName = subcategory === "current" ? category.name : `${category.name} ${subLabel[subcategory]}`;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!tenantIds.length) {
      setError("Select at least one tenant");
      return;
    }
    const amountError = validateMoneyField(amount, { allowZero: false });
    if (amountError) {
      setError(amountError);
      return;
    }
    setError("");
    try {
      const result = await generate({
        tenant_ids: tenantIds,
        issue_date: issueDate,
        due_date: dueDate || undefined,
        title: lineName,
        line_items: [{
          item: lineName,
          unit_price: amount,
          quantity: 1,
          category_id: category.id,
          subcategory,
        }],
      }).unwrap();
      toast(`${result?.created ?? "Invoices"} for ${category.name} generated.`, { type: "success" });
      onClose();
    } catch {
      toast(`Could not generate ${category.name} invoices.`, { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Generate ${category.name} invoices`} size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Select
            label="Property"
            placeholder="All properties"
            value={propertyId}
            onChange={(e) => { setPropertyId(e.target.value); setTenantIds([]); }}
            options={properties.map((p) => ({ value: p.id, label: p.name }))}
          />
          <Select
            label="Charge"
            value={subcategory}
            onChange={(e) => setSubcategory(e.target.value)}
            options={[
              { value: "current", label: `${category.name} — This month` },
              { value: "balance", label: `${category.name} — Balance` },
              { value: "deposit", label: `${category.name} — Deposit` },
            ]}
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-sm font-medium text-white/70">Tenants</p>
            <div className="flex gap-2">
              <button type="button" onClick={selectAllScoped} className="text-xs text-secondary hover:underline">Select all</button>
              <button type="button" onClick={clearTenants} className="text-xs text-white/40 hover:underline">Clear</button>
            </div>
          </div>
          <div className="glass max-h-40 space-y-1 overflow-y-auto p-3">
            {scopedTenants.map((tenant) => (
              <label key={tenant.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-white/70 hover:bg-white/5">
                <input type="checkbox" checked={tenantIds.includes(tenant.id)} onChange={() => toggleTenant(tenant.id)} />
                {tenant.first_name} {tenant.last_name}
              </label>
            ))}
            {!scopedTenants.length && <p className="px-2 py-1.5 text-sm text-white/40">No tenants in this scope.</p>}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Input label="Amount" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          <DatePicker label="Due date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        </div>
        <DatePicker label="Issue date" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} required />

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
