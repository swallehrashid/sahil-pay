import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { ADMIN_ROUTES } from "@/config/routePaths";
import { useGetAffiliateConfigQuery, useUpdateAffiliateConfigMutation } from "./adminAffiliateApiSlice";

export default function AffiliateProgramSettings() {
  const { data, isLoading } = useGetAffiliateConfigQuery();
  const [update, { isLoading: isSaving }] = useUpdateAffiliateConfigMutation();
  const [confirmKillSwitch, setConfirmKillSwitch] = useState(false);

  const [prev, setPrev] = useState();
  const [form, setForm] = useState(null);
  if (data?.config && data.config !== prev) {
    setPrev(data.config);
    setForm(data.config);
  }

  if (isLoading || !form) return <Spinner className="mx-auto my-10" />;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async (overrides = {}) => {
    try {
      await update({
        default_commission_rate: form.default_commission_rate,
        default_commission_months: form.default_commission_months,
        min_withdrawal: form.min_withdrawal,
        wht_rate: form.wht_rate,
        fee_type: form.fee_type,
        fee_value: form.fee_value,
        attribution_grace_days: form.attribution_grace_days,
        is_program_active: form.is_program_active,
        ...overrides,
      }).unwrap();
      toast("Program settings saved.", { type: "success" });
    } catch {
      toast("Could not save settings.", { type: "error" });
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    save();
  };

  const toggleKillSwitch = async () => {
    const next = !form.is_program_active;
    setForm((f) => ({ ...f, is_program_active: next }));
    await save({ is_program_active: next });
    setConfirmKillSwitch(false);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Affiliate program settings"
        subtitle="Global defaults — changing these never touches existing referrals or withdrawals"
        breadcrumbs={[
          { label: "Admin", to: ADMIN_ROUTES.dashboard },
          { label: "Affiliates", to: ADMIN_ROUTES.affiliates },
          { label: "Settings" },
        ]}
      />

      <form onSubmit={handleSubmit} className="glass max-w-2xl space-y-5 p-6">
        <div>
          <h3 className="text-base font-medium text-white">Commission defaults</h3>
          <p className="mt-1 text-sm text-white/50">Applied to new referrals only — existing referrals keep their snapshotted terms.</p>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="Default commission rate (%)" type="number" step="0.01" value={form.default_commission_rate} onChange={set("default_commission_rate")} required />
          <Input label="Default commission months" type="number" value={form.default_commission_months} onChange={set("default_commission_months")} required />
        </div>

        <div>
          <h3 className="text-base font-medium text-white">Withdrawals</h3>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="Minimum withdrawal (KES)" type="number" step="0.01" value={form.min_withdrawal} onChange={set("min_withdrawal")} required />
          <Input label="Withholding tax rate (%)" type="number" step="0.01" value={form.wht_rate} onChange={set("wht_rate")} required hint="Confirm with your accountant — this deducts at source on every withdrawal." />
          <Select
            label="Platform fee type"
            value={form.fee_type}
            onChange={set("fee_type")}
            options={[{ value: "percent", label: "Percent of gross" }, { value: "flat", label: "Flat amount" }]}
          />
          <Input label={form.fee_type === "flat" ? "Fee (KES)" : "Fee (%)"} type="number" step="0.01" value={form.fee_value} onChange={set("fee_value")} required />
        </div>

        <div>
          <h3 className="text-base font-medium text-white">Attribution</h3>
        </div>
        <Input
          label="Grace window (days)"
          type="number"
          value={form.attribution_grace_days}
          onChange={set("attribution_grace_days")}
          hint="How long after registration the admin can still attribute a forgotten referral code."
          required
        />

        <div className="flex justify-end">
          <Button type="submit" isLoading={isSaving}>Save settings</Button>
        </div>
      </form>

      <div className="glass max-w-2xl space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Program kill switch</h3>
        <p className="text-sm text-white/50">
          When off: the public "Become an affiliate" link disappears, new affiliate signups are blocked, and
          new landlord referrals stop being attributed. Existing referrals keep accruing and affiliates can
          still withdraw what they've already earned — obligations are always honoured.
        </p>
        <Checkbox
          label={form.is_program_active ? "Program is ACTIVE" : "Program is INACTIVE"}
          checked={Boolean(form.is_program_active)}
          onChange={() => setConfirmKillSwitch(true)}
        />
      </div>

      <ConfirmDialog
        isOpen={confirmKillSwitch}
        onClose={() => setConfirmKillSwitch(false)}
        onConfirm={toggleKillSwitch}
        title={form.is_program_active ? "Turn off the affiliate program?" : "Turn on the affiliate program?"}
        description={
          form.is_program_active
            ? "New signups and new referral attributions will stop immediately. Existing referrals and withdrawals are unaffected."
            : "The public signup link and referral attribution will resume immediately."
        }
        confirmLabel={form.is_program_active ? "Turn off" : "Turn on"}
        isDangerous={form.is_program_active}
      />
    </div>
  );
}
