import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { INVOICE_TYPES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { formatCurrency } from "@/utils/currencyFormatter";

const EMPTY_LINE = { item: "", description: "", quantity: 1, unit_price: "" };

// Single invoice + line items — the server validates total_amount === Σ(line items),
// but we surface the same total live here too.
export default function InvoiceForm({ initialValues, tenants = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    tenant_id: "",
    invoice_type: "rent",
    issue_date: new Date().toISOString().slice(0, 10),
    due_date: "",
    title: "",
    ...initialValues,
  });
  const [lines, setLines] = useState(initialValues?.line_items?.length ? initialValues.line_items : [{ ...EMPTY_LINE }]);
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const updateLine = (index, key, value) => {
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, [key]: value } : line)));
  };

  const addLine = () => setLines((prev) => [...prev, { ...EMPTY_LINE }]);
  const removeLine = (index) => setLines((prev) => prev.filter((_, i) => i !== index));

  const total = lines.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0);

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.tenant_id)) nextErrors.tenant_id = "Select a tenant";
    if (!isRequired(form.issue_date)) nextErrors.issue_date = "Issue date is required";
    if (!lines.length || lines.some((l) => !isRequired(l.item) || !isRequired(l.unit_price))) {
      nextErrors.lines = "Every line needs an item and unit price";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit({ ...form, line_items: lines, total_amount: total });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <Select
          label="Tenant"
          value={form.tenant_id}
          onChange={update("tenant_id")}
          error={errors.tenant_id}
          options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
          required
        />
        <Select label="Invoice type" value={form.invoice_type} onChange={update("invoice_type")} options={INVOICE_TYPES.map((t) => ({ value: t, label: t }))} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <DatePicker label="Issue date" value={form.issue_date} onChange={update("issue_date")} error={errors.issue_date} required />
        <DatePicker label="Due date" value={form.due_date} onChange={update("due_date")} />
      </div>
      <Input label="Title" value={form.title} onChange={update("title")} hint="Optional — shown on the invoice header" />

      <div className="border-t border-white/10 pt-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-wide text-white/40">Line items</p>
          <Button type="button" variant="subtle" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={addLine}>
            Add line
          </Button>
        </div>
        {errors.lines && <p className="mb-2 text-xs text-secondary-300">{errors.lines}</p>}
        <div className="space-y-3">
          {lines.map((line, index) => (
            <div key={index} className="grid grid-cols-12 gap-2">
              <div className="col-span-4">
                <Input placeholder="Item" value={line.item} onChange={(e) => updateLine(index, "item", e.target.value)} />
              </div>
              <div className="col-span-3">
                <Input placeholder="Qty" type="number" value={line.quantity} onChange={(e) => updateLine(index, "quantity", e.target.value)} />
              </div>
              <div className="col-span-3">
                <Input placeholder="Unit price" type="number" value={line.unit_price} onChange={(e) => updateLine(index, "unit_price", e.target.value)} />
              </div>
              <button
                type="button"
                onClick={() => removeLine(index)}
                className="col-span-2 flex items-center justify-center rounded-lg text-white/40 transition-colors hover:text-secondary"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
        <p className="mt-3 text-right text-sm text-white/70">Total: {formatCurrency(total)}</p>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save invoice
        </Button>
      </div>
    </form>
  );
}
