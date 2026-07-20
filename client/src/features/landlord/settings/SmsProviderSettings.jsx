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

// §9.3 — connect a custom SMS sender ID so messages go out under the
// landlord's own brand (flat rate per SMS). Without a sender ID, Sahil Pay's
// shared sender ID is used and messages are billed by length.
export default function SmsProviderSettings() {
  const { data, isLoading } = useGetSmsProviderQuery();
  const [update, { isLoading: isSaving }] = useUpdateSmsProviderMutation();
  const [connect, { isLoading: isConnecting }] = useConnectSmsProviderMutation();
  const [disconnect, { isLoading: isDisconnecting }] = useDisconnectSmsProviderMutation();

  const [form, setForm] = useState({ sms_api_key: "", sms_sender_id: "" });
  const [prev, setPrev] = useState();
  if (data && data !== prev) {
    setPrev(data);
    // Never hydrate the secret key back into the field; keep the sender ID.
    setForm({ sms_api_key: "", sms_sender_id: data.sms_sender_id ?? "" });
  }

  if (isLoading) return <SkeletonForm fields={3} />;

  const connected = Boolean(data?.sms_connected);
  const price = data?.price_per_sms;
  const currency = data?.currency ?? "KES";
  const priceLabel = price != null ? `${price} ${currency} / SMS` : "—";

  const handleSave = async (e) => {
    e.preventDefault();
    // Only send the api key when the user actually typed a new one.
    const body = { sms_sender_id: form.sms_sender_id };
    if (form.sms_api_key.trim()) body.sms_api_key = form.sms_api_key.trim();
    try {
      await update(body).unwrap();
      toast("SMS provider details saved.", { type: "success" });
      setForm((f) => ({ ...f, sms_api_key: "" }));
    } catch {
      toast("Could not save the details.", { type: "error" });
    }
  };

  const handleConnect = async () => {
    try {
      await connect().unwrap();
      toast("Custom sender ID connected.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error ?? "Could not connect. Save your details first.", { type: "error" });
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnect().unwrap();
      toast("Disconnected. Messages now use Sahil Pay's shared sender ID.", { type: "success" });
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
        <SummaryCard label="Sender ID" value={connected ? (data?.sms_sender_id ?? "—") : "Sahil Pay (shared)"} accent="third" />
        <SummaryCard label="Billing" value={connected ? priceLabel : "By length"} accent="third" />
      </div>

      <div className="glass space-y-2 p-6 text-sm text-white/60">
        <p className="text-white/80 font-medium">How it works</p>
        <p>
          Connect your own registered sender ID and API key to send SMS under your own brand —
          billed a flat <span className="text-white">{priceLabel}</span>. Sahil Pay delivers the messages for you.
        </p>
        <p>
          No sender ID? You can still send using Sahil Pay's shared sender ID — those messages are
          <span className="text-white"> billed by length</span> (longer messages use more segments and cost more).
        </p>
      </div>

      <form onSubmit={handleSave} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Custom SMS sender credentials</h3>
        <Input
          label="API key"
          type="password"
          placeholder={data?.sms_api_key_set ? `Saved (${data.sms_api_key_masked})` : "Paste your SMS provider API key"}
          value={form.sms_api_key}
          onChange={(e) => setForm((f) => ({ ...f, sms_api_key: e.target.value }))}
          hint={data?.sms_api_key_set ? "Leave blank to keep the saved key." : undefined}
        />
        <Input
          label="Sender ID"
          placeholder="e.g. YOURBRAND"
          value={form.sms_sender_id}
          onChange={(e) => setForm((f) => ({ ...f, sms_sender_id: e.target.value }))}
        />
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
          Sending under <span className="font-medium">{data?.sms_sender_id}</span> — {priceLabel}.
        </div>
      )}
    </div>
  );
}
