import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { INVOICE_TYPES, INVOICE_LINE_ITEMS } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { formatCurrency } from "@/utils/currencyFormatter";

// A line is now { item (dropdown), custom_item (only when item==="other"), amount, description }.
// We no longer expose quantity/unit_price in the UI — each line is a single named charge
// with an amount. On submit we map to the server's line_item shape (quantity 1, unit_price = amount).
const EMPTY_LINE = { item: "rent", custom_item: "", amount: "", description: "" };

export default function InvoiceForm({ initialValues, tenants = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    tenant_id: "",
    invoice_type: "rent",
    issue_date: new Date().toISOString().slice(0, 10),
    due_date: "",
    title: "",
    combine: true, // default: roll charges into this tenant's open invoice for the month
    ...initialValues,
  });
  const [lines, setLines] = useState(
    initialValues?.line_items?.length
      ? initialValues.line_items.map((l) => ({
          item: INVOICE_LINE_ITEMS.includes(l.item) ? l.item : "other",
          custom_item: INVOICE_LINE_ITEMS.includes(l.item) ? "" : l.item,
          amount: l.amount ?? l.unit_price ?? "",
          description: l.description ?? "",
        }))
      : [{ ...EMPTY_LINE }]
  );
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const updateLine = (index, key, value) =>
    setLines((prev) => prev.map((line, i) => (i === index ? { ...line, [key]: value } : line)));
  const addLine = () => setLines((prev) => [...prev, { ...EMPTY_LINE }]);
  const removeLine = (index) => setLines((prev) => prev.filter((_, i) => i !== index));

  const total = lines.reduce((sum, line) => sum + Number(line.amount || 0), 0);

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.tenant_id)) nextErrors.tenant_id = "Select a tenant";
    if (!isRequired(form.issue_date)) nextErrors.issue_date = "Issue date is required";
    if (
      !lines.length ||
      lines.some((l) => (l.item === "other" && !isRequired(l.custom_item)) || !(Number(l.amount) > 0))
    ) {
      nextErrors.lines = "Every line needs an item and an amount greater than zero";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    const line_items = lines.map((l) => {
      const name = l.item === "other" ? l.custom_item.trim() : l.item;
      const amount = Number(l.amount);
      return { item: name, description: l.description, quantity: 1, unit_price: amount, amount };
    });
    onSubmit({ ...form, line_items, total_amount: total });
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
          <p className="text-xs font-medium uppercase tracking-wide text-white/40">Charges</p>
          <Button type="button" variant="subtle" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={addLine}>
            Add charge
          </Button>
        </div>
        {errors.lines && <p className="mb-2 text-xs text-secondary-300">{errors.lines}</p>}
        <div className="space-y-3">
          {lines.map((line, index) => (
            <div key={index} className="space-y-2 rounded-lg bg-white/5 p-3">
              <div className="grid grid-cols-12 items-start gap-2">
                <div className="col-span-5">
                  <Select
                    value={line.item}
                    onChange={(e) => updateLine(index, "item", e.target.value)}
                    options={INVOICE_LINE_ITEMS.map((i) => ({ value: i, label: i.charAt(0).toUpperCase() + i.slice(1) }))}
                  />
                </div>
                <div className="col-span-5">
                  <Input placeholder="Amount" type="number" step="0.01" value={line.amount} onChange={(e) => updateLine(index, "amount", e.target.value)} />
                </div>
                <button
                  type="button"
                  onClick={() => removeLine(index)}
                  disabled={lines.length === 1}
                  className="col-span-2 flex h-10 items-center justify-center rounded-lg text-white/40 transition-colors hover:text-secondary disabled:opacity-30"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              {line.item === "other" && (
                <Input placeholder="Item name" value={line.custom_item} onChange={(e) => updateLine(index, "custom_item", e.target.value)} />
              )}
              <Input placeholder="Description (optional)" value={line.description} onChange={(e) => updateLine(index, "description", e.target.value)} />
            </div>
          ))}
        </div>
        <p className="mt-3 text-right text-sm text-white/70">Total: {formatCurrency(total)}</p>
      </div>

      <Checkbox
        name="combine"
        label="Add to this tenant's existing invoice for this month (if one is open)"
        checked={!!form.combine}
        onChange={(e) => setForm((f) => ({ ...f, combine: e.target.checked }))}
      />

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
