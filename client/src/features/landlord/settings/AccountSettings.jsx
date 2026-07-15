import { useState } from "react";
import Input from "@/components/ui/Input";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetAccountSettingsQuery, useUpdateAccountSettingsMutation } from "./settingsApiSlice";

// §4.17 — profile, signature, change password. Co-pilot agent code lives in
// Settings → Co-pilot now (CopilotSettings.jsx) alongside the rest of its config.
export default function AccountSettings() {
  const { data, isLoading } = useGetAccountSettingsQuery();
  const [updateAccount, { isLoading: isSaving }] = useUpdateAccountSettingsMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    setForm(data);
  }

  const [signature, setSignature] = useState(null);
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });

  if (isLoading || !form) return <SkeletonForm fields={6} />;

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateAccount({ ...form, signature, ...(passwords.new_password ? passwords : {}) }).unwrap();
      toast("Account updated.", { type: "success" });
      setPasswords({ current_password: "", new_password: "" });
    } catch {
      toast("Could not update your account.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Profile</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input label="Username" value={form.username ?? ""} onChange={update("username")} />
          <Input label="Email" type="email" value={form.email ?? ""} onChange={update("email")} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input label="First name" value={form.first_name ?? ""} onChange={update("first_name")} />
          <Input label="Last name" value={form.last_name ?? ""} onChange={update("last_name")} />
        </div>
        <FileUpload label="Signature" accept="image/*" value={signature} onChange={setSignature} hint="Appears on statements and receipts" />
      </div>

      <div className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Change password</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Current password"
            type="password"
            value={passwords.current_password}
            onChange={(e) => setPasswords((p) => ({ ...p, current_password: e.target.value }))}
          />
          <Input
            label="New password"
            type="password"
            value={passwords.new_password}
            onChange={(e) => setPasswords((p) => ({ ...p, new_password: e.target.value }))}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>
          Save account
        </Button>
      </div>
    </form>
  );
}
