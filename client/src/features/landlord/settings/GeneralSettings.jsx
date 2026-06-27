import { useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import {
  useGetGeneralSettingsQuery,
  useUpdateGeneralSettingsMutation,
  useGetAutomationSettingsQuery,
  useUpdateAutomationSettingsMutation,
} from "./settingsApiSlice";
import { MPESA_TYPES, ACCOUNT_TYPES } from "@/utils/constants";

// §4.14 — company branding, M-Pesa config, automation toggles and communication channels.
export default function GeneralSettings() {
  const { data, isLoading } = useGetGeneralSettingsQuery();
  const { data: automation, isLoading: isAutomationLoading } = useGetAutomationSettingsQuery();
  const [updateGeneral, { isLoading: isSavingGeneral }] = useUpdateGeneralSettingsMutation();
  const [updateAutomation, { isLoading: isSavingAutomation }] = useUpdateAutomationSettingsMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    // Backend nests sms_enabled/whatsapp_enabled/email_enabled under channel_settings
    // on GET, but the PUT handler reads them flat — flatten on hydrate so both the
    // checkboxes display correctly AND a save-without-touching-them round-trips intact.
    setForm({ ...data, ...(data.channel_settings ?? {}) });
  }

  const [prevAutomation, setPrevAutomation] = useState();
  const [automationForm, setAutomationForm] = useState(null);
  if (automation && automation !== prevAutomation) {
    setPrevAutomation(automation);
    setAutomationForm(automation);
  }

  const [logo, setLogo] = useState(null);

  if (isLoading || isAutomationLoading || !form || !automationForm) return <SkeletonForm fields={8} />;

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const updateAuto = (key) => (e) => setAutomationForm((f) => ({ ...f, [key]: e.target.checked }));
  const updateAutoValue = (key) => (e) => setAutomationForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateGeneral({ ...form, logo }).unwrap();
      await updateAutomation(automationForm).unwrap();
      toast("Settings saved.", { type: "success" });
    } catch {
      toast("Could not save settings.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Company</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input label="Company name" value={form.company_name ?? ""} onChange={update("company_name")} required />
          <Input label="Abbreviated name" value={form.abbreviated_name ?? ""} onChange={update("abbreviated_name")} />
        </div>
        <Input label="Company address" value={form.company_address ?? ""} onChange={update("company_address")} />
        <FileUpload label="Logo" accept="image/*" value={logo} onChange={setLogo} hint="Appears on statements and receipts" />
        <div className="grid grid-cols-2 gap-4">
          <Input label="Invoice title" value={form.invoice_title ?? ""} onChange={update("invoice_title")} />
          <Select
            label="Account type"
            value={form.account_type ?? ""}
            onChange={update("account_type")}
            options={ACCOUNT_TYPES.map((t) => ({ value: t, label: t }))}
          />
        </div>
      </div>

      <div className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Locale &amp; M-Pesa</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input label="Currency" value={form.currency ?? "KES"} onChange={update("currency")} />
          <Input label="Timezone" value={form.timezone ?? "Africa/Nairobi"} onChange={update("timezone")} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Select label="M-Pesa type" value={form.mpesa_type ?? ""} onChange={update("mpesa_type")} options={MPESA_TYPES.map((t) => ({ value: t, label: t }))} />
          <Input label="Paybill/till number" value={form.mpesa_number ?? ""} onChange={update("mpesa_number")} />
        </div>
        <Input label="Default account number" value={form.default_account_number ?? ""} onChange={update("default_account_number")} />
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Automated tasks</h3>
        <Checkbox
          label="Automatically generate recurring rent invoices"
          checked={Boolean(automationForm.auto_generate_recurring_invoices)}
          onChange={updateAuto("auto_generate_recurring_invoices")}
        />
        <Checkbox
          label="Automatically generate other recurring bills"
          checked={Boolean(automationForm.auto_generate_recurring_bills)}
          onChange={updateAuto("auto_generate_recurring_bills")}
        />
        <Checkbox label="Alert me when a new tenant is added" checked={Boolean(automationForm.alert_on_new_tenant)} onChange={updateAuto("alert_on_new_tenant")} />
        <Checkbox
          label="Automatically send payment acknowledgments"
          checked={Boolean(automationForm.auto_send_payment_acknowledgments)}
          onChange={updateAuto("auto_send_payment_acknowledgments")}
        />
        <Checkbox label="Send monthly payment reminders" checked={Boolean(automationForm.monthly_reminders_enabled)} onChange={updateAuto("monthly_reminders_enabled")} />
        {automationForm.monthly_reminders_enabled && (
          <Input
            label="Reminder day of month"
            type="number"
            min="1"
            max="28"
            value={automationForm.monthly_reminder_day ?? ""}
            onChange={updateAutoValue("monthly_reminder_day")}
          />
        )}
        <Checkbox label="Send lease-expiry notifications" checked={Boolean(automationForm.lease_expiry_notifications)} onChange={updateAuto("lease_expiry_notifications")} />
        {automationForm.lease_expiry_notifications && (
          <Input
            label="Notify within (days)"
            type="number"
            min="1"
            value={automationForm.lease_expiry_range_days ?? ""}
            onChange={updateAutoValue("lease_expiry_range_days")}
          />
        )}
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Communication channels</h3>
        <Checkbox label="SMS" checked={Boolean(form.sms_enabled)} onChange={(e) => setForm((f) => ({ ...f, sms_enabled: e.target.checked }))} />
        <Checkbox label="WhatsApp" checked={Boolean(form.whatsapp_enabled)} onChange={(e) => setForm((f) => ({ ...f, whatsapp_enabled: e.target.checked }))} />
        <Checkbox label="Email" checked={Boolean(form.email_enabled)} onChange={(e) => setForm((f) => ({ ...f, email_enabled: e.target.checked }))} />
      </div>

      <div className="flex justify-end">
        <Button type="submit" isLoading={isSavingGeneral || isSavingAutomation}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
