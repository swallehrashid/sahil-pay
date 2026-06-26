import { useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
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
  useCreateMessageTemplateMutation,
  useUpdateMessageTemplateMutation,
  useDeleteMessageTemplateMutation,
} from "./communicationApiSlice";
import { MESSAGE_CHANNELS, MESSAGE_TEMPLATE_TYPES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { toRows } from "@/utils/tableAdapters";

function TemplateForm({ initialValues, onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ name: "", channel: "sms", template_type: "custom", body: "", ...initialValues });
  const [errors, setErrors] = useState({});
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

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
        hint="Supports {tenant_name}, {balance}, {invoice_items}…"
        required
      />
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
  const [createTemplate, { isLoading: isCreating }] = useCreateMessageTemplateMutation();
  const [updateTemplate, { isLoading: isUpdating }] = useUpdateMessageTemplateMutation();
  const [deleteTemplate] = useDeleteMessageTemplateMutation();

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
        <p className="text-sm text-white/50">Reusable templates with dynamic placeholders for balance and invoice reminders.</p>
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
        <TemplateForm initialValues={active} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
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
