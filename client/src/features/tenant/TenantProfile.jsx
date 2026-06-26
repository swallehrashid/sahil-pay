import { useState } from "react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetPortalProfileQuery, useUpdatePortalProfileMutation } from "./tenantPortalApiSlice";
import { isValidEmail, isValidPhone } from "@/utils/validators";

// §6.6 — profile edits write straight to the same tenants row the landlord sees.
export default function TenantProfile() {
  const { data, isLoading } = useGetPortalProfileQuery();
  const [updateProfile, { isLoading: isSaving }] = useUpdatePortalProfileMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    setForm(data);
  }

  const [errors, setErrors] = useState({});

  if (isLoading || !form) return <SkeletonForm fields={5} />;

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isValidPhone(form.phone)) nextErrors.phone = "Enter a valid phone number";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    try {
      await updateProfile(form).unwrap();
      toast("Profile updated.", { type: "success" });
    } catch {
      toast("Could not update your profile.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="glass animate-fade-in-up space-y-4 p-6">
      <h1 className="mb-2 text-2xl font-light tracking-wide text-white">Profile</h1>
      <p className="text-sm text-white/50">Changes here sync straight to your landlord's records.</p>
      <div className="grid grid-cols-2 gap-4">
        <Input label="First name" value={form.first_name ?? ""} onChange={update("first_name")} />
        <Input label="Last name" value={form.last_name ?? ""} onChange={update("last_name")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Phone" value={form.phone ?? ""} onChange={update("phone")} error={errors.phone} />
        <Input label="Email" type="email" value={form.email ?? ""} onChange={update("email")} error={errors.email} />
      </div>
      <Input label="Secondary phone" value={form.secondary_phone ?? ""} onChange={update("secondary_phone")} />
      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
