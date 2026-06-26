import { useState } from "react";
import { Copy } from "lucide-react";
import Input from "@/components/ui/Input";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetAccountSettingsQuery, useUpdateAccountSettingsMutation, useGenerateAgentCodeMutation } from "./settingsApiSlice";

// §4.17 — profile, signature, change password, generate Co-pilot agent code.
export default function AccountSettings() {
  const { data, isLoading } = useGetAccountSettingsQuery();
  const [updateAccount, { isLoading: isSaving }] = useUpdateAccountSettingsMutation();
  const [generateAgentCode, { isLoading: isGeneratingCode }] = useGenerateAgentCodeMutation();

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

  const handleGenerateCode = async () => {
    try {
      const result = await generateAgentCode().unwrap();
      setForm((f) => ({ ...f, agent_code: result?.agent_code ?? f.agent_code }));
      toast("Agent code generated.", { type: "success" });
    } catch {
      toast("Could not generate an agent code.", { type: "error" });
    }
  };

  const copyAgentCode = () => {
    if (form.agent_code) {
      navigator.clipboard.writeText(form.agent_code);
      toast("Agent code copied.", { type: "success" });
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

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Co-pilot agent code</h3>
        <p className="text-sm text-white/50">Connects your Co-pilot SMS-forwarding app to this account.</p>
        <div className="flex items-center gap-3">
          <Input value={form.agent_code ?? "Not generated yet"} readOnly className="flex-1" />
          {form.agent_code && (
            <Button type="button" variant="ghost" size="sm" leftIcon={<Copy className="h-4 w-4" />} onClick={copyAgentCode}>
              Copy
            </Button>
          )}
          <Button type="button" variant="ghost" size="sm" isLoading={isGeneratingCode} onClick={handleGenerateCode}>
            Generate new
          </Button>
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
