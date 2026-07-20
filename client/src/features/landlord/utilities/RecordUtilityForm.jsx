import { useMemo, useState } from "react";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { isRequired } from "@/utils/validators";
import { currentMonth } from "@/utils/dateFormatter";
import { useGetChargeCategoriesQuery } from "../chargeCategoryApiSlice";

// Records a utility against one of the landlord's utility ChargeCategories. Metered
// categories (water/electricity) take previous/current readings; non-metered ones
// (garbage, security, …) take a straight flat amount. Both reading fields optional.
export default function RecordUtilityForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const { data: catData } = useGetChargeCategoriesQuery({ kind: "utility" });
  const utilityTypes = catData?.categories ?? [];

  const [form, setForm] = useState({
    property_id: "",
    unit_id: "",
    category_id: "",
    current_reading: "",
    previous_reading: "",
    amount: "",
    reading_month: currentMonth(),
    ...initialValues,
  });
  const [errors, setErrors] = useState({});
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const unitOptions = units.filter((u) => !form.property_id || String(u.property_id) === String(form.property_id));
  const selectedType = useMemo(
    () => utilityTypes.find((t) => String(t.id) === String(form.category_id)),
    [utilityTypes, form.category_id]
  );
  const isMetered = selectedType?.is_metered ?? false;

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.unit_id)) nextErrors.unit_id = "Select a unit";
    if (!isRequired(form.category_id)) nextErrors.category_id = "Select a utility";
    if (isMetered) {
      if (!isRequired(form.current_reading)) nextErrors.current_reading = "Current reading is required for a metered utility";
      if (form.previous_reading && Number(form.current_reading) < Number(form.previous_reading)) {
        nextErrors.current_reading = "Must be ≥ previous reading";
      }
    } else if (!isRequired(form.amount)) {
      nextErrors.amount = "Enter the charge amount";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    // Only send the fields relevant to the chosen type so the server stores clean rows.
    const payload = {
      property_id: form.property_id,
      unit_id: form.unit_id,
      category_id: form.category_id,
      reading_month: form.reading_month,
    };
    if (isMetered) {
      payload.current_reading = form.current_reading;
      if (form.previous_reading) payload.previous_reading = form.previous_reading;
    } else {
      payload.amount = form.amount;
    }
    onSubmit(payload);
  };

  const typeOptions = utilityTypes.map((t) => ({
    value: t.id,
    label: `${t.name}${t.is_metered ? " (metered)" : ""}`,
  }));

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
      <Select
        label="Utility"
        value={form.category_id}
        onChange={update("category_id")}
        error={errors.category_id}
        options={typeOptions}
        hint="Manage the list under Utilities → Utility categories"
        required
      />

      {isMetered ? (
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
      ) : (
        <Input
          label="Amount (KES)"
          type="number"
          step="0.01"
          value={form.amount}
          onChange={update("amount")}
          error={errors.amount}
          hint="Flat charge — no meter readings"
          required
        />
      )}

      <Input label="Reading month" type="month" value={form.reading_month} onChange={update("reading_month")} required />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save
        </Button>
      </div>
    </form>
  );
}
