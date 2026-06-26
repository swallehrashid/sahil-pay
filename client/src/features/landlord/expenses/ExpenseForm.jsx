import { useState } from "react";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { EXPENSE_CATEGORIES, EXPENSE_STATUSES } from "@/utils/constants";
import { isRequired, validateMoneyField } from "@/utils/validators";

export default function ExpenseForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    property_id: "",
    unit_id: "",
    amount: "",
    payment_method: "",
    category: "maintenance",
    expense_date: new Date().toISOString().slice(0, 10),
    status: "confirmed",
    notes: "",
    ...initialValues,
  });
  const [file, setFile] = useState(null);
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const unitOptions = units.filter((u) => !form.property_id || String(u.property_id) === String(form.property_id));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.property_id)) nextErrors.property_id = "Select a property";
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) nextErrors.amount = amountError;
    if (!isRequired(form.expense_date)) nextErrors.expense_date = "Expense date is required";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit({ ...form, file });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Select
          label="Property"
          value={form.property_id}
          onChange={update("property_id")}
          error={errors.property_id}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
          required
        />
        <Select
          label="Unit"
          value={form.unit_id}
          onChange={update("unit_id")}
          placeholder="Whole property"
          options={unitOptions.map((u) => ({ value: u.id, label: u.name }))}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Amount" type="number" step="0.01" value={form.amount} onChange={update("amount")} error={errors.amount} required />
        <Input label="Payment method" value={form.payment_method} onChange={update("payment_method")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Select label="Category" value={form.category} onChange={update("category")} options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))} required />
        <Select label="Status" value={form.status} onChange={update("status")} options={EXPENSE_STATUSES.map((s) => ({ value: s, label: s }))} />
      </div>
      <DatePicker label="Expense date" value={form.expense_date} onChange={update("expense_date")} error={errors.expense_date} required />
      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />
      <FileUpload label="Receipt" accept="image/*,.pdf" value={file} onChange={setFile} />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save expense
        </Button>
      </div>
    </form>
  );
}
