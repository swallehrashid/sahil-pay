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
import { toast } from "@/components/ui/Toast";
import PropertyForm from "./PropertyForm";
import { useGetPropertiesQuery, useCreatePropertyMutation, useUpdatePropertyMutation, useDeletePropertyMutation } from "./propertyApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

export default function PropertiesPage() {
  const pg = usePagination();
  const { data, isLoading } = useGetPropertiesQuery(pg.params);
  const [createProperty, { isLoading: isCreating }] = useCreatePropertyMutation();
  const [updateProperty, { isLoading: isUpdating }] = useUpdatePropertyMutation();
  const [deleteProperty] = useDeletePropertyMutation();

  const [activeProperty, setActiveProperty] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const properties = toRows(data);
  const meta = toPaginationMeta(data);
  const totals = {
    properties: data?.total_properties ?? properties.length,
    units: data?.total_units ?? properties.reduce((sum, p) => sum + (p.number_of_units ?? 0), 0),
    vacancies: data?.total_vacancies ?? 0,
  };

  const openCreate = () => {
    setActiveProperty(null);
    setIsFormOpen(true);
  };
  const openEdit = (property) => {
    setActiveProperty(property);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activeProperty) {
        await updateProperty({ id: activeProperty.id, ...values }).unwrap();
        toast("Property updated.", { type: "success" });
      } else {
        await createProperty(values).unwrap();
        toast("Property added.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the property.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteProperty(pendingDelete.id).unwrap();
      toast("Property deleted.", { type: "success" });
    } catch {
      toast("Could not delete the property.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "name", header: "Property" },
    { key: "units", header: "Units", render: (row) => row.number_of_units },
    { key: "city", header: "Location", render: (row) => row.city },
    { key: "manager", header: "Manager", render: (row) => row.manager_name ?? "—" },
    { key: "water_rate", header: "Water rate", render: (row) => row.water_rate ?? "—" },
  ];

  return (
    <div>
      <PageHeader
        title="Properties"
        subtitle="Every property in your portfolio"
        actions={
          <Button data-tour={ANCHORS.properties.addButton} leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
            Add property
          </Button>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={3} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <SummaryCard label="Total properties" value={totals.properties} icon={<Building2 className="h-5 w-5" />} />
          <SummaryCard label="Total units" value={totals.units} icon={<DoorOpen className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Vacancies" value={totals.vacancies} icon={<AlertCircle className="h-5 w-5" />} />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={properties}
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
        <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
      </div>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeProperty ? "Edit property" : "Add property"} size="lg">
        <PropertyForm initialValues={activeProperty} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete property?"
        description={`"${pendingDelete?.name}" will be moved out of your active properties list.`}
      />
    </div>
  );
}
