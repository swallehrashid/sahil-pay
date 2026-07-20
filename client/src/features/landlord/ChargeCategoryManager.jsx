import { useState } from "react";
import { Plus, Pencil, Power, Lock, Trash2 } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetChargeCategoriesQuery,
  useCreateChargeCategoryMutation,
  useUpdateChargeCategoryMutation,
  useDeleteChargeCategoryMutation,
} from "./chargeCategoryApiSlice";

// Reusable catalogue manager for BOTH the Utilities page (kind="utility") and the
// Invoices page (kind="invoice"). Every category implicitly owns three subcategories
// (deposit / balance / current) shown as read-only chips. Defaults are protected —
// deactivatable, never deletable.
const EMPTY = (kind) => ({
  name: "",
  kind,
  description: "",
  is_metered: false,
  default_rate: "",
  auto_bill_monthly: false,
});

export default function ChargeCategoryManager({ isOpen, onClose, kind }) {
  const isUtility = kind === "utility";
  const { data } = useGetChargeCategoriesQuery({ kind, include_inactive: 1 }, { skip: !isOpen });
  const [createCat, { isLoading: isCreating }] = useCreateChargeCategoryMutation();
  const [updateCat, { isLoading: isUpdating }] = useUpdateChargeCategoryMutation();
  const [deleteCat] = useDeleteChargeCategoryMutation();

  const [editing, setEditing] = useState(null); // null | new | existing row
  const categories = data?.categories ?? [];

  const startCreate = () => setEditing(EMPTY(kind));

  const save = async () => {
    if (!editing.name.trim()) {
      toast("Name is required.", { type: "error" });
      return;
    }
    if (editing.is_metered && editing.auto_bill_monthly) {
      toast("A metered category can't auto-bill monthly.", { type: "error" });
      return;
    }
    const body = {
      name: editing.name.trim(),
      kind,
      description: editing.description || null,
      is_metered: isUtility ? editing.is_metered : false,
      default_rate: editing.default_rate === "" ? null : Number(editing.default_rate),
      auto_bill_monthly: editing.auto_bill_monthly,
    };
    try {
      if (editing.id) await updateCat({ id: editing.id, ...body }).unwrap();
      else await createCat(body).unwrap();
      toast("Category saved.", { type: "success" });
      setEditing(null);
    } catch (err) {
      toast(err?.data?.error || "Could not save category.", { type: "error" });
    }
  };

  const toggleActive = async (row) => {
    try {
      await updateCat({ id: row.id, is_active: !row.is_active }).unwrap();
      toast(row.is_active ? "Category deactivated." : "Category activated.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not update category.", { type: "error" });
    }
  };

  const remove = async (row) => {
    try {
      await deleteCat(row.id).unwrap();
      toast("Category deleted.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not delete this category.", { type: "error" });
    }
  };

  const title = isUtility ? "Utility categories" : "Invoice categories";

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} size="lg">
      {editing ? (
        <div className="space-y-4">
          <Input
            label="Name"
            value={editing.name}
            onChange={(e) => setEditing((s) => ({ ...s, name: e.target.value }))}
            placeholder={isUtility ? "e.g. Water, Garbage" : "e.g. Rent, Parking"}
            disabled={editing.is_default}
            required
          />
          <Input
            label="Description"
            value={editing.description || ""}
            onChange={(e) => setEditing((s) => ({ ...s, description: e.target.value }))}
            hint="Optional"
          />
          <Input
            label="Default rate"
            type="number"
            step="0.01"
            value={editing.default_rate ?? ""}
            onChange={(e) => setEditing((s) => ({ ...s, default_rate: e.target.value }))}
            hint={isUtility ? "Per-unit rate (metered) or flat amount" : "Amount billed each month when auto-billed"}
          />
          {isUtility && (
            <Checkbox
              name="is_metered"
              label="Metered (billed on meter readings)"
              checked={editing.is_metered}
              onChange={(e) =>
                setEditing((s) => ({ ...s, is_metered: e.target.checked, auto_bill_monthly: e.target.checked ? false : s.auto_bill_monthly }))
              }
            />
          )}
          <div>
            <Checkbox
              name="auto_bill_monthly"
              label="Bill automatically every month"
              checked={editing.auto_bill_monthly}
              disabled={editing.is_metered}
              onChange={(e) => setEditing((s) => ({ ...s, auto_bill_monthly: e.target.checked }))}
            />
            {editing.is_metered && (
              <p className="mt-1 pl-1 text-xs text-white/40">
                Metered categories can't auto-bill — the amount depends on the reading.
              </p>
            )}
          </div>

          <div className="rounded-xl bg-white/5 p-3">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-white/40">
              Auto-created subcategories
            </p>
            <div className="flex flex-wrap gap-2">
              {["Deposit", "Balance", "This month"].map((s) => (
                <Badge key={s} color="white">
                  {editing.name?.trim() || "…"} {s === "This month" ? "" : s}
                  {s === "This month" ? " (current)" : ""}
                </Badge>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={save} isLoading={isCreating || isUpdating}>Save category</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex justify-end">
            <Button size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={startCreate}>
              New category
            </Button>
          </div>
          <div className="space-y-2">
            {categories.length === 0 && (
              <p className="py-6 text-center text-sm text-white/40">No categories yet.</p>
            )}
            {categories.map((cat) => (
              <div
                key={cat.id}
                className={"rounded-xl bg-white/5 p-3 " + (cat.is_active ? "" : "opacity-50")}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-white/90">{cat.name}</span>
                      {cat.is_default && (
                        <Badge color="white"><Lock className="mr-1 inline h-3 w-3" />Default</Badge>
                      )}
                      {cat.is_metered && <Badge color="secondary">Metered</Badge>}
                      {cat.auto_bill_monthly && <Badge color="emerald">Auto-bills monthly</Badge>}
                      {!cat.is_active && <Badge color="white">Inactive</Badge>}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-white/40">
                      {cat.subcategories?.map((s) => (
                        <span key={s.subcategory} className="rounded bg-white/5 px-1.5 py-0.5">{s.label}</span>
                      ))}
                    </div>
                    {cat.description && <p className="mt-1 text-xs text-white/40">{cat.description}</p>}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      title="Edit"
                      onClick={() => setEditing({ ...cat, default_rate: cat.default_rate ?? "" })}
                      className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      title={cat.is_active ? "Deactivate" : "Activate"}
                      onClick={() => toggleActive(cat)}
                      className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-white"
                    >
                      <Power className="h-4 w-4" />
                    </button>
                    {!cat.is_default && (
                      <button
                        type="button"
                        title="Delete"
                        onClick={() => remove(cat)}
                        className="rounded-lg p-1.5 text-white/50 hover:bg-white/10 hover:text-secondary-300"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}
