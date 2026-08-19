import { useState } from "react";
import { Plus } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { useGetPortalMaintenanceRequestsQuery, useCreatePortalMaintenanceRequestMutation } from "./tenantPortalApiSlice";
import { MAINTENANCE_CATEGORIES } from "@/utils/constants";
import { formatDate } from "@/utils/dateFormatter";
import { isRequired } from "@/utils/validators";
import { withFiles } from "@/utils/multipart";

// §6.7 — open + list maintenance requests; visible to the landlord the moment they're created.
export default function TenantMaintenance() {
  const { data, isLoading } = useGetPortalMaintenanceRequestsQuery();
  const [createRequest, { isLoading: isCreating }] = useCreatePortalMaintenanceRequestMutation();

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState({ category: "plumbing", summary: "", description: "" });
  const [image, setImage] = useState(null);
  const [error, setError] = useState("");

  // Backend returns { requests: [...] }, not one of toRows()'s recognized keys.
  const requests = data?.requests ?? [];

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isRequired(form.summary)) {
      setError("A short summary is required");
      return;
    }
    setError("");
    try {
      // Multipart when there is a photo. Posting the File inside a JSON body
      // dropped it silently — the request reached the office with no image and
      // neither side was told, which is why tenant photos "never arrived".
      await createRequest(withFiles({ ...form, image }, ["image"])).unwrap();
      toast("Maintenance request submitted.", { type: "success" });
      setForm({ category: "plumbing", summary: "", description: "" });
      setImage(null);
      setIsFormOpen(false);
    } catch (err) {
      toast(err?.data?.error || "Could not submit your request.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.created_at) },
    { key: "summary", header: "Summary" },
    { key: "category", header: "Category" },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    // Their own proof that the photo arrived. Without it a tenant has no way to
    // tell a picture that uploaded from one that vanished.
    {
      key: "image_url", header: "Photo",
      render: (row) =>
        row.image_url ? (
          <a href={row.image_url} target="_blank" rel="noopener noreferrer"
             className="text-secondary underline-offset-2 hover:underline">
            <img src={row.image_url} alt={`Photo attached to: ${row.summary}`}
                 className="h-10 w-10 rounded-lg object-cover" />
          </a>
        ) : (
          <span className="text-white/30">—</span>
        ),
    },
  ];

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-light tracking-wide text-white">Maintenance requests</h1>
        <Button leftIcon={<Plus className="h-4 w-4" />} onClick={() => setIsFormOpen(true)}>
          New request
        </Button>
      </div>

      <ResponsiveTable
        columns={columns}
        rows={requests}
        isLoading={isLoading}
        emptyState={<p className="text-sm text-white/50">No maintenance requests yet.</p>}
      />

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title="New maintenance request">
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input label="Summary" value={form.summary} onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))} error={error} placeholder="e.g. Leaking tap" required />
          <Select
            label="Category"
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
            options={MAINTENANCE_CATEGORIES.map((c) => ({ value: c, label: c }))}
            required
          />
          <Textarea label="Description" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} hint="Optional" />
          <FileUpload label="Photo" accept="image/*" value={image} onChange={setImage} />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsFormOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isCreating}>
              Submit request
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
