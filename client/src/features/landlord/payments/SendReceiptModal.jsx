import { useState } from "react";
import { Mail, MessageSquare, Bell, Send } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useSendPaymentReceiptMutation } from "./paymentApiSlice";

/**
 * Choose HOW the receipt goes, then send it.
 *
 * "Send receipt" used to fire the moment it was clicked, by email only, with
 * no say in the matter. An SMS costs the account credit and not every tenant
 * reads email, so the sender picks the channels — email, SMS, in-app, any mix
 * — and nothing leaves until they press Send.
 */
const CHANNELS = [
  { value: "email", label: "Email", icon: Mail, hint: "PDF receipt attached" },
  { value: "sms", label: "SMS", icon: MessageSquare, hint: "Summary + receipt link · uses SMS credit" },
  { value: "in_app", label: "In-app", icon: Bell, hint: "Shows in the tenant portal" },
];

export default function SendReceiptModal({ payment, onClose }) {
  const [channels, setChannels] = useState([]);
  const [send, { isLoading }] = useSendPaymentReceiptMutation();

  // A fresh choice for every payment — nothing carried over from the last one.
  const [forPayment, setForPayment] = useState(payment?.id);
  if (payment?.id !== forPayment) {
    setForPayment(payment?.id);
    setChannels([]);
  }

  const toggle = (value) =>
    setChannels((prev) => (prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]));

  const handleSend = async () => {
    try {
      const res = await send({ id: payment.id, channels }).unwrap();
      toast(res?.message || "Receipt sent.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || err?.data?.message || "The receipt could not be sent.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={Boolean(payment)} onClose={onClose} title="Send receipt">
      {payment && (
        <div className="space-y-5" data-testid="send-receipt-modal">
          <div className="rounded-xl bg-white/5 p-4 text-sm">
            <p className="text-white">
              {payment.tenant_name || "Tenant"} · <span className="font-semibold">{formatCurrency(payment.amount)}</span>
            </p>
            <p className="mt-0.5 text-xs text-white/50">
              Receipt {payment.payment_ref}{payment.mpesa_reference ? ` · ${payment.mpesa_reference}` : ""}
            </p>
          </div>

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-white/80">Send it by</legend>
            <div className="space-y-2">
              {CHANNELS.map(({ value, label, icon: Icon, hint }) => (
                <div key={value} className="flex items-center justify-between rounded-lg border border-white/10 px-3 py-2.5">
                  <Checkbox
                    name={`receipt_channel_${value}`}
                    label={<span className="inline-flex items-center gap-2"><Icon className="h-4 w-4 text-white/50" />{label}</span>}
                    checked={channels.includes(value)}
                    onChange={() => toggle(value)}
                  />
                  <span className="text-xs text-white/40">{hint}</span>
                </div>
              ))}
            </div>
            {channels.length === 0 && (
              <p className="mt-2 text-xs text-amber-300/90">Tick at least one channel.</p>
            )}
          </fieldset>

          <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button
              data-testid="send-receipt-confirm"
              leftIcon={<Send className="h-4 w-4" />}
              disabled={channels.length === 0}
              isLoading={isLoading}
              onClick={handleSend}
            >
              Send receipt
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
