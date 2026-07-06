import { useState } from "react";
import { MessageSquare, Link2, Unlink, CheckCircle2 } from "lucide-react";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonForm } from "@/components/ui/Skeleton";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetSmsProviderQuery,
  useUpdateSmsProviderMutation,
  useConnectSmsProviderMutation,
  useDisconnectSmsProviderMutation,
} from "./smsProviderApiSlice";

// §9.3 — connect Africa's Talking so SMS go out under the landlord's own
// sender ID (flat rate per SMS). Without a sender ID, SahilPay's shared sender
// ID is used and messages are billed by length.
export default function SmsProviderSettings() {
  const { data, isLoading } = useGetSmsProviderQuery();
  const [update, { isLoading: isSaving }] = useUpdateSmsProviderMutation();
  const [connect, { isLoading: isConnecting }] = useConnectSmsProviderMutation();
  const [disconnect, { isLoading: isDisconnecting }] = useDisconnectSmsProviderMutation();

  const [form, setForm] = useState({ at_api_key: "", at_username: "", at_sender_id: "" });
  const [prev, setPrev] = useState();
  if (data && data !== prev) {
    setPrev(data);
    // Never hydrate the secret key back into the field; keep username/sender.
    setForm({ at_api_key: "", at_username: data.at_username ?? "", at_sender_id: data.at_sender_id ?? "" });
  }

  if (isLoading) return <SkeletonForm fields={3} />;

  const connected = Boolean(data?.at_connected);

  const handleSave = async (e) => {
    e.preventDefault();
    // Only send the api key when the user actually typed a new one.
    const body = { at_username: form.at_username, at_sender_id: form.at_sender_id };
    if (form.at_api_key.trim()) body.at_api_key = form.at_api_key.trim();
    try {
      await update(body).unwrap();
      toast("SMS provider details saved.", { type: "success" });
      setForm((f) => ({ ...f, at_api_key: "" }));
    } catch {
      toast("Could not save the details.", { type: "error" });
    }
  };

  const handleConnect = async () => {
    try {
      await connect().unwrap();
      toast("Africa's Talking connected.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error ?? "Could not connect. Save your details first.", { type: "error" });
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnect().unwrap();
      toast("Disconnected. Messages now use SahilPay's shared sender ID.", { type: "success" });
    } catch {
      toast("Could not disconnect.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <SummaryCard
          label="Connection"
          value={connected ? <Badge color="emerald">Connected</Badge> : <Badge color="secondary">Not connected</Badge>}
          icon={<MessageSquare className="h-5 w-5" />}
        />
        <SummaryCard label="Sender ID" value={connected ? (data?.at_sender_id ?? "—") : "SahilPay (shared)"} accent="third" />
        <SummaryCard label="Billing" value={connected ? "1 KES / SMS" : "By length"} accent="third" />
      </div>

      <div className="glass space-y-2 p-6 text-sm text-white/60">
        <p className="text-white/80 font-medium">How it works</p>
        <p>
          Connect your Africa's Talking account and registered sender ID to send SMS under your own brand —
          billed a flat <span className="text-white">1 KES per SMS</span>. SahilPay delivers the messages for you.
        </p>
        <p>
          No sender ID? You can still send using SahilPay's shared sender ID — those messages are
          <span className="text-white"> billed by length</span> (longer messages use more segments and cost more).
        </p>
      </div>

      <form onSubmit={handleSave} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Africa's Talking credentials</h3>
        <Input
          label="API key"
          type="password"
          placeholder={data?.at_api_key_set ? `Saved (${data.at_api_key_masked})` : "Paste your Africa's Talking API key"}
          value={form.at_api_key}
          onChange={(e) => setForm((f) => ({ ...f, at_api_key: e.target.value }))}
          hint={data?.at_api_key_set ? "Leave blank to keep the saved key." : undefined}
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="Username"
            placeholder="Your AT username"
            value={form.at_username}
            onChange={(e) => setForm((f) => ({ ...f, at_username: e.target.value }))}
          />
          <Input
            label="Sender ID"
            placeholder="e.g. YOURBRAND"
            value={form.at_sender_id}
            onChange={(e) => setForm((f) => ({ ...f, at_sender_id: e.target.value }))}
          />
        </div>
        <div className="flex flex-wrap justify-end gap-3">
          <Button type="submit" variant="ghost" isLoading={isSaving}>Save details</Button>
          {connected ? (
            <Button type="button" variant="danger" leftIcon={<Unlink className="h-4 w-4" />} isLoading={isDisconnecting} onClick={handleDisconnect}>
              Disconnect
            </Button>
          ) : (
            <Button type="button" leftIcon={<Link2 className="h-4 w-4" />} isLoading={isConnecting} onClick={handleConnect}>
              Connect
            </Button>
          )}
        </div>
      </form>

      {connected && (
        <div className="glass flex items-center gap-3 p-4 text-sm text-emerald-300">
          <CheckCircle2 className="h-5 w-5" />
          Sending under <span className="font-medium">{data?.at_sender_id}</span> — 1 KES per SMS.
        </div>
      )}
    </div>
  );
}
