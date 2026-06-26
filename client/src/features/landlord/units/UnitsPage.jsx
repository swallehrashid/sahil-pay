import { useState } from "react";
import { Plus, Building2, DoorOpen, AlertCircle, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import UnitForm from "./UnitForm";
import { useGetUnitsQuery, useCreateUnitMutation, useUpdateUnitMutation, useDeleteUnitMutation } from "./unitApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function UnitsPage() {
  const { data, isLoading } = useGetUnitsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const [createUnit, { isLoading: isCreating }] = useCreateUnitMutation();
  const [updateUnit, { isLoading: isUpdating }] = useUpdateUnitMutation();
  const [deleteUnit] = useDeleteUnitMutation();

  const [activeUnit, setActiveUnit] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const units = toRows(data);
  const properties = toRows(propertiesData);
  const totals = {
    properties: properties.length,
    units: data?.total_units ?? units.length,
    vacancies: data?.total_vacancies ?? units.filter((u) => !u.is_occupied).length,
  };

  const openCreate = () => {
    setActiveUnit(null);
    setIsFormOpen(true);
  };
  const openEdit = (unit) => {
    setActiveUnit(unit);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activeUnit) {
        await updateUnit({ id: activeUnit.id, ...values }).unwrap();
        toast("Unit updated.", { type: "success" });
      } else {
        await createUnit(values).unwrap();
        toast("Unit added.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the unit.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteUnit(pendingDelete.id).unwrap();
      toast("Unit deleted.", { type: "success" });
    } catch {
      toast("Could not delete the unit.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "property", header: "Property", render: (row) => row.property_name ?? row.property?.name },
    { key: "name", header: "Unit" },
    {
      key: "occupied",
      header: "Occupied",
      render: (row) => <Badge color={row.is_occupied ? "emerald" : "white"}>{row.is_occupied ? "Yes" : "No"}</Badge>,
    },
    { key: "rent_amount", header: "Rent / month", render: (row) => formatCurrency(row.rent_amount) },
    { key: "tax_rate", header: "Tax rate", render: (row) => (row.tax_rate != null ? `${row.tax_rate}%` : "—") },
  ];

  return (
    <div>
      <PageHeader
        title="Units"
        subtitle="Every unit across your properties"
        actions={
          <Button leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
            Add unit
          </Button>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={3} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <SummaryCard label="Properties" value={totals.properties} icon={<Building2 className="h-5 w-5" />} />
          <SummaryCard label="Total units" value={totals.units} icon={<DoorOpen className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Vacancies" value={totals.vacancies} icon={<AlertCircle className="h-5 w-5" />} />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={units}
          isLoading={isLoading}
          rowActions={(row) => (
            <Dropdown
              items={[
                { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
              ]}
            />
          )}
        />
      </div>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeUnit ? "Edit unit" : "Add unit"}>
        <UnitForm initialValues={activeUnit} properties={properties} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete unit?"
        description={`"${pendingDelete?.name}" will be soft-deleted.`}
      />
    </div>
  );
}
