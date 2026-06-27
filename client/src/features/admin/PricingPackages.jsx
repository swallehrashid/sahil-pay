import { useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Select from "@/components/ui/Select";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import {
  useGetPackagesQuery,
  useCreatePackageMutation,
  useUpdatePackageMutation,
  useDeletePackageMutation,
  useUpdateLandlordPerUnitPriceMutation,
} from "./adminPricingApiSlice";
import { useGetAdminLandlordsQuery } from "./adminApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import { isRequired } from "@/utils/validators";

function PackageForm({ initialValues, onSubmit, onCancel, isSubmitting }) {
  const [form, setForm] = useState({ name: "", min_units: "", max_units: "", price_per_unit: "", flat_price: "", ...initialValues });
  const [error, setError] = useState("");
  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isRequired(form.name) || !isRequired(form.min_units)) {
      setError("Name and minimum units are required");
      return;
    }
    setError("");
    onSubmit(form);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input label="Package name" value={form.name} onChange={update("name")} error={error} required />
      <div className="grid grid-cols-2 gap-4">
        <Input label="Min units" type="number" value={form.min_units} onChange={update("min_units")} required />
        <Input label="Max units" type="number" value={form.max_units} onChange={update("max_units")} hint="Leave blank for no upper bound" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Input label="Price per unit" type="number" step="0.01" value={form.price_per_unit} onChange={update("price_per_unit")} />
        <Input label="Flat price" type="number" step="0.01" value={form.flat_price} onChange={update("flat_price")} />
      </div>
      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" isLoading={isSubmitting}>
          Save package
        </Button>
      </div>
    </form>
  );
}

function OverridePriceModal({ landlords, onClose }) {
  const [updatePrice, { isLoading }] = useUpdateLandlordPerUnitPriceMutation();
  const [form, setForm] = useState({ landlord_id: "", per_unit_price: "", reason: "" });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await updatePrice({ id: form.landlord_id, per_unit_price: form.per_unit_price, reason: form.reason }).unwrap();
      toast("Per-unit price overridden.", { type: "success" });
      onClose();
    } catch {
      toast("Could not update the price.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title="Override per-unit price">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Select
          label="Landlord"
          value={form.landlord_id}
          onChange={(e) => setForm((f) => ({ ...f, landlord_id: e.target.value }))}
          options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
          required
        />
        <Input
          label="Per-unit price"
          type="number"
          step="0.01"
          value={form.per_unit_price}
          onChange={(e) => setForm((f) => ({ ...f, per_unit_price: e.target.value }))}
          required
        />
        <Textarea
          label="Reason"
          value={form.reason}
          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
          rows={2}
          required
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Save override
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// §7.2 — admin-defined tiered pricing by unit band, plus per-landlord per-unit overrides.
export default function PricingPackages() {
  const { data, isLoading } = useGetPackagesQuery();
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [createPackage, { isLoading: isCreating }] = useCreatePackageMutation();
  const [updatePackage, { isLoading: isUpdating }] = useUpdatePackageMutation();
  const [deletePackage] = useDeletePackageMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isOverrideOpen, setIsOverrideOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const packages = toRows(data);
  const landlords = toRows(landlordsData);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updatePackage({ id: active.id, ...values }).unwrap();
        toast("Package updated.", { type: "success" });
      } else {
        await createPackage(values).unwrap();
        toast("Package created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the package.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deletePackage(pendingDelete.id).unwrap();
      toast("Package deactivated.", { type: "success" });
    } catch {
      toast("Could not deactivate the package.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "name", header: "Package" },
    { key: "band", header: "Unit band", render: (row) => `${row.min_units} – ${row.max_units ?? "∞"}` },
    {
      key: "price",
      header: "Price",
      render: (row) => (row.flat_price ? formatCurrency(row.flat_price) : `${formatCurrency(row.price_per_unit)} / unit`),
    },
    { key: "is_active", header: "Status", render: (row) => <Badge color={row.is_active ? "emerald" : "white"}>{row.is_active ? "Active" : "Inactive"}</Badge> },
  ];

  return (
    <div>
      <PageHeader
        title="Pricing Packages"
        subtitle="Tiered unit-band pricing landlords subscribe into"
        actions={
          <>
            <Button variant="ghost" onClick={() => setIsOverrideOpen(true)}>
              Override landlord price
            </Button>
            <Button
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setActive(null);
                setIsFormOpen(true);
              }}
            >
              Add package
            </Button>
          </>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={packages}
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

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit package" : "Add package"}>
        <PackageForm initialValues={active} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      {isOverrideOpen && <OverridePriceModal landlords={landlords} onClose={() => setIsOverrideOpen(false)} />}

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Deactivate package?"
        description="Landlords already on this package keep their rate; new subscriptions won't use it."
      />
    </div>
  );
}
