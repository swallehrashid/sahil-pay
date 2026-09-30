import { useMemo, useState } from "react";
import MoveInBillEditor from "./MoveInBillEditor";
import { EMPTY_MOVE_IN } from "./moveInBill";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { isRequired, isValidPhone, isValidEmail, isDateOnOrAfter, PHONE_ERROR, PHONE_HINT, toKenyanPhone } from "@/utils/validators";
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
  next_of_kin_name: "",
  next_of_kin_relationship: "",
  next_of_kin_phone: "",
  // Off by default: sending costs the landlord SMS credits, and a message
  // going out unasked is not a pleasant surprise.
  send_welcome_message: false,
};

// Only property/unit, first/last name and phone are required — every other field is
// optional (§4.5).
export default function TenantForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState(() => {
    const merged = { ...EMPTY_FORM, ...initialValues };
    // Nulls from the API would make these controlled inputs uncontrolled.
    for (const k of ["next_of_kin_name", "next_of_kin_relationship", "next_of_kin_phone"]) merged[k] = merged[k] ?? "";
    return merged;
  });
  const [errors, setErrors] = useState({});
  const isNew = !initialValues?.id;

  // The move-in bill (new tenants only) — an invoice raised with the tenant.
  // See MoveInBillEditor and server/services/move_in_service.py.
  const [moveIn, setMoveIn] = useState(EMPTY_MOVE_IN);

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
    if (!isValidPhone(form.phone)) nextErrors.phone = PHONE_ERROR;
    if (form.secondary_phone && !isValidPhone(form.secondary_phone)) nextErrors.secondary_phone = PHONE_ERROR;
    if (!isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isDateOnOrAfter(form.lease_expiry_date, form.lease_start_date)) {
      nextErrors.lease_expiry_date = "Must be on/after the lease start date";
    }
    if (form.deposit_returned && form.deposit_paid && Number(form.deposit_returned) > Number(form.deposit_paid)) {
      nextErrors.deposit_returned = "Cannot exceed deposit paid";
    }
    if (form.next_of_kin_phone && !isValidPhone(form.next_of_kin_phone)) nextErrors.next_of_kin_phone = PHONE_ERROR;
    if ((form.next_of_kin_phone || form.next_of_kin_relationship) && !isRequired(form.next_of_kin_name)) {
      nextErrors.next_of_kin_name = "Enter the next of kin's name";
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    const payload = { ...form };
    const billLines = moveIn.lines.filter((l) => Number(l.amount) > 0);
    if (isNew && billLines.length) {
      payload.move_in_billing = {
        enabled: true,
        bill_next_month: moveIn.bill_next_month,
        bill_month: moveIn.bill_next_month ? moveIn.bill_month : undefined,
        lines: billLines.map((l) => ({ category_id: l.category_id, subcategory: l.subcategory, item: l.item, amount: Number(l.amount) })),
      };
    }
    onSubmit(payload);
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
          hint={toKenyanPhone(form.phone) ? `Will be saved as ${toKenyanPhone(form.phone)}` : PHONE_HINT}
          required
          data-tour={ANCHORS.tenants.phoneField}
        />
        <Input label="Secondary phone" value={form.secondary_phone} onChange={update("secondary_phone")}
               error={errors.secondary_phone} hint="Tenant's other number" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Email" type="email" value={form.email} onChange={update("email")} error={errors.email} />
        <Input label="Account number" value={form.account_number} onChange={update("account_number")} hint="M-Pesa account reference" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="National ID" value={form.national_id} onChange={update("national_id")} />
        <Input label="KRA PIN" value={form.kra_pin} onChange={update("kra_pin")} />
      </div>

      <div className="border-t border-white/10 pt-4" data-testid="next-of-kin-section">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Next of kin</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Input label="Name" name="next_of_kin_name" value={form.next_of_kin_name} onChange={update("next_of_kin_name")}
                 error={errors.next_of_kin_name} />
          <Input label="Relationship" name="next_of_kin_relationship" placeholder="e.g. Sister, Spouse, Father"
                 value={form.next_of_kin_relationship} onChange={update("next_of_kin_relationship")} />
          <Input label="Phone" name="next_of_kin_phone" value={form.next_of_kin_phone} onChange={update("next_of_kin_phone")}
                 error={errors.next_of_kin_phone}
                 hint={toKenyanPhone(form.next_of_kin_phone) ? `Will be saved as ${toKenyanPhone(form.next_of_kin_phone)}` : PHONE_HINT} />
        </div>
      </div>

      <div className="border-t border-white/10 pt-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Deposit</p>
        <div className="grid grid-cols-3 gap-4">
          <Input label="Deposit amount" type="number" step="0.01" value={form.deposit_amount} onChange={update("deposit_amount")} />
          <Input label="Amount paid" type="number" step="0.01" value={form.deposit_paid} onChange={update("deposit_paid")}
                 hint="Paid before Sahil Pay. Billing the deposit below? Leave this empty." />
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

      {isNew && (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4" data-testid="move-in-billing">
          <p className="text-sm font-medium text-white">Move-in bill</p>
          <p className="mb-3 mt-1 text-xs leading-relaxed text-white/45">
            Invoice the tenant as you add them — deposit, rent, lease fee, anything else. It is a normal
            invoice: it shows on their statement, takes their payment and prints on the receipt.
          </p>
          {!form.unit_id ? (
            <p className="text-xs text-white/45">Choose the unit first.</p>
          ) : (
            <MoveInBillEditor value={moveIn} onChange={setMoveIn} unitId={form.unit_id} moveInDate={form.move_in_date} />
          )}
        </div>
      )}

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
