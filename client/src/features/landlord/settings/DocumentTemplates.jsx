import { useState } from "react";
import { Plus, Pencil, Trash2, Send } from "lucide-react";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import FileUpload from "@/components/ui/FileUpload";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetDocumentTemplatesQuery,
  useCreateDocumentTemplateMutation,
  useUpdateDocumentTemplateMutation,
  useDeleteDocumentTemplateMutation,
  useSendDocumentMutation,
} from "./documentApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { DOCUMENT_TYPES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";
import { toRows } from "@/utils/tableAdapters";

function TemplateForm({ initialValues, onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ name: "", document_type: "lease", content: "", ...initialValues });
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isRequired(form.name)) {
      setError("Template name is required");
      return;
    }
    setError("");
    onSubmit({ ...form, file });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input label="Name" value={form.name} onChange={update("name")} error={error} required />
      <Select label="Document type" value={form.document_type} onChange={update("document_type")} options={DOCUMENT_TYPES.map((t) => ({ value: t, label: t }))} required />
      <Textarea label="Content" rows={6} value={form.content} onChange={update("content")} hint="HTML body rendered to PDF, or upload a file instead" />
      <FileUpload label="Or upload a file" value={file} onChange={setFile} />
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

function SendDocumentModal({ template, tenants, onClose }) {
  const [sendDocument, { isLoading }] = useSendDocumentMutation();
  const [tenantId, setTenantId] = useState("");

  if (!template) return null;

  const handleSend = async (e) => {
    e.preventDefault();
    try {
      await sendDocument({ template_id: template.id, tenant_id: tenantId }).unwrap();
      toast("Document sent.", { type: "success" });
      onClose();
    } catch {
      toast("Could not send the document.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Send "${template.name}"`}>
      <form onSubmit={handleSend} className="space-y-4">
        <Select
          label="Tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
          required
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Send
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// §4.18 (beta) — lease/tenancy/deposit document templates, dispatched to tenants.
export default function DocumentTemplates() {
  const { data, isLoading } = useGetDocumentTemplatesQuery();
  const { data: tenantsData } = useGetTenantsQuery();
  const [createTemplate, { isLoading: isCreating }] = useCreateDocumentTemplateMutation();
  const [updateTemplate, { isLoading: isUpdating }] = useUpdateDocumentTemplateMutation();
  const [deleteTemplate] = useDeleteDocumentTemplateMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [sendTarget, setSendTarget] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const templates = toRows(data);
  const tenants = toRows(tenantsData);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateTemplate({ id: active.id, ...values }).unwrap();
        toast("Template updated.", { type: "success" });
      } else {
        await createTemplate(values).unwrap();
        toast("Template added.", { type: "success" });
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
    { key: "document_type", header: "Type", render: (row) => <Badge>{row.document_type}</Badge> },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-white/50">Lease, tenancy agreement and deposit document templates.</p>
        <Button
          size="sm"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setActive(null);
            setIsFormOpen(true);
          }}
        >
          Add document
        </Button>
      </div>

      <ResponsiveTable
        columns={columns}
        rows={templates}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              { label: "Send to tenant", icon: <Send className="h-4 w-4" />, onClick: () => setSendTarget(row) },
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

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit document" : "Add document"} size="lg">
        <TemplateForm initialValues={active} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <SendDocumentModal template={sendTarget} tenants={tenants} onClose={() => setSendTarget(null)} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete document template?"
        description="This template will be permanently removed."
      />
    </div>
  );
}
