import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import Textarea from "@/components/ui/Textarea";
import { toast } from "@/components/ui/Toast";
import { useGetSmsProviderQuery } from "../settings/smsProviderApiSlice";
import { useSendTenantReminderMutation } from "../tenants/tenantApiSlice";

// #4 — before any reminder goes out, the landlord confirms WHICH channels to use
// (SMS / Email / In-app / WhatsApp). Channels are pre-checked from the settings default
// but always editable, and only the ticked ones are sent.
const CHANNELS = [
  { value: "sms", label: "SMS" },
  { value: "email", label: "Email" },
  { value: "in_app", label: "In-app notification" },
  { value: "whatsapp", label: "WhatsApp" },
];

export default function SendReminderModal({ tenant, onClose, defaultChannels }) {
  const isOpen = Boolean(tenant);
  const { data: smsProvider } = useGetSmsProviderQuery(undefined, { skip: !isOpen });
  const [sendReminder, { isLoading }] = useSendTenantReminderMutation();

  const [channels, setChannels] = useState(defaultChannels ?? ["sms"]);
  const [message, setMessage] = useState("");

  // Reset each time the modal opens for a new tenant.
  useEffect(() => {
    if (tenant) {
      setChannels(defaultChannels ?? ["sms"]);
      setMessage("");
    }
  }, [tenant, defaultChannels]);

  const toggle = (value) =>
    setChannels((prev) => (prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]));

  const send = async () => {
    if (!channels.length) {
      toast("Pick at least one channel.", { type: "error" });
      return;
    }
    try {
      const res = await sendReminder({ id: tenant.id, channels, message: message.trim() || undefined }).unwrap();
      toast(res?.message || "Reminder sent.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not send the reminder.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Send balance reminder">
      {tenant && (
        <div className="space-y-4">
          <p className="text-sm text-white/60">
            To <span className="text-white/90">{tenant.first_name} {tenant.last_name}</span>. Choose how to send it.
          </p>

          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-white/40">Channels</p>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {CHANNELS.map((ch) => (
                <Checkbox
                  key={ch.value}
                  name={`ch_${ch.value}`}
                  label={ch.label}
                  checked={channels.includes(ch.value)}
                  onChange={() => toggle(ch.value)}
                />
              ))}
            </div>
            {channels.includes("sms") && smsProvider && (
              <p className="mt-2 text-xs text-white/40">
                SMS balance: {smsProvider.sms_balance ?? 0} credit(s) · cost depends on message length (words → credits)
              </p>
            )}
          </div>

          <Textarea
            label="Message (optional)"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Leave blank to use the default balance-reminder message."
          />

          <div className="flex justify-end gap-3 pt-1">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={send} isLoading={isLoading}>
              Send reminder
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
