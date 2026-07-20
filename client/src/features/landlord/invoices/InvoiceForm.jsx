import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { INVOICE_STATUSES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetChargeCategoriesQuery } from "../chargeCategoryApiSlice";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

// Charge-category restructure (§5.2): every line targets a (category, subcategory)
// pair — "Rent — Deposit", "Rent — Balance", "Rent — This month", "Water — Deposit"…
// The landlord builds the invoice by picking one or more of these from a multi-select;
// each pick becomes a chip AND a line below (fixed label, editable amount +
// description) — removing a chip removes its line. The invoice's name/title is the
// selected items joined with ", " (e.g. "Rent, Electricity, Water").
const SUB_LABEL = { deposit: "Deposit", balance: "Balance", current: "This month" };
const CUSTOM_VALUE = "custom";

export default function InvoiceForm({ initialValues, tenants = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    tenant_id: "",
    issue_date: new Date().toISOString().slice(0, 10),
    due_date: "",
    status: "open",
    combine: false,
    ...initialValues,
  });

  const { data: catData } = useGetChargeCategoriesQuery({ kind: "invoice", include_inactive: 0 });
  const categories = catData?.categories ?? [];

  const chargeOptions = useMemo(() => {
    const opts = [];
    categories.forEach((c) => {
      ["deposit", "balance", "current"].forEach((sub) => {
        opts.push({
          value: `${c.id}:${sub}`,
          label: `${c.name} — ${SUB_LABEL[sub]}`,
          name: sub === "current" ? c.name : `${c.name} ${SUB_LABEL[sub]}`,
        });
      });
    });
    return opts;
  }, [categories]);

  // Each selection is { key: "<catId>:<sub>" | "custom-<n>", name, target, custom }.
  const [selections, setSelections] = useState(() => {
    if (initialValues?.line_items?.length) {
      return initialValues.line_items.map((l, i) =>
        l.category_id && l.subcategory
          ? { key: `${l.category_id}:${l.subcategory}`, target: `${l.category_id}:${l.subcategory}`, name: null, custom: false }
          : { key: `custom-${i}`, target: CUSTOM_VALUE, name: l.item, custom: true }
      );
    }
    return [];
  });
  const [lines, setLines] = useState(() => {
    if (initialValues?.line_items?.length) {
      const map = {};
      initialValues.line_items.forEach((l, i) => {
        const key = l.category_id && l.subcategory ? `${l.category_id}:${l.subcategory}` : `custom-${i}`;
        map[key] = { amount: l.amount ?? l.unit_price ?? "", description: l.description ?? "" };
      });
      return map;
    }
    return {};
  });
  const [pickerValue, setPickerValue] = useState("");
  const [customDraft, setCustomDraft] = useState("");
  const [addingCustom, setAddingCustom] = useState(false);
  const [errors, setErrors] = useState({});
  const isEditing = Boolean(initialValues?.id);

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const selectedTargets = new Set(selections.filter((s) => !s.custom).map((s) => s.target));
  const pickerOptions = chargeOptions.filter((o) => !selectedTargets.has(o.value));

  const addSelection = (target) => {
    if (!target) return;
    const opt = chargeOptions.find((o) => o.value === target);
    if (!opt) return;
    setSelections((prev) => [...prev, { key: target, target, name: null, custom: false }]);
    setLines((prev) => ({ ...prev, [target]: { amount: "", description: "" } }));
    setPickerValue("");
  };

  const addCustom = () => {
    const name = customDraft.trim();
    if (!name) return;
    const key = `custom-${Date.now()}`;
    setSelections((prev) => [...prev, { key, target: CUSTOM_VALUE, name, custom: true }]);
    setLines((prev) => ({ ...prev, [key]: { amount: "", description: "" } }));
    setCustomDraft("");
    setAddingCustom(false);
  };

  const removeSelection = (key) => {
    setSelections((prev) => prev.filter((s) => s.key !== key));
    setLines((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const updateLine = (key, field, value) =>
    setLines((prev) => ({ ...prev, [key]: { ...prev[key], [field]: value } }));

  const labelFor = (sel) => {
    if (sel.custom) return sel.name;
    const opt = chargeOptions.find((o) => o.value === sel.target);
    return opt?.name || opt?.label || sel.target;
  };

  const total = selections.reduce((sum, sel) => sum + Number(lines[sel.key]?.amount || 0), 0);
  const invoiceName = selections.map(labelFor).join(", ");

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.tenant_id)) nextErrors.tenant_id = "Select a tenant";
    if (!isRequired(form.issue_date)) nextErrors.issue_date = "Issue date is required";
    const badLine = selections.some((sel) => !(Number(lines[sel.key]?.amount) > 0));
    if (!selections.length || badLine) {
      nextErrors.lines = "Add at least one charge, each with an amount greater than zero";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    const line_items = selections.map((sel) => {
      const amount = Number(lines[sel.key]?.amount);
      const description = lines[sel.key]?.description;
      if (sel.custom) {
        return { item: sel.name, description, quantity: 1, unit_price: amount, amount };
      }
      const [cid, sub] = sel.target.split(":");
      return {
        item: labelFor(sel),
        description,
        quantity: 1,
        unit_price: amount,
        amount,
        category_id: Number(cid),
        subcategory: sub,
      };
    });
    onSubmit({ ...form, invoice_type: "custom", title: invoiceName, line_items, total_amount: total });
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
          data-tour={ANCHORS.invoices.tenantSelect}
        />
        <DatePicker label="Issue date" value={form.issue_date} onChange={update("issue_date")} error={errors.issue_date} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <DatePicker label="Due date" value={form.due_date} onChange={update("due_date")} />
        {isEditing && (
          <Select
            label="Status"
            value={form.status || "open"}
            onChange={update("status")}
            options={INVOICE_STATUSES.map((s) => ({ value: s, label: s === "paid" ? "Confirmed" : s.charAt(0).toUpperCase() + s.slice(1) }))}
            hint="Auto-set to Confirmed when fully paid — override only if needed."
          />
        )}
      </div>

      <div className="border-t border-white/10 pt-4" data-tour={ANCHORS.invoices.lineItemsArea}>
        <p className="mb-1.5 block text-sm font-medium text-white/70">Invoice items</p>
        <p className="mb-2 text-xs text-white/40">
          Pick one or more charges from your categories — each becomes a line below. The invoice name is built from what you pick.
        </p>

        <div className="flex flex-wrap gap-2">
          {selections.map((sel) => (
            <span key={sel.key} className="inline-flex items-center gap-1.5 rounded-full bg-secondary/15 px-3 py-1 text-xs text-secondary-100">
              {labelFor(sel)}
              <button type="button" onClick={() => removeSelection(sel.key)} className="text-secondary-100/70 hover:text-white">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>

        <div className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <Select
              value={pickerValue}
              onChange={(e) => addSelection(e.target.value)}
              options={pickerOptions}
              placeholder="Add a charge from your categories…"
            />
          </div>
          {!addingCustom ? (
            <Button type="button" variant="subtle" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setAddingCustom(true)}>
              Other (custom)
            </Button>
          ) : (
            <>
              <Input placeholder="Custom item name" value={customDraft} onChange={(e) => setCustomDraft(e.target.value)} />
              <Button type="button" variant="subtle" size="sm" onClick={addCustom}>
                Add
              </Button>
            </>
          )}
        </div>

        {errors.lines && <p className="mt-2 text-xs text-secondary-300">{errors.lines}</p>}

        <div className="mt-4 space-y-3">
          {selections.map((sel) => (
            <div key={sel.key} className="space-y-2 rounded-lg bg-white/5 p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-white/80">{labelFor(sel)}</p>
                <Input
                  placeholder="Amount"
                  type="number"
                  step="0.01"
                  value={lines[sel.key]?.amount ?? ""}
                  onChange={(e) => updateLine(sel.key, "amount", e.target.value)}
                  className="w-32"
                />
              </div>
              <Input
                placeholder="Description (optional)"
                value={lines[sel.key]?.description ?? ""}
                onChange={(e) => updateLine(sel.key, "description", e.target.value)}
              />
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
        <Button type="submit" data-tour={ANCHORS.invoices.saveButton} isLoading={isSubmitting}>
          Save invoice
        </Button>
      </div>
    </form>
  );
}
