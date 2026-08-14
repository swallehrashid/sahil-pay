import { useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import PayCodeField from "./PayCodeField";
import Button from "@/components/ui/Button";
import { isRequired, validateMoneyField } from "@/utils/validators";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

export default function UnitForm({ initialValues, properties = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    property_id: "",
    name: "",
    rent_amount: "",
    tax_rate: "",
    notes: "",
    ...initialValues,
  });
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.property_id)) nextErrors.property_id = "Select a property";
    if (!isRequired(form.name)) nextErrors.name = "Unit name/ID is required";
    const rentError = validateMoneyField(form.rent_amount, { allowZero: false });
    if (rentError) nextErrors.rent_amount = rentError;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" data-tour={ANCHORS.units.form}>
      <Select
        label="Property"
        value={form.property_id}
        onChange={update("property_id")}
        error={errors.property_id}
        options={properties.map((p) => ({ value: p.id, label: p.name }))}
        required
        data-tour={ANCHORS.units.propertySelect}
      />
      <Input label="Unit name / ID" value={form.name} onChange={update("name")} error={errors.name} required />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Rent amount" type="number" step="0.01" value={form.rent_amount} onChange={update("rent_amount")} error={errors.rent_amount} required />
        <Input label="Tax rate (%)" type="number" step="0.01" value={form.tax_rate} onChange={update("tax_rate")} hint="Inherits property if blank" />
      </div>
      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />

      {/* Saved on its own button — changing a code retires the old one rather
          than deleting it, and the owner needs telling that. */}
      <PayCodeField unit={initialValues} />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" data-tour={ANCHORS.units.saveButton} isLoading={isSubmitting}>
          Save unit
        </Button>
      </div>
    </form>
  );
}
