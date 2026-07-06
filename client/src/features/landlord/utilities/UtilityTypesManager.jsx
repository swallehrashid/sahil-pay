import { useState } from "react";
import { Plus, Pencil, Power } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetUtilityTypesQuery,
  useCreateUtilityTypeMutation,
  useUpdateUtilityTypeMutation,
  useDeleteUtilityTypeMutation,
} from "./utilityApiSlice";

// #6 — landlords define/manage their own utilities, each tagged into one of the three
// buckets that drive tracking + auto-allocation: deposit / balance / current_utility.
const CATEGORIES = [
  { value: "current_utility", label: "Current utility (this month)" },
  { value: "balance", label: "Balance (arrears carried forward)" },
  { value: "deposit", label: "Deposit" },
];
const CAT_LABEL = Object.fromEntries(CATEGORIES.map((c) => [c.value, c.label]));

const EMPTY = { name: "", category: "current_utility", is_metered: false, default_rate: "" };

export default function UtilityTypesManager({ isOpen, onClose }) {
  const { data } = useGetUtilityTypesQuery({ include_inactive: 1 }, { skip: !isOpen });
  const [createType, { isLoading: isCreating }] = useCreateUtilityTypeMutation();
  const [updateType, { isLoading: isUpdating }] = useUpdateUtilityTypeMutation();
  const [deleteType] = useDeleteUtilityTypeMutation();

  const [editing, setEditing] = useState(null); // null | EMPTY | existing row
  const types = data?.utility_types ?? [];

  const save = async () => {
    if (!editing.name.trim()) {
      toast("Name is required.", { type: "error" });
      return;
    }
    const body = {
      name: editing.name.trim(),
      category: editing.category,
      is_metered: editing.is_metered,
      default_rate: editing.default_rate === "" ? null : Number(editing.default_rate),
    };
    try {
      if (editing.id) await updateType({ id: editing.id, ...body }).unwrap();
      else await createType(body).unwrap();
      toast("Utility saved.", { type: "success" });
      setEditing(null);
    } catch (err) {
      toast(err?.data?.error || "Could not save utility.", { type: "error" });
    }
  };

  const toggleActive = async (row) => {
    try {
      if (row.is_active) await deleteType(row.id).unwrap();
      else await updateType({ id: row.id, is_active: true }).unwrap();
    } catch {
      toast("Could not update utility.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Utility types">
      <div className="space-y-4">
        <p className="text-sm text-white/50">
          Define the utilities, deposits and balances you charge. Each is tracked and
          auto-allocated individually.
        </p>

        <div className="space-y-2">
          {types.map((t) => (
            <div key={t.id} className="flex items-center gap-3 rounded-xl bg-white/5 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm text-white/90">{t.name}</span>
                  {!t.is_active && <Badge color="white">inactive</Badge>}
                  {t.is_metered && <Badge color="third">metered</Badge>}
                </div>
                <span className="text-xs text-white/40">{CAT_LABEL[t.category] || t.category}</span>
              </div>
              <button
                type="button"
                className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white"
                onClick={() => setEditing({ ...t, default_rate: t.default_rate ?? "" })}
                title="Edit"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white"
                onClick={() => toggleActive(t)}
                title={t.is_active ? "Deactivate" : "Reactivate"}
              >
                <Power className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>

        {editing ? (
          <div className="space-y-3 rounded-xl border border-white/10 p-3">
            <Input
              label="Name"
              value={editing.name}
              onChange={(e) => setEditing((s) => ({ ...s, name: e.target.value }))}
              required
            />
            <Select
              label="Category"
              value={editing.category}
              onChange={(e) => setEditing((s) => ({ ...s, category: e.target.value }))}
              options={CATEGORIES}
            />
            <Checkbox
              label="Metered (takes meter readings)"
              checked={editing.is_metered}
              onChange={(e) => setEditing((s) => ({ ...s, is_metered: e.target.checked }))}
            />
            {editing.is_metered && (
              <Input
                label="Default rate per unit consumed (optional)"
                type="number"
                step="0.01"
                value={editing.default_rate}
                onChange={(e) => setEditing((s) => ({ ...s, default_rate: e.target.value }))}
              />
            )}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button onClick={save} isLoading={isCreating || isUpdating}>
                Save
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="ghost" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setEditing({ ...EMPTY })}>
            Add utility type
          </Button>
        )}
      </div>
    </Modal>
  );
}
