import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useCreateExpenseFromMaintenanceMutation } from "./maintenanceApiSlice";
import { EXPENSE_CATEGORIES } from "@/utils/constants";
import { validateMoneyField } from "@/utils/validators";

// "Create expense" shortcut — pre-fills the expense form from a maintenance request and
// links the resulting expense back via maintenance_requests.expense_id.
export default function CreateExpenseFromMaintenance({ request, onClose }) {
  const [createExpense, { isLoading }] = useCreateExpenseFromMaintenanceMutation();
  const [form, setForm] = useState({ amount: "", category: "maintenance", expense_date: new Date().toISOString().slice(0, 10) });
  const [error, setError] = useState("");

  if (!request) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) {
      setError(amountError);
      return;
    }
    setError("");
    try {
      await createExpense({ id: request.id, ...form }).unwrap();
      toast("Expense created from maintenance request.", { type: "success" });
      onClose();
    } catch {
      toast("Could not create the expense.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title="Create expense">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-white/50">
          Pre-filled from "{request.summary}" — {request.property_name} / {request.unit_name}.
        </p>
        <Input label="Amount" type="number" step="0.01" value={form.amount} onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))} error={error} required />
        <Select
          label="Category"
          value={form.category}
          onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
          options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))}
          required
        />
        <DatePicker label="Expense date" value={form.expense_date} onChange={(e) => setForm((f) => ({ ...f, expense_date: e.target.value }))} required />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Create expense
          </Button>
        </div>
      </form>
    </Modal>
  );
}
