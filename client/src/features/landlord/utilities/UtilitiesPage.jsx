import { useState } from "react";
import { Plus, Upload, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import RecordUtilityForm from "./RecordUtilityForm";
import BulkUploadUtilities from "./BulkUploadUtilities";
import { useGetUtilityReadingsQuery, useCreateUtilityReadingMutation, useUpdateUtilityReadingMutation, useDeleteUtilityReadingMutation } from "./utilityApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetUnitsQuery } from "../units/unitApiSlice";
import { toRows } from "@/utils/tableAdapters";

export default function UtilitiesPage() {
  const { data, isLoading } = useGetUtilityReadingsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: unitsData } = useGetUnitsQuery();
  const [createReading, { isLoading: isCreating }] = useCreateUtilityReadingMutation();
  const [updateReading, { isLoading: isUpdating }] = useUpdateUtilityReadingMutation();
  const [deleteReading] = useDeleteUtilityReadingMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isBulkOpen, setIsBulkOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const readings = toRows(data);
  const properties = toRows(propertiesData);
  const units = toRows(unitsData);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateReading({ id: active.id, ...values }).unwrap();
        toast("Reading updated.", { type: "success" });
      } else {
        await createReading(values).unwrap();
        toast("Reading recorded.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the reading.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteReading(pendingDelete.id).unwrap();
      toast("Reading deleted.", { type: "success" });
    } catch {
      toast("Could not delete the reading.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "month", header: "Month", render: (row) => row.reading_month },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "item", header: "Item", render: (row) => row.utility_item },
    { key: "previous", header: "Previous", render: (row) => row.previous_reading ?? "—" },
    { key: "current", header: "Current", render: (row) => row.current_reading },
    { key: "invoice", header: "Invoice #", render: (row) => row.invoice_number ?? "Not invoiced" },
  ];

  return (
    <div>
      <PageHeader
        title="Utilities"
        subtitle="Meter readings across water, electricity, garbage and security"
        actions={
          <>
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setIsBulkOpen(true)}>
              Bulk upload
            </Button>
            <Button
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setActive(null);
                setIsFormOpen(true);
              }}
            >
              Record reading
            </Button>
          </>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={readings}
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
              { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit reading" : "Record reading"}>
        <RecordUtilityForm
          initialValues={active}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <BulkUploadUtilities isOpen={isBulkOpen} onClose={() => setIsBulkOpen(false)} properties={properties} units={units} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete reading?"
        description="This utility reading will be permanently removed."
      />
    </div>
  );
}
