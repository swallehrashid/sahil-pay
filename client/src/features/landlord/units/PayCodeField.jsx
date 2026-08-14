import { useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import {
  useLazyCheckPayCodeQuery,
  useSetPayCodeMutation,
} from "@/features/landlord/allocation/allocationApiSlice";

// sahilpay_payment_allocation_spec.md §7 — the pay-code field on the unit form.
//
// Saved separately from the rest of the form because changing a code has a
// consequence the owner needs told about: the old one is retired but KEEPS
// WORKING, since tenants have it saved in M-Pesa. Bundling that into a generic
// "Save unit" would hide it.
//
// Only rendered for a SAVED unit — a code needs a unit id to hang off, and the
// backend generates one automatically on create anyway.
export default function PayCodeField({ unit }) {
  const [value, setValue] = useState(unit?.pay_code ?? "");
  const [check, { data: availability, isFetching }] = useLazyCheckPayCodeQuery();
  const [save, { isLoading: saving }] = useSetPayCodeMutation();

  useEffect(() => setValue(unit?.pay_code ?? ""), [unit?.pay_code]);

  // Debounced live uniqueness check, so a duplicate is caught while typing
  // rather than on submit.
  useEffect(() => {
    const trimmed = value.trim();
    if (!trimmed || trimmed === unit?.pay_code) return;
    const timer = setTimeout(() => check({ code: trimmed, unitId: unit?.id }), 400);
    return () => clearTimeout(timer);
  }, [value, unit?.id, unit?.pay_code, check]);

  if (!unit?.id) return null;

  const changed = value.trim() && value.trim().toUpperCase() !== (unit.pay_code ?? "");
  const taken = changed && availability && availability.available === false;

  const submit = async () => {
    try {
      const result = await save({ unitId: unit.id, pay_code: value }).unwrap();
      toast(result.previous
        ? `Pay code changed to ${result.pay_code}. ${result.previous} will keep working.`
        : `Pay code set to ${result.pay_code}.`, { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save that pay code.", { type: "error" });
    }
  };

  return (
    <div className="space-y-2 border-t border-white/10 pt-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Input
          label="Pay code"
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          hint="What tenants quote when paying. Must be unique across your account."
          error={taken ? "That code is already in use on this account." : undefined}
        />
        <Button type="button" className="shrink-0" onClick={submit}
                isLoading={saving} disabled={!changed || taken || isFetching}>
          Save code
        </Button>
      </div>

      {changed && availability?.available && (
        <p className="flex items-center gap-1 text-xs text-third-100">
          <Check size={12} /> {availability.code} is available.
        </p>
      )}
      {taken && (
        <p className="flex items-center gap-1 text-xs text-secondary">
          <X size={12} /> Pick a different code.
        </p>
      )}
      {unit.pay_code && changed && !taken && (
        <p className="text-xs text-white/40">
          Tenants still paying with {unit.pay_code} will keep being matched correctly.
        </p>
      )}
    </div>
  );
}
