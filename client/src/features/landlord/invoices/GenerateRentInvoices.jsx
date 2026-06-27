import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGenerateRentInvoicesMutation } from "./invoiceApiSlice";

// Generates a rent invoice for every active tenant covered by the selected scope and month.
export default function GenerateRentInvoices({ isOpen, onClose, properties = [] }) {
  const [generate, { isLoading }] = useGenerateRentInvoicesMutation();
  const [form, setForm] = useState({ property_id: "", billing_month: new Date().toISOString().slice(0, 7), due_date: "" });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await generate({
        property_ids: form.property_id ? [Number(form.property_id)] : undefined,
        issue_date: `${form.billing_month}-01`,
        due_date: form.due_date || undefined,
      }).unwrap();
      toast(`${result?.created ?? "Rent"} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not generate rent invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Generate rent invoices">
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
        <p className="text-xs text-white/40">A rent invoice is created for every active tenant covered by this selection.</p>
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
