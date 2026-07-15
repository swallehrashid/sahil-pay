import { useState } from "react";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { isRequired, validateMoneyField } from "@/utils/validators";
import { DEFAULT_TAX_RATE } from "@/utils/constants";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

const EMPTY_FORM = {
  name: "",
  number_of_units: "",
  city: "",
  street_name: "",
  water_rate: "",
  electricity_rate: "",
  mpesa_details: "",
  rent_payment_penalty: "",
  tax_rate: String(DEFAULT_TAX_RATE),
  management_fee: "",
  owner_phone: "",
  notes: "",
};

// Only name, number_of_units and city are required — everything else is optional (§4.6).
export default function PropertyForm({ initialValues, onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ ...EMPTY_FORM, ...initialValues });
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.name)) nextErrors.name = "Property name is required";
    if (!isRequired(form.number_of_units)) nextErrors.number_of_units = "Number of units is required";
    if (!isRequired(form.city)) nextErrors.city = "City/location is required";
    if (form.water_rate) {
      const rateError = validateMoneyField(form.water_rate, { required: false });
      if (rateError) nextErrors.water_rate = rateError;
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" data-tour={ANCHORS.properties.form}>
      <Input label="Property name" value={form.name} onChange={update("name")} error={errors.name} required />
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Number of units"
          type="number"
          min="0"
          value={form.number_of_units}
          onChange={update("number_of_units")}
          error={errors.number_of_units}
          required
        />
        <Input label="City / location" value={form.city} onChange={update("city")} error={errors.city} required />
      </div>
      <Input label="Street name" value={form.street_name} onChange={update("street_name")} />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Water rate" type="number" step="0.01" value={form.water_rate} onChange={update("water_rate")} error={errors.water_rate} hint="Optional" />
        <Input label="Electricity rate" type="number" step="0.01" value={form.electricity_rate} onChange={update("electricity_rate")} hint="Optional" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="M-Pesa details" value={form.mpesa_details} onChange={update("mpesa_details")} hint="Property-specific paybill/till" />
        <Input label="Rent payment penalty" type="number" step="0.01" value={form.rent_payment_penalty} onChange={update("rent_payment_penalty")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Tax rate (%)" type="number" step="0.01" value={form.tax_rate} onChange={update("tax_rate")} />
        <Input label="Management fee" type="number" step="0.01" value={form.management_fee} onChange={update("management_fee")} hint="Mainly PM accounts" />
      </div>
      <Input label="Owner phone" value={form.owner_phone} onChange={update("owner_phone")} />
      <Textarea label="Notes" value={form.notes} onChange={update("notes")} hint="Instructions" />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" data-tour={ANCHORS.properties.saveButton} isLoading={isSubmitting}>
          Save property
        </Button>
      </div>
    </form>
  );
}
