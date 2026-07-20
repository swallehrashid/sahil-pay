import { useState } from "react";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { isRequired } from "@/utils/validators";

export default function GroupForm({ initialValues, properties = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ name: "", property_ids: [], ...initialValues });
  const [error, setError] = useState("");

  const toggleProperty = (id) => {
    setForm((f) => ({
      ...f,
      property_ids: f.property_ids.includes(id) ? f.property_ids.filter((p) => p !== id) : [...f.property_ids, id],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isRequired(form.name)) {
      setError("Group name is required");
      return;
    }
    setError("");
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input label="Group name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} error={error} required />
      <div>
        <p className="mb-1.5 text-sm font-medium text-white/70">Properties in this group</p>
        <div className="glass max-h-48 space-y-1 overflow-y-auto p-3">
          {properties.map((property) => (
            <Checkbox
              key={property.id}
              label={property.name}
              checked={form.property_ids.includes(property.id)}
              onChange={() => toggleProperty(property.id)}
              className="w-full px-2 py-1.5"
            />
          ))}
        </div>
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save group
        </Button>
      </div>
    </form>
  );
}
