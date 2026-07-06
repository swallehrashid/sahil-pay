import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Spinner from "@/components/ui/Spinner";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetLandlordBillingQuery,
  useUpdateLandlordBillingMutation,
  useAddLandlordToCustomMutation,
} from "./adminPricingApiSlice";

// #16/#17 — admin opens a landlord under a package: view their billing cycle, amount
// due, trial status/end and next billing date, edit any of them manually, or move them
// into the Custom package at a negotiated per-unit price. Changes reflect to the landlord.
const STATUSES = ["trial", "active", "past_due", "cancelled"];

export default function AdminLandlordBillingModal({ landlordId, onClose }) {
  const isOpen = landlordId != null;
  const { data, isLoading } = useGetLandlordBillingQuery(landlordId, { skip: !isOpen });
  const [updateBilling, { isLoading: isSaving }] = useUpdateLandlordBillingMutation();
  const [addToCustom, { isLoading: isAdding }] = useAddLandlordToCustomMutation();

  const [form, setForm] = useState({});
  const [customPrice, setCustomPrice] = useState("");

  useEffect(() => {
    if (data) {
      setForm({
        amount_due: data.subscription?.amount_due ?? "",
        next_billing_date: data.subscription?.next_billing_date ?? "",
        status: data.subscription?.status ?? "active",
        billing_cycle: data.subscription?.billing_cycle ?? "monthly",
        is_on_trial: Boolean(data.is_on_trial),
        trial_ends_at: data.trial_ends_at ? data.trial_ends_at.slice(0, 10) : "",
      });
      setCustomPrice(data.per_unit_price ?? "");
    }
  }, [data]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    try {
      await updateBilling({
        id: landlordId,
        amount_due: form.amount_due === "" ? undefined : Number(form.amount_due),
        next_billing_date: form.next_billing_date || undefined,
        status: form.status,
        billing_cycle: form.billing_cycle,
        is_on_trial: form.is_on_trial,
        trial_ends_at: form.trial_ends_at || null,
      }).unwrap();
      toast("Billing updated.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not update billing.", { type: "error" });
    }
  };

  const moveToCustom = async () => {
    if (!customPrice) {
      toast("Enter a per-unit price.", { type: "error" });
      return;
    }
    try {
      await addToCustom({ id: landlordId, per_unit_price: Number(customPrice) }).unwrap();
      toast("Landlord moved to the Custom package.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not add to Custom.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Landlord billing">
      {isLoading || !data ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-white">{data.company_name}</p>
              <p className="text-xs text-white/50">
                Package: {data.package?.name ?? "—"}
                {data.is_custom_package && " (Custom)"}
              </p>
            </div>
            {data.is_on_trial && <Badge color="amber">On trial</Badge>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input label="Amount due" type="number" step="0.01" value={form.amount_due} onChange={set("amount_due")} />
            <Input label="Next billing date" type="date" value={form.next_billing_date} onChange={set("next_billing_date")} />
            <Select
              label="Status"
              value={form.status}
              onChange={set("status")}
              options={STATUSES.map((s) => ({ value: s, label: s }))}
            />
            <Select
              label="Billing cycle"
              value={form.billing_cycle}
              onChange={set("billing_cycle")}
              options={[{ value: "monthly", label: "Monthly" }, { value: "yearly", label: "Yearly" }]}
            />
          </div>

          <div className="flex items-center gap-6">
            <Checkbox
              label="Trial active"
              checked={Boolean(form.is_on_trial)}
              onChange={(e) => setForm((f) => ({ ...f, is_on_trial: e.target.checked }))}
            />
            <Input label="Trial ends" type="date" value={form.trial_ends_at} onChange={set("trial_ends_at")} className="flex-1" />
          </div>

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={save} isLoading={isSaving}>Save billing</Button>
          </div>

          {/* #17 — move into the Custom package at a negotiated per-unit price */}
          <div className="mt-2 space-y-2 rounded-xl border border-white/10 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-white/40">Custom package</p>
            <p className="text-xs text-white/50">
              Move this landlord to the private Custom package and set their per-unit price.
            </p>
            <div className="flex items-end gap-3">
              <Input
                label="Per-unit price"
                type="number"
                step="0.01"
                value={customPrice}
                onChange={(e) => setCustomPrice(e.target.value)}
                className="flex-1"
              />
              <Button variant="ghost" onClick={moveToCustom} isLoading={isAdding}>
                {data.is_custom_package ? "Update price" : "Add to Custom"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
