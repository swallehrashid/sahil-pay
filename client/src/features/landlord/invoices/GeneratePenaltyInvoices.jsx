import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGeneratePenaltyInvoicesMutation } from "./invoiceApiSlice";

// Applies each tenant's/property's configured late-payment penalty to outstanding balances.
export default function GeneratePenaltyInvoices({ isOpen, onClose, properties = [] }) {
  const [generate, { isLoading }] = useGeneratePenaltyInvoicesMutation();
  const [form, setForm] = useState({ property_id: "", as_of_date: new Date().toISOString().slice(0, 10) });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await generate(form).unwrap();
      toast(`${result?.created_count ?? "Penalty"} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not generate penalty invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Generate penalty invoices">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Select
          label="Property"
          placeholder="All properties"
          value={form.property_id}
          onChange={(e) => setForm((f) => ({ ...f, property_id: e.target.value }))}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <DatePicker label="As of date" value={form.as_of_date} onChange={(e) => setForm((f) => ({ ...f, as_of_date: e.target.value }))} required />
        <p className="text-xs text-white/40">Applies the configured late-payment penalty to tenants with outstanding balances as of this date.</p>
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
