import { useState } from "react";
import { MessageSquare, Link2, Unlink, CheckCircle2, KeyRound, Send } from "lucide-react";
import clsx from "clsx";
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
  useTestSmsProviderMutation,
} from "./smsProviderApiSlice";

/**
 * How this account's SMS go out — three ways (server/services/sms_provider_service.py):
 *
 *   Shared        Sahil Pay's sender name, billed from your Sahil Pay SMS balance.
 *   Branded       your approved name on Sahil Pay's account, same billing.
 *   Third party   YOUR OWN FluxSMS account: your API key and sender ID. Sahil Pay
 *                 sends through it and your provider bills you directly — nothing
 *                 comes off your Sahil Pay balance. The key is checked live against
 *                 FluxSMS before anything is connected, and stored encrypted.
 */
const MODES = [
  { key: "branded", title: "Sender name on Sahil Pay", body: "Sahil Pay registered your name for you. Billed from your Sahil Pay SMS balance." },
  { key: "own_account", title: "My own FluxSMS account (third party)", body: "You have your own FluxSMS API key and approved sender ID. Your provider bills you." },
];

export default function SmsProviderSettings() {
  const { data, isLoading } = useGetSmsProviderQuery();
  const [update, { isLoading: isSaving }] = useUpdateSmsProviderMutation();
  const [connect, { isLoading: isConnecting }] = useConnectSmsProviderMutation();
  const [disconnect, { isLoading: isDisconnecting }] = useDisconnectSmsProviderMutation();
  const [sendTest, { isLoading: isTesting }] = useTestSmsProviderMutation();

  const [form, setForm] = useState({ sms_api_key: "", sms_sender_id: "" });
  const [mode, setMode] = useState(null);
  const [testPhone, setTestPhone] = useState("");
  const [lastCheck, setLastCheck] = useState(null);
  const [prev, setPrev] = useState();
  if (data && data !== prev) {
    setPrev(data);
    // Never hydrate the secret key back into the field; keep the sender ID.
    setForm({ sms_api_key: "", sms_sender_id: data.sms_sender_id ?? "" });
    if (mode === null) setMode(data.sms_api_key_set ? "own_account" : "branded");
  }

  if (isLoading) return <SkeletonForm fields={3} />;

  const connected = Boolean(data?.sms_connected);
  const provider = data?.provider;
  const price = data?.price_per_sms;
  const currency = data?.currency ?? "KES";
  const priceLabel = price != null ? `${price} ${currency} / SMS` : "—";
  const ownAccount = mode === "own_account";

  const save = async () => {
    const body = { sms_sender_id: form.sms_sender_id };
    if (ownAccount && form.sms_api_key.trim()) body.sms_api_key = form.sms_api_key.trim();
    if (!ownAccount && data?.sms_api_key_set) body.sms_api_key = "";   // switching back clears the stored key
    await update(body).unwrap();
  };

  const handleSave = async (e) => {
    e.preventDefault();
    try {
      await save();
      toast("Saved. Press Connect to check and switch it on.", { type: "success" });
      setForm((f) => ({ ...f, sms_api_key: "" }));
    } catch (err) {
      toast(err?.data?.error ?? "Could not save the details.", { type: "error" });
    }
  };

  const handleConnect = async () => {
    try {
      if (form.sms_sender_id !== (data?.sms_sender_id ?? "") || form.sms_api_key.trim()) await save();
      const res = await connect().unwrap();
      setLastCheck({ ok: true, text: res?.message });
      toast(res?.message ?? "Connected.", { type: "success", duration: 7000 });
      setForm((f) => ({ ...f, sms_api_key: "" }));
    } catch (err) {
      const text = err?.data?.error ?? "Could not connect.";
      setLastCheck({ ok: false, text });
      toast(text, { type: "error", duration: 8000 });
    }
  };

  const handleDisconnect = async () => {
    try {
      await disconnect().unwrap();
      setLastCheck(null);
      toast("Disconnected. Messages now use Sahil Pay's shared sender ID.", { type: "success" });
    } catch {
      toast("Could not disconnect.", { type: "error" });
    }
  };

  const handleTest = async () => {
    try {
      const res = await sendTest({ phone: testPhone }).unwrap();
      toast(res?.message ?? "Test SMS sent.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error ?? "The test SMS was not sent.", { type: "error", duration: 8000 });
    }
  };

  return (
    <div className="space-y-6" data-testid="sms-provider-settings">
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
        <SummaryCard
          label="Connection"
          value={connected ? <Badge color="emerald">Connected</Badge> : <Badge color="secondary">Not connected</Badge>}
          icon={<MessageSquare className="h-5 w-5" />}
        />
        <SummaryCard label="Sending as" value={connected ? (data?.sms_sender_id ?? "—") : "Sahil Pay (shared)"} accent="third" />
        <SummaryCard
          label="Billed to"
          value={provider?.mode === "own_account" ? "Your FluxSMS account" : priceLabel}
          accent="third"
        />
      </div>

      <div className="glass space-y-3 p-6">
        <p className="text-sm font-medium text-white/80">How do you want to send?</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              data-testid={`sms-mode-${m.key}`}
              onClick={() => setMode(m.key)}
              className={clsx(
                "rounded-xl border p-4 text-left transition-all",
                mode === m.key ? "border-secondary/60 bg-secondary/10 ring-1 ring-secondary/40" : "border-white/10 bg-white/[0.03] hover:border-white/25"
              )}
            >
              <span className="block text-sm text-white">{m.title}</span>
              <span className="mt-1 block text-xs leading-relaxed text-white/50">{m.body}</span>
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSave} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">
          {ownAccount ? "Your FluxSMS account" : "Your own sender name"}
        </h3>
        <p className="-mt-1 text-sm text-white/50">
          {ownAccount
            ? "Paste the API key from your FluxSMS dashboard and the sender ID approved on it. Connect checks the key with FluxSMS straight away."
            : "Sahil Pay registers the name with the networks on your behalf. Ask us to arrange it, then enter the approved name below."}
        </p>
        <Input
          label={ownAccount ? "Sender ID" : "Sender name"}
          name="sms_sender_id"
          placeholder="e.g. YOURBRAND"
          value={form.sms_sender_id}
          onChange={(e) => setForm((f) => ({ ...f, sms_sender_id: e.target.value }))}
          hint="Up to 11 characters, letters and numbers"
        />
        {ownAccount && (
          <Input
            label="FluxSMS API key"
            name="sms_api_key"
            type="password"
            autoComplete="off"
            placeholder={data?.sms_api_key_set ? `Saved (${data.sms_api_key_masked}) — paste a new key to replace it` : "Paste your API key"}
            value={form.sms_api_key}
            onChange={(e) => setForm((f) => ({ ...f, sms_api_key: e.target.value }))}
            hint="Stored encrypted. Never shown again after saving."
          />
        )}
        {lastCheck && (
          <p className={clsx("flex items-start gap-2 rounded-lg p-3 text-sm",
            lastCheck.ok ? "bg-emerald-400/10 text-emerald-200" : "bg-red-400/10 text-red-200")} data-testid="sms-connect-result">
            <KeyRound className="mt-0.5 h-4 w-4 flex-shrink-0" />{lastCheck.text}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-3">
          <Button type="submit" variant="ghost" isLoading={isSaving}>Save details</Button>
          {connected ? (
            <Button type="button" variant="danger" leftIcon={<Unlink className="h-4 w-4" />} isLoading={isDisconnecting} onClick={handleDisconnect}>
              Disconnect
            </Button>
          ) : (
            <Button type="button" data-testid="sms-connect" leftIcon={<Link2 className="h-4 w-4" />} isLoading={isConnecting} onClick={handleConnect}>
              {ownAccount ? "Check key & connect" : "Connect"}
            </Button>
          )}
        </div>
      </form>

      {connected && (
        <div className="glass space-y-4 p-6">
          <div className="flex items-center gap-3 text-sm text-emerald-300">
            <CheckCircle2 className="h-5 w-5" />
            Sending under <span className="font-medium">{data?.sms_sender_id}</span> — {provider?.label}.
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-64">
              <Input label="Send a test SMS to" name="test_phone" placeholder="07XX XXX XXX" value={testPhone}
                     onChange={(e) => setTestPhone(e.target.value)} />
            </div>
            <Button variant="ghost" leftIcon={<Send className="h-4 w-4" />} isLoading={isTesting} disabled={!testPhone} onClick={handleTest}>
              Send test
            </Button>
          </div>
          <p className="text-xs text-white/40">
            The only way to prove the sender ID itself is approved on the networks. Billed like any other message.
          </p>
        </div>
      )}
    </div>
  );
}
