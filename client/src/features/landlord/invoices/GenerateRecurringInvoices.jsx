import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGenerateRecurringInvoicesMutation } from "./invoiceApiSlice";

// Generates an invoice line for every active recurring_bills row attached to the selected scope.
export default function GenerateRecurringInvoices({ isOpen, onClose, properties = [] }) {
  const [generate, { isLoading }] = useGenerateRecurringInvoicesMutation();
  const [form, setForm] = useState({ property_id: "", billing_month: new Date().toISOString().slice(0, 7), due_date: "" });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await generate({
        property_ids: form.property_id ? [Number(form.property_id)] : undefined,
        issue_date: `${form.billing_month}-01`,
      }).unwrap();
      toast(`${result?.created ?? "Recurring bill"} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not generate recurring bill invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Generate recurring bill invoices">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Select
          label="Property"
          placeholder="All properties"
          value={form.property_id}
          onChange={(e) => setForm((f) => ({ ...f, property_id: e.target.value }))}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Input
          label="Billing month"
          type="month"
          value={form.billing_month}
          onChange={(e) => setForm((f) => ({ ...f, billing_month: e.target.value }))}
          required
        />
        <DatePicker label="Due date" value={form.due_date} onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))} />
        <p className="text-xs text-white/40">
          Generates an invoice for every active recurring bill (e.g. a fixed service charge) attached to the selected scope.
        </p>
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
