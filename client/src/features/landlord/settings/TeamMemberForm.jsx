import { useState } from "react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import PermissionMatrix from "./PermissionMatrix";
import RolePresetPicker from "./RolePresetPicker";
import TaxCompliancePermissions from "./TaxCompliancePermissions";
import { TEAM_MEMBER_ROLES, PERMISSION_MODULES } from "@/utils/constants";
import { isRequired, isValidEmail } from "@/utils/validators";

function defaultPermissions() {
  return PERMISSION_MODULES.reduce((acc, module) => ({ ...acc, [module]: { can_view: false, can_edit: false } }), {});
}

// §4.20 — username/email/role + property scope + the full permission matrix in one form.
export default function TeamMemberForm({ initialValues, properties = [], onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    username: "",
    email: "",
    first_name: "",
    last_name: "",
    phone: "",
    role: "viewer",
    preset: "",
    property_access_all: true,
    property_ids: [],
    ...initialValues,
  });
  const [permissions, setPermissions] = useState(initialValues?.permissions ?? defaultPermissions());
  const [errors, setErrors] = useState({});

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  /**
   * Applying a preset FILLS IN the matrix below — it does not lock it. Every
   * module and every property stays editable afterwards, which is the point:
   * the preset saves the landlord ticking twelve boxes for the hundredth owner
   * login, and then they tighten anything they want.
   *
   * An owner preset forces a specific-properties scope: an owner who could see
   * every property would be reading the other landlords' books.
   */
  const applyPreset = (preset) => {
    const next = defaultPermissions();
    for (const row of preset.permissions) {
      next[row.module] = { can_view: row.can_view, can_edit: row.can_edit };
    }
    setPermissions(next);
    setForm((f) => ({
      ...f,
      preset: preset.key,
      role: preset.role ?? f.role,
      property_access_all: preset.scope === "specific" ? false : f.property_access_all,
    }));
  };

  const toggleProperty = (id) => {
    setForm((f) => ({
      ...f,
      property_ids: f.property_ids.includes(id) ? f.property_ids.filter((p) => p !== id) : [...f.property_ids, id],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.username)) nextErrors.username = "Username is required";
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    onSubmit({ ...form, permissions });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Presets only when creating — changing an existing member's role
          shouldn't silently rewrite permissions somebody hand-tuned. */}
      {!initialValues?.id && (
        <RolePresetPicker
          value={form.preset}
          onChange={applyPreset}
          className="border-b border-white/10 pb-5"
        />
      )}

      <div className="grid grid-cols-2 gap-4">
        <Input label="Username" value={form.username} onChange={update("username")} error={errors.username} required />
        <Input label="Email" type="email" value={form.email} onChange={update("email")} error={errors.email} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="First name" value={form.first_name} onChange={update("first_name")} />
        <Input label="Last name" value={form.last_name} onChange={update("last_name")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Phone" value={form.phone} onChange={update("phone")} />
        <Select label="Role" value={form.role} onChange={update("role")} options={TEAM_MEMBER_ROLES.map((r) => ({ value: r, label: r }))} required />
      </div>

      <div className="border-t border-white/10 pt-4">
        <Checkbox
          label="Access all properties"
          checked={form.property_access_all}
          onChange={(e) => setForm((f) => ({ ...f, property_access_all: e.target.checked }))}
        />
        {!form.property_access_all && (
          <div className="glass mt-3 max-h-40 space-y-1 overflow-y-auto p-3">
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
        )}
      </div>

      <div className="border-t border-white/10 pt-4">
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-white/40">Permissions</p>
        <PermissionMatrix permissions={permissions} onChange={setPermissions} />
      </div>

      {/* Per-property tax-compliance grants. Saves on its own button rather
          than with the form, because a grant needs a saved member id — and it
          renders nothing at all unless the account has opted into eTIMS. */}
      <TaxCompliancePermissions
        memberId={initialValues?.id}
        memberName={form.first_name || form.username}
      />

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save team member
        </Button>
      </div>
    </form>
  );
}
