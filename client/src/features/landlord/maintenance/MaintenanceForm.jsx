import { useState } from "react";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { MAINTENANCE_CATEGORIES, MAINTENANCE_STATUSES } from "@/utils/constants";
import { isRequired } from "@/utils/validators";

export default function MaintenanceForm({ initialValues, properties = [], units = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    property_id: "",
    unit_id: "",
    status: "open",
    category: "plumbing",
    summary: "",
    description: "",
    ...initialValues,
  });
  const [image, setImage] = useState(null);
  const [errors, setErrors] = useState({});
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const unitOptions = units.filter((u) => !form.property_id || String(u.property_id) === String(form.property_id));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.unit_id)) nextErrors.unit_id = "Select a unit";
    if (!isRequired(form.summary)) nextErrors.summary = "A short summary is required";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit({ ...form, image });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Select label="Property" value={form.property_id} onChange={update("property_id")} options={properties.map((p) => ({ value: p.id, label: p.name }))} required />
        <Select
          label="Unit"
          value={form.unit_id}
          onChange={update("unit_id")}
          error={errors.unit_id}
          options={unitOptions.map((u) => ({ value: u.id, label: u.name }))}
          required
        />
      </div>
      <Input label="Summary" value={form.summary} onChange={update("summary")} error={errors.summary} placeholder="e.g. Broken ceiling light" required />
      <div className="grid grid-cols-2 gap-4">
        <Select label="Category" value={form.category} onChange={update("category")} options={MAINTENANCE_CATEGORIES.map((c) => ({ value: c, label: c }))} required />
        <Select label="Status" value={form.status} onChange={update("status")} options={MAINTENANCE_STATUSES.map((s) => ({ value: s, label: s }))} required />
      </div>
      <Textarea label="Description" value={form.description} onChange={update("description")} hint="Optional" />
      <FileUpload label="Photo" accept="image/*" value={image} onChange={setImage} />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save request
        </Button>
      </div>
    </form>
  );
}
