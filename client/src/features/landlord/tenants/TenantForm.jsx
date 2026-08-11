import { useMemo, useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { isRequired, isValidPhone, isValidEmail, isDateOnOrAfter } from "@/utils/validators";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

const EMPTY_FORM = {
  property_id: "",
  unit_id: "",
  first_name: "",
  last_name: "",
  phone: "",
  secondary_phone: "",
  email: "",
  national_id: "",
  kra_pin: "",
  account_number: "",
  deposit_amount: "",
  deposit_paid: "",
  deposit_returned: "",
  rent_payment_penalty: "",
  bank_payer_name: "",
  lease_start_date: "",
  lease_expiry_date: "",
  move_in_date: "",
  move_out_date: "",
  notes: "",
  // Off by default: sending costs the landlord SMS credits, and a message
  // going out unasked is not a pleasant surprise.
  send_welcome_message: false,
};

// Only property/unit, first/last name and phone are required — every other field is
// optional (§4.5).
export default function TenantForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ ...EMPTY_FORM, ...initialValues });
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const unitOptions = useMemo(
    () =>
      units
        .filter((u) => !form.property_id || String(u.property_id) === String(form.property_id))
        .map((u) => ({ value: u.id, label: u.name })),
    [units, form.property_id]
  );

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.unit_id)) nextErrors.unit_id = "Select a unit";
    if (!isRequired(form.first_name)) nextErrors.first_name = "First name is required";
    if (!isRequired(form.last_name)) nextErrors.last_name = "Last name is required";
    if (!isValidPhone(form.phone)) nextErrors.phone = "Enter a valid phone number";
    if (!isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isDateOnOrAfter(form.lease_expiry_date, form.lease_start_date)) {
      nextErrors.lease_expiry_date = "Must be on/after the lease start date";
    }
    if (form.deposit_returned && form.deposit_paid && Number(form.deposit_returned) > Number(form.deposit_paid)) {
      nextErrors.deposit_returned = "Cannot exceed deposit paid";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5" data-tour={ANCHORS.tenants.form}>
      <div className="grid grid-cols-2 gap-4">
        <Select
          label="Property"
          value={form.property_id}
          onChange={update("property_id")}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Select
          label="Unit"
          value={form.unit_id}
          onChange={update("unit_id")}
          options={unitOptions}
          error={errors.unit_id}
          required
          data-tour={ANCHORS.tenants.unitSelect}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="First name" value={form.first_name} onChange={update("first_name")} error={errors.first_name} required />
        <Input label="Last name" value={form.last_name} onChange={update("last_name")} error={errors.last_name} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="Phone"
          value={form.phone}
          onChange={update("phone")}
          error={errors.phone}
          required
          data-tour={ANCHORS.tenants.phoneField}
        />
        <Input label="Secondary phone" value={form.secondary_phone} onChange={update("secondary_phone")} hint="Next of kin / other" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Email" type="email" value={form.email} onChange={update("email")} error={errors.email} />
        <Input label="Account number" value={form.account_number} onChange={update("account_number")} hint="M-Pesa account reference" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="National ID" value={form.national_id} onChange={update("national_id")} />
        <Input label="KRA PIN" value={form.kra_pin} onChange={update("kra_pin")} />
      </div>

      <div className="border-t border-white/10 pt-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Deposit</p>
        <div className="grid grid-cols-3 gap-4">
          <Input label="Deposit amount" type="number" step="0.01" value={form.deposit_amount} onChange={update("deposit_amount")} />
          <Input label="Amount paid" type="number" step="0.01" value={form.deposit_paid} onChange={update("deposit_paid")} />
          <Input
            label="Amount returned"
            type="number"
            step="0.01"
            value={form.deposit_returned}
            onChange={update("deposit_returned")}
            error={errors.deposit_returned}
          />
        </div>
      </div>

      <div className="border-t border-white/10 pt-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Lease</p>
        <div className="grid grid-cols-2 gap-4">
          <DatePicker label="Lease start date" value={form.lease_start_date} onChange={update("lease_start_date")} />
          <DatePicker label="Lease expiry date" value={form.lease_expiry_date} onChange={update("lease_expiry_date")} error={errors.lease_expiry_date} />
          <DatePicker label="Move-in date" value={form.move_in_date} onChange={update("move_in_date")} />
          <DatePicker label="Move-out date" value={form.move_out_date} onChange={update("move_out_date")} />
        </div>
      </div>

      <Input label="Rent payment penalty" type="number" step="0.01" value={form.rent_payment_penalty} onChange={update("rent_payment_penalty")} />
      <Input label="Bank payer name" value={form.bank_payer_name} onChange={update("bank_payer_name")} />
      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />

      {/* Only offered when creating — an existing tenant has already been
          welcomed, and re-sending belongs on the Communications page. */}
      {!initialValues?.id && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <Checkbox
            label="Send a welcome message to this tenant"
            checked={form.send_welcome_message}
            onChange={(e) =>
              setForm((f) => ({ ...f, send_welcome_message: e.target.checked }))
            }
          />
          <p className="mt-1.5 pl-7 text-xs leading-relaxed text-white/45">
            A short, warm SMS with their unit, how to pay and who to call — plus
            an email copy if you've given an address. Uses your SMS credits.
            Edit the wording under Communications → Message templates.
          </p>
        </div>
      )}

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" data-tour={ANCHORS.tenants.saveButton} isLoading={isSubmitting}>
          Save tenant
        </Button>
      </div>
    </form>
  );
}
