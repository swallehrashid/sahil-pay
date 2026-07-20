import { useState } from "react";
import { Send } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useSendNotificationMutation, useGetNotificationTemplatesQuery } from "./notificationApiSlice";
import { useGetAdminLandlordsQuery } from "@/features/admin/adminApiSlice";
import { toRows } from "@/utils/tableAdapters";

const AUDIENCES = [
  { value: "all_landlords", label: "All landlords (platform-wide)" },
  { value: "landlord", label: "A specific landlord" },
  { value: "all_tenants", label: "Tenants (one landlord, or all if left blank)" },
  { value: "all_team_members", label: "Team members (one landlord, or all if left blank)" },
];

// §8.5 — system admin broadcasts a templated or custom notification to a
// platform-wide or landlord-scoped audience. Mirrors SendNotificationLandlord.jsx's
// shape, but with the wider admin-only audience set.
export default function SendNotificationAdmin() {
  const [sendNotification, { isLoading }] = useSendNotificationMutation();
  const { data: templatesData } = useGetNotificationTemplatesQuery();
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const landlords = toRows(landlordsData);
  const templates = templatesData?.templates ?? [];

  const [form, setForm] = useState({ audience: "all_landlords", target_id: "", template_key: "", title: "", body: "", link: "" });
  const needsLandlordTarget = form.audience === "landlord";
  const optionalLandlordTarget = form.audience === "all_tenants" || form.audience === "all_team_members";

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.template_key && (!form.title.trim() || !form.body.trim())) {
      toast("Provide a template, or a title and body.", { type: "error" });
      return;
    }
    if (needsLandlordTarget && !form.target_id) {
      toast("Select a landlord.", { type: "error" });
      return;
    }
    try {
      await sendNotification({
        audience: form.audience,
        target_id: form.target_id ? Number(form.target_id) : undefined,
        template_key: form.template_key || undefined,
        title: form.template_key ? undefined : form.title,
        body: form.template_key ? undefined : form.body,
        link: form.link || undefined,
      }).unwrap();
      toast("Notification sent.", { type: "success" });
      setForm({ audience: "all_landlords", target_id: "", template_key: "", title: "", body: "", link: "" });
    } catch {
      toast("Could not send the notification.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader title="Send Notification" subtitle="Broadcast an in-app notification to landlords, tenants, or team members" />

      <form onSubmit={handleSubmit} className="glass max-w-2xl space-y-4 p-6">
        <Select
          label="Audience"
          value={form.audience}
          onChange={(e) => setForm((f) => ({ ...f, audience: e.target.value, target_id: "" }))}
          options={AUDIENCES}
          required
        />

        {(needsLandlordTarget || optionalLandlordTarget) && (
          <Select
            label={needsLandlordTarget ? "Landlord" : "Landlord (optional — leave blank for all)"}
            value={form.target_id}
            onChange={(e) => setForm((f) => ({ ...f, target_id: e.target.value }))}
            placeholder="All landlords"
            options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
            required={needsLandlordTarget}
          />
        )}

        <Select
          label="Template (optional)"
          value={form.template_key}
          onChange={(e) => setForm((f) => ({ ...f, template_key: e.target.value }))}
          placeholder="Custom message"
          options={templates.filter((t) => t !== "broadcast").map((t) => ({ value: t, label: t.replace(/_/g, " ") }))}
        />

        {!form.template_key && (
          <>
            <Input label="Title" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} required />
            <Textarea label="Message" value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} rows={4} required />
          </>
        )}

        <Input
          label="Link (optional)"
          value={form.link}
          onChange={(e) => setForm((f) => ({ ...f, link: e.target.value }))}
          hint="A frontend route to deep-link to when the notification is clicked, e.g. /landlord/billing"
        />

        <div className="flex justify-end pt-2">
          <Button type="submit" leftIcon={<Send className="h-4 w-4" />} isLoading={isLoading}>
            Send notification
          </Button>
        </div>
      </form>
    </div>
  );
}
