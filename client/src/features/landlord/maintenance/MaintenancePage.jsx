import { useState } from "react";
import { Plus, AlertCircle, Loader2, Pencil, Trash2, Receipt, Eye, Paperclip } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { withFiles } from "@/utils/multipart";
import MaintenanceForm from "./MaintenanceForm";
import CreateExpenseFromMaintenance from "./CreateExpenseFromMaintenance";
import MaintenanceDetail from "./MaintenanceDetail";
import {
  useGetMaintenanceRequestsQuery,
  useCreateMaintenanceRequestMutation,
  useUpdateMaintenanceRequestMutation,
  useDeleteMaintenanceRequestMutation,
} from "./maintenanceApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetUnitsQuery } from "../units/unitApiSlice";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function MaintenancePage() {
  const { data, isLoading } = useGetMaintenanceRequestsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: unitsData } = useGetUnitsQuery();
  const [createRequest, { isLoading: isCreating }] = useCreateMaintenanceRequestMutation();
  const [updateRequest, { isLoading: isUpdating }] = useUpdateMaintenanceRequestMutation();
  const [deleteRequest] = useDeleteMaintenanceRequestMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [expenseTarget, setExpenseTarget] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  // The request being read in full — photo, description, status controls.
  const [viewing, setViewing] = useState(null);

  const requests = toRows(data);
  const properties = toRows(propertiesData);
  const units = toRows(unitsData);

  const totals = {
    open: data?.open_count ?? requests.filter((r) => r.status === "open").length,
    inProgress: data?.in_progress_count ?? requests.filter((r) => r.status === "in_progress").length,
  };

  const handleSubmit = async (values) => {
    // The photo has to go as multipart. Sent inside a JSON body the File
    // stringifies to {} and is dropped without a word, so the request saves
    // fine and the picture is simply gone.
    const body = withFiles(values, ["image"]);
    try {
      if (active?.id) {
        await updateRequest({ id: active.id, body }).unwrap();
        toast("Maintenance request updated.", { type: "success" });
      } else {
        await createRequest(body).unwrap();
        toast("Maintenance request created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch (err) {
      toast(err?.data?.error || "Could not save the request.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteRequest(pendingDelete.id).unwrap();
      toast("Maintenance request deleted.", { type: "success" });
    } catch {
      toast("Could not delete the request.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    {
      key: "summary",
      header: "Summary",
      render: (row) => (
        <button
          onClick={() => setViewing(row)}
          className="flex items-center gap-1.5 text-left text-secondary hover:underline"
        >
          {row.summary}
          {/* A paperclip on the row means "there is a photo to look at" —
              otherwise the only way to find out is to open every request. */}
          {row.image_url && <Paperclip className="h-3.5 w-3.5 flex-shrink-0 text-white/40" />}
        </button>
      ),
    },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "category", header: "Category" },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "date", header: "Date", render: (row) => formatDate(row.created_at) },
    {
      key: "expense",
      header: "Expense",
      render: (row) =>
        row.expense_id ? (
          <span className="text-xs text-white/40">Linked</span>
        ) : (
          <button onClick={() => setExpenseTarget(row)} className="flex items-center gap-1 text-xs text-secondary hover:underline">
            <Receipt className="h-3.5 w-3.5" /> Create
          </button>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Maintenance"
        subtitle="Repair and maintenance requests across your portfolio"
        actions={
          <Button
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setActive(null);
              setIsFormOpen(true);
            }}
          >
            Add request
          </Button>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={2} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <SummaryCard label="Open requests" value={totals.open} icon={<AlertCircle className="h-5 w-5" />} />
          <SummaryCard label="In progress" value={totals.inProgress} icon={<Loader2 className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={requests}
          isLoading={isLoading}
          rowActions={(row) => (
            <Dropdown
              items={[
                {
                  label: "View details",
                  icon: <Eye className="h-4 w-4" />,
                  onClick: () => setViewing(row),
                },
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
      </div>

      {viewing && (
        <MaintenanceDetail
          request={requests.find((r) => r.id === viewing.id) || viewing}
          onClose={() => setViewing(null)}
        />
      )}

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit request" : "Add maintenance request"}>
        <MaintenanceForm
          initialValues={active}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <CreateExpenseFromMaintenance request={expenseTarget} onClose={() => setExpenseTarget(null)} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete request?"
        description="This maintenance request will be permanently removed."
      />
    </div>
  );
}
