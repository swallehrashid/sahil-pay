import { useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetRecurringExpensesQuery,
  useCreateRecurringExpenseMutation,
  useUpdateRecurringExpenseMutation,
  useDeleteRecurringExpenseMutation,
} from "./expenseApiSlice";
import { EXPENSE_CATEGORIES } from "@/utils/constants";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import { validateMoneyField } from "@/utils/validators";

function RecurringExpenseForm({ initialValues, properties, units, onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({
    property_id: "",
    unit_id: "",
    amount: "",
    payment_method: "",
    category: "maintenance",
    day_of_month: "1",
    notes: "",
    ...initialValues,
  });
  const [error, setError] = useState("");
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) {
      setError(amountError);
      return;
    }
    setError("");
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Select label="Property" value={form.property_id} onChange={update("property_id")} placeholder="All properties" options={properties.map((p) => ({ value: p.id, label: p.name }))} />
      <Select label="Unit" value={form.unit_id} onChange={update("unit_id")} placeholder="Whole property" options={units.map((u) => ({ value: u.id, label: u.name }))} />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Amount" type="number" step="0.01" value={form.amount} onChange={update("amount")} error={error} required />
        <Select label="Category" value={form.category} onChange={update("category")} options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))} required />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Payment method" value={form.payment_method} onChange={update("payment_method")} />
        <Input label="Day of month" type="number" min="1" max="28" value={form.day_of_month} onChange={update("day_of_month")} />
      </div>
      <Textarea label="Notes" value={form.notes} onChange={update("notes")} />
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save template
        </Button>
      </div>
    </form>
  );
}

// Recurring expense templates — Celery Beat instantiates each into a real expense on the 1st of every month.
export default function RecurringExpenses({ properties = [], units = [] }) {
  const { data, isLoading } = useGetRecurringExpensesQuery();
  const [createTemplate, { isLoading: isCreating }] = useCreateRecurringExpenseMutation();
  const [updateTemplate, { isLoading: isUpdating }] = useUpdateRecurringExpenseMutation();
  const [deleteTemplate] = useDeleteRecurringExpenseMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const templates = toRows(data);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateTemplate({ id: active.id, ...values }).unwrap();
        toast("Recurring expense updated.", { type: "success" });
      } else {
        await createTemplate(values).unwrap();
        toast("Recurring expense created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the recurring expense.", { type: "error" });
    }
  };

  const handleDeactivate = async () => {
    try {
      await deleteTemplate(pendingDelete.id).unwrap();
      toast("Recurring expense deactivated.", { type: "success" });
    } catch {
      toast("Could not deactivate the template.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "category", header: "Category" },
    { key: "scope", header: "Scope", render: (row) => row.unit_name ?? row.property_name ?? "All properties" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "day_of_month", header: "Day of month" },
    {
      key: "is_active",
      header: "Active",
      render: (row) => <Badge color={row.is_active ? "emerald" : "white"}>{row.is_active ? "Active" : "Inactive"}</Badge>,
    },
  ];

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-white/50">Auto-instantiated into an expense on the 1st of each month.</p>
        <Button
          size="sm"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={() => {
            setActive(null);
            setIsFormOpen(true);
          }}
        >
          Add recurring expense
        </Button>
      </div>
      <ResponsiveTable
        columns={columns}
        rows={templates}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              {
                label: "Edit",
                icon: <Pencil className="h-4 w-4" />,
                onClick: () => {
                  setActive(row);
                  setIsFormOpen(true);
                },
              },
              { label: "Deactivate", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />
      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit recurring expense" : "Add recurring expense"}>
        <RecurringExpenseForm
          initialValues={active}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>
      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDeactivate}
        title="Deactivate template?"
        description="This recurring expense will stop generating new expenses."
      />
    </div>
  );
}
