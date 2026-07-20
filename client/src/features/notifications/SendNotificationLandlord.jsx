import { useState } from "react";
import { Send } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useSendNotificationMutation, useGetNotificationTemplatesQuery } from "./notificationApiSlice";
import { useGetPropertiesQuery } from "@/features/landlord/properties/propertyApiSlice";
import { useGetTenantsQuery } from "@/features/landlord/tenants/tenantApiSlice";
import { useGetTeamMembersQuery } from "@/features/landlord/settings/teamApiSlice";
import { toRows } from "@/utils/tableAdapters";

const AUDIENCES = [
  { value: "all_tenants", label: "All my tenants" },
  { value: "property_tenants", label: "Tenants of one property" },
  { value: "all_team_members", label: "All my team members" },
  { value: "user", label: "A specific tenant or team member" },
];

// §8.5 — landlord broadcasts a templated or custom notification, always
// scoped to their own tenants/team/properties (the backend re-enforces this
// regardless of what's sent here). Mirrors SendNotificationAdmin.jsx's shape.
export default function SendNotificationLandlord() {
  const [sendNotification, { isLoading }] = useSendNotificationMutation();
  const { data: templatesData } = useGetNotificationTemplatesQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: tenantsData } = useGetTenantsQuery();
  const { data: teamData } = useGetTeamMembersQuery();

  const properties = toRows(propertiesData);
  const tenants = toRows(tenantsData);
  const teamMembers = teamData?.team_members ?? [];
  const templates = templatesData?.templates ?? [];

  const [form, setForm] = useState({
    audience: "all_tenants", target_id: "", target_type: "tenant",
    template_key: "", title: "", body: "", link: "",
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.template_key && (!form.title.trim() || !form.body.trim())) {
      toast("Provide a template, or a title and body.", { type: "error" });
      return;
    }
    if ((form.audience === "property_tenants" || form.audience === "user") && !form.target_id) {
      toast("Select a recipient.", { type: "error" });
      return;
    }
    try {
      await sendNotification({
        audience: form.audience,
        target_type: form.audience === "user" ? form.target_type : undefined,
        target_id: form.target_id ? Number(form.target_id) : undefined,
        template_key: form.template_key || undefined,
        title: form.template_key ? undefined : form.title,
        body: form.template_key ? undefined : form.body,
        link: form.link || undefined,
      }).unwrap();
      toast("Notification sent.", { type: "success" });
      setForm({ audience: "all_tenants", target_id: "", target_type: "tenant", template_key: "", title: "", body: "", link: "" });
    } catch {
      toast("Could not send the notification.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader title="Send Notification" subtitle="Broadcast an in-app notification to your tenants or team" />

      <form onSubmit={handleSubmit} className="glass max-w-2xl space-y-4 p-6">
        <Select
          label="Audience"
          value={form.audience}
          onChange={(e) => setForm((f) => ({ ...f, audience: e.target.value, target_id: "" }))}
          options={AUDIENCES}
          required
        />

        {form.audience === "property_tenants" && (
          <Select
            label="Property"
            value={form.target_id}
            onChange={(e) => setForm((f) => ({ ...f, target_id: e.target.value }))}
            options={properties.map((p) => ({ value: p.id, label: p.name }))}
            required
          />
        )}

        {form.audience === "user" && (
          <>
            <Select
              label="Recipient type"
              value={form.target_type}
              onChange={(e) => setForm((f) => ({ ...f, target_type: e.target.value, target_id: "" }))}
              options={[{ value: "tenant", label: "Tenant" }, { value: "team_member", label: "Team member" }]}
            />
            <Select
              label={form.target_type === "tenant" ? "Tenant" : "Team member"}
              value={form.target_id}
              onChange={(e) => setForm((f) => ({ ...f, target_id: e.target.value }))}
              options={
                form.target_type === "tenant"
                  ? tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))
                  : teamMembers.map((m) => ({ value: m.id, label: m.username }))
              }
              required
            />
          </>
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
          hint="A frontend route to deep-link to when the notification is clicked, e.g. /portal/pay"
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
