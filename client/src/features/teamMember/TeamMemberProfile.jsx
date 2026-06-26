import { useState } from "react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetMyProfileQuery, useUpdateMyProfileMutation } from "./teamMemberApiSlice";

// Edit own limited profile fields — username changes stay with the landlord.
export default function TeamMemberProfile() {
  const { data, isLoading } = useGetMyProfileQuery();
  const [updateProfile, { isLoading: isSaving }] = useUpdateMyProfileMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    setForm(data);
  }

  if (isLoading || !form) return <SkeletonForm fields={4} />;

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateProfile(form).unwrap();
      toast("Profile updated.", { type: "success" });
    } catch {
      toast("Could not update your profile.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="glass space-y-4 p-6">
      <h1 className="mb-2 text-2xl font-light tracking-wide text-white">My profile</h1>
      <div className="grid grid-cols-2 gap-4">
        <Input label="First name" value={form.first_name ?? ""} onChange={update("first_name")} />
        <Input label="Last name" value={form.last_name ?? ""} onChange={update("last_name")} />
      </div>
      <Input label="Phone" value={form.phone ?? ""} onChange={update("phone")} />
      <Input label="Username" value={form.username ?? ""} disabled hint="Contact your landlord to change your username" />
      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
