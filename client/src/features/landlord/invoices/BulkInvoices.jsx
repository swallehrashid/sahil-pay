import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useBulkAddInvoicesMutation } from "./invoiceApiSlice";

const EMPTY_ROW = { tenant_id: "", item: "rent", amount: "" };

// Quick multi-row entry for adding several distinct invoices in one submit.
export default function BulkInvoices({ isOpen, onClose, tenants = [] }) {
  const [bulkAdd, { isLoading }] = useBulkAddInvoicesMutation();
  const [rows, setRows] = useState([{ ...EMPTY_ROW }]);

  const updateRow = (index, key, value) => setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  const addRow = () => setRows((prev) => [...prev, { ...EMPTY_ROW }]);
  const removeRow = (index) => setRows((prev) => prev.filter((_, i) => i !== index));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validRows = rows.filter((r) => r.tenant_id && r.amount);
    if (!validRows.length) {
      toast("Add at least one complete row.", { type: "error" });
      return;
    }
    const todayIso = new Date().toISOString().slice(0, 10);
    const invoices = validRows.map((r) => {
      const tenant = tenants.find((t) => String(t.id) === String(r.tenant_id));
      return {
        tenant_id: r.tenant_id,
        unit_id: tenant?.unit_id,
        property_id: tenant?.property_id,
        issue_date: todayIso,
        line_items: [{ item: r.item, amount: r.amount, unit_price: r.amount, quantity: 1 }],
      };
    });
    try {
      const result = await bulkAdd({ invoices }).unwrap();
      toast(`${result?.created ?? validRows.length} invoices created.`, { type: "success" });
      setRows([{ ...EMPTY_ROW }]);
      onClose();
    } catch {
      toast("Could not create the invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Bulk add invoices" size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-3">
          {rows.map((row, index) => (
            <div key={index} className="grid grid-cols-12 items-end gap-2">
              <div className="col-span-5">
                <Select
                  label={index === 0 ? "Tenant" : undefined}
                  value={row.tenant_id}
                  onChange={(e) => updateRow(index, "tenant_id", e.target.value)}
                  options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
                />
              </div>
              <div className="col-span-3">
                <Input label={index === 0 ? "Item" : undefined} value={row.item} onChange={(e) => updateRow(index, "item", e.target.value)} />
              </div>
              <div className="col-span-3">
                <Input
                  label={index === 0 ? "Amount" : undefined}
                  type="number"
                  step="0.01"
                  value={row.amount}
                  onChange={(e) => updateRow(index, "amount", e.target.value)}
                />
              </div>
              <button
                type="button"
                onClick={() => removeRow(index)}
                className="col-span-1 flex items-center justify-center rounded-lg p-2 text-white/40 transition-colors hover:text-secondary"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
        <Button type="button" variant="subtle" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={addRow}>
          Add row
        </Button>
        <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Create invoices
          </Button>
        </div>
      </form>
    </Modal>
  );
}
