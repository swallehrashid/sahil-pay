import { useState } from "react";
import { Plus, Pencil, Trash2, Sparkles } from "lucide-react";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetMessageTemplatesQuery,
  useGetMessageVariablesQuery,
  useInstallDefaultTemplatesMutation,
  useCreateMessageTemplateMutation,
  useUpdateMessageTemplateMutation,
  useDeleteMessageTemplateMutation,
} from "./communicationApiSlice";
import { MESSAGE_CHANNELS, MESSAGE_TEMPLATE_TYPES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { toRows } from "@/utils/tableAdapters";

function TemplateForm({ initialValues, variables = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ name: "", channel: "sms", template_type: "custom", body: "", ...initialValues });
  const [errors, setErrors] = useState({});
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const insertVariable = (key) => setForm((f) => ({ ...f, body: `${f.body}${key}` }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.name)) nextErrors.name = "Template name is required";
    if (!isRequired(form.body)) nextErrors.body = "Template body is required";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input label="Name" value={form.name} onChange={update("name")} error={errors.name} required />
      <div className="grid grid-cols-2 gap-4">
        <Select label="Channel" value={form.channel} onChange={update("channel")} options={MESSAGE_CHANNELS.map((c) => ({ value: c, label: c }))} required />
        <Select
          label="Type"
          value={form.template_type}
          onChange={update("template_type")}
          options={MESSAGE_TEMPLATE_TYPES.map((t) => ({ value: t, label: t }))}
          required
        />
      </div>
      <Textarea
        label="Body"
        rows={5}
        value={form.body}
        onChange={update("body")}
        error={errors.body}
        hint="Click a variable below to insert it — it's replaced per tenant at send time."
        required
      />
      {variables.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {variables.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => insertVariable(v.key)}
              title={v.label}
              className="rounded-full border border-white/15 bg-white/5 px-2.5 py-1 text-xs text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            >
              {v.key}
            </button>
          ))}
        </div>
      )}
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save template
        </Button>
      </div>
    </form>
  );
}

// §4.19 — reusable SMS/WhatsApp/email templates with dynamic placeholders.
export default function MessageTemplates() {
  const { data, isLoading } = useGetMessageTemplatesQuery();
  const { data: variablesData } = useGetMessageVariablesQuery();
  const [installDefaults, { isLoading: isInstalling }] = useInstallDefaultTemplatesMutation();
  const [createTemplate, { isLoading: isCreating }] = useCreateMessageTemplateMutation();
  const [updateTemplate, { isLoading: isUpdating }] = useUpdateMessageTemplateMutation();
  const [deleteTemplate] = useDeleteMessageTemplateMutation();

  const variables = variablesData?.variables ?? [];

  const handleInstallDefaults = async () => {
    try {
      const res = await installDefaults().unwrap();
      toast(res.installed?.length ? `${res.installed.length} starter template(s) added.` : "Starter templates already installed.", { type: "success" });
    } catch {
      toast("Could not install starter templates.", { type: "error" });
    }
  };

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const templates = toRows(data);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateTemplate({ id: active.id, ...values }).unwrap();
        toast("Template updated.", { type: "success" });
      } else {
        await createTemplate(values).unwrap();
        toast("Template created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the template.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTemplate(pendingDelete.id).unwrap();
      toast("Template deleted.", { type: "success" });
    } catch {
      toast("Could not delete the template.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "name", header: "Name" },
    { key: "channel", header: "Channel", render: (row) => <Badge>{row.channel}</Badge> },
    { key: "template_type", header: "Type" },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-white/50">Reusable templates with dynamic placeholders. Each starter template already includes your payment method.</p>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" leftIcon={<Sparkles className="h-4 w-4" />} isLoading={isInstalling} onClick={handleInstallDefaults}>
            Use starter templates
          </Button>
          <Button
            size="sm"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setActive(null);
              setIsFormOpen(true);
            }}
          >
            Add template
          </Button>
        </div>
      </div>

      <ResponsiveTable
        columns={columns}
        rows={templates}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              {
                label: "Edit",
                icon: <Pencil className="h-4 w-4" />,
                onClick: () => {
                  setActive(row);
                  setIsFormOpen(true);
                },
              },
              { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit template" : "Add template"}>
        <TemplateForm initialValues={active} variables={variables} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete template?"
        description="This message template will be permanently removed."
      />
    </div>
  );
}
