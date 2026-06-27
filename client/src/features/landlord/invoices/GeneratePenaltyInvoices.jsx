import { useState } from "react";
import Modal from "@/components/ui/Modal";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGeneratePenaltyInvoicesMutation } from "./invoiceApiSlice";

// Applies each tenant's/property's configured late-payment penalty to outstanding balances.
// Scope is always every tenant currently in arrears (the backend has no property filter
// for this generator — it operates on balances directly, not property membership).
export default function GeneratePenaltyInvoices({ isOpen, onClose }) {
  const [generate, { isLoading }] = useGeneratePenaltyInvoicesMutation();
  const [form, setForm] = useState({ as_of_date: new Date().toISOString().slice(0, 10) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await generate({ issue_date: form.as_of_date }).unwrap();
      toast(`${result?.created ?? "Penalty"} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not generate penalty invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Generate penalty invoices">
      <form onSubmit={handleSubmit} className="space-y-4">
        <DatePicker label="As of date" value={form.as_of_date} onChange={(e) => setForm((f) => ({ ...f, as_of_date: e.target.value }))} required />
        <p className="text-xs text-white/40">Applies the configured late-payment penalty to every tenant currently in arrears as of this date.</p>
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Generate
          </Button>
        </div>
      </form>
    </Modal>
  );
}
