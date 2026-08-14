import { useEffect, useState } from "react";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import {
  useClearPaymentEtimsMutation,
  useSetPaymentEtimsMutation,
  useSetPayoutEtimsMutation,
} from "./etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §4.1 — recording one eTIMS number.
//
// Reached from a row action on a payment or an owner payout. Deliberately
// small: the number, the date it was issued, and optionally the KRA
// verification link if the user pasted one. Nothing computed, nothing
// validated against KRA — SahilPay only stores what the user typed.
//
// Mobile-first: fields stack in one column and the actions are full-width
// stacked buttons until sm, because this gets used one-handed.
export default function EtimsEntryModal({ record, kind = "payment", onClose }) {
  const [setPayment, { isLoading: savingPayment }] = useSetPaymentEtimsMutation();
  const [setPayout, { isLoading: savingPayout }] = useSetPayoutEtimsMutation();
  const [clearPayment, { isLoading: clearing }] = useClearPaymentEtimsMutation();

  const [number, setNumber] = useState("");
  const [issuedAt, setIssuedAt] = useState("");
  const [qrUrl, setQrUrl] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!record) return;
    setNumber(record.etims_invoice_number ?? "");
    setIssuedAt(
      record.etims_issued_at?.slice(0, 10) ??
        new Date().toISOString().slice(0, 10)
    );
    setQrUrl(record.etims_qr_url ?? "");
    setError(null);
  }, [record]);

  if (!record) return null;

  const isSaving = savingPayment || savingPayout;
  const label = record.payment_ref || `#${record.id}`;

  const handleSave = async () => {
    setError(null);
    const body = {
      etims_invoice_number: number,
      etims_issued_at: issuedAt || undefined,
      etims_qr_url: qrUrl || undefined,
    };
    try {
      if (kind === "payout") {
        await setPayout({ payoutId: record.id, ...body }).unwrap();
      } else {
        await setPayment({ paymentId: record.id, ...body }).unwrap();
      }
      toast("eTIMS invoice recorded.", { type: "success" });
      onClose?.();
    } catch (err) {
      // A duplicate names the record that already holds the number, so show it
      // inline against the field rather than as a disappearing toast.
      setError(err?.data?.error || "Could not save that eTIMS invoice number.");
    }
  };

  const handleRemove = async () => {
    try {
      await clearPayment(record.id).unwrap();
      toast("Removed.", { type: "success" });
      onClose?.();
    } catch (err) {
      setError(err?.data?.error || "Could not remove it.");
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Record eTIMS invoice — ${label}`} size="md">
      <div className="space-y-4">
        <p className="text-sm text-white/50">
          Issue the invoice at KRA first (eCitizen, *222#, or the eTIMS app), then
          paste the number it gave you here.
        </p>

        <Input
          label="eTIMS invoice number"
          value={number}
          placeholder="Paste the number from KRA"
          onChange={(e) => setNumber(e.target.value)}
          error={error}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            type="date"
            label="Issued on"
            value={issuedAt}
            onChange={(e) => setIssuedAt(e.target.value)}
          />
          <Input
            label="Verification link (optional)"
            value={qrUrl}
            placeholder="https://…"
            onChange={(e) => setQrUrl(e.target.value)}
            hint="Renders as a QR code on the receipt."
          />
        </div>

        <div className="flex flex-col gap-2 pt-2 sm:flex-row sm:justify-end">
          {kind === "payment" && record.etims_invoice_number && (
            <Button
              type="button"
              variant="ghost"
              onClick={handleRemove}
              isLoading={clearing}
              className="sm:mr-auto"
            >
              Remove
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSave} isLoading={isSaving}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}
