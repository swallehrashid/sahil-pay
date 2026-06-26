import { useState } from "react";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { UTILITY_ITEMS } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { currentMonth } from "@/utils/dateFormatter";

// Validates current >= previous and computes consumption server-side; we mirror the
// same check here so a bad reading never round-trips needlessly.
export default function RecordUtilityForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    property_id: "",
    unit_id: "",
    utility_item: "water",
    current_reading: "",
    previous_reading: "",
    reading_month: currentMonth(),
    ...initialValues,
  });
  const [errors, setErrors] = useState({});
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const unitOptions = units.filter((u) => !form.property_id || String(u.property_id) === String(form.property_id));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.unit_id)) nextErrors.unit_id = "Select a unit";
    if (!isRequired(form.current_reading)) nextErrors.current_reading = "Current reading is required";
    if (form.previous_reading && Number(form.current_reading) < Number(form.previous_reading)) {
      nextErrors.current_reading = "Must be ≥ previous reading";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Select label="Property" value={form.property_id} onChange={update("property_id")} options={properties.map((p) => ({ value: p.id, label: p.name }))} required />
        <Select
          label="Unit"
          value={form.unit_id}
          onChange={update("unit_id")}
          error={errors.unit_id}
          options={unitOptions.map((u) => ({ value: u.id, label: u.name }))}
          required
        />
      </div>
      <Select label="Utility item" value={form.utility_item} onChange={update("utility_item")} options={UTILITY_ITEMS.map((u) => ({ value: u, label: u }))} required />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Previous reading" type="number" step="0.01" value={form.previous_reading} onChange={update("previous_reading")} hint="Optional" />
        <Input
          label="Current reading"
          type="number"
          step="0.01"
          value={form.current_reading}
          onChange={update("current_reading")}
          error={errors.current_reading}
          required
        />
      </div>
      <Input label="Reading month" type="month" value={form.reading_month} onChange={update("reading_month")} required />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save reading
        </Button>
      </div>
    </form>
  );
}
