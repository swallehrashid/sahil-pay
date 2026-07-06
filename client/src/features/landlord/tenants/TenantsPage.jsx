import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Users,
  AlertTriangle,
  CalendarClock,
  Pencil,
  Trash2,
  Eye,
  Bell,
  FileText,
  Wallet,
  MessageSquare,
  FileDown,
  ArrowRightLeft,
  Download,
} from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { toast } from "@/components/ui/Toast";
import TenantForm from "./TenantForm";
import ShiftTenantModal from "./ShiftTenantModal";
import {
  useGetTenantsQuery,
  useCreateTenantMutation,
  useUpdateTenantMutation,
  useDeleteTenantMutation,
  useSendBulkReminderMutation,
  useSendTenantStatementMutation,
} from "./tenantApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetUnitsQuery } from "../units/unitApiSlice";
import { formatCurrency, formatBalance } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import SendReminderModal from "../communications/SendReminderModal";

export default function TenantsPage() {
  const navigate = useNavigate();
  const pg = usePagination();
  const { data, isLoading } = useGetTenantsQuery(pg.params);
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: unitsData } = useGetUnitsQuery();
  const [createTenant, { isLoading: isCreating }] = useCreateTenantMutation();
  const [updateTenant, { isLoading: isUpdating }] = useUpdateTenantMutation();
  const [deleteTenant] = useDeleteTenantMutation();
  const [sendBulkReminder] = useSendBulkReminderMutation();
  const [sendStatement] = useSendTenantStatementMutation();

  const [activeTenant, setActiveTenant] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [shiftTenant, setShiftTenant] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [reminderTenant, setReminderTenant] = useState(null); // #4 — channel-picker modal
  const [selectedIds, setSelectedIds] = useState([]);

  const tenants = toRows(data);
  const meta = toPaginationMeta(data);
  const properties = toRows(propertiesData);
  const units = toRows(unitsData);

  const totals = {
    tenants: data?.total_tenants ?? tenants.length,
    // balance < 0 = arrears (owed); matches server's landlord_dashboard_routes convention.
    arrears: data?.total_arrears ?? tenants.reduce((sum, t) => sum + Math.max(0, -Number(t.balance ?? 0)), 0),
    expiringLeases: data?.leases_expiring_soon ?? 0,
  };

  const toggleSelected = (id) => setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const openCreate = () => {
    setActiveTenant(null);
    setIsFormOpen(true);
  };
  const openEdit = (tenant) => {
    setActiveTenant(tenant);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activeTenant) {
        await updateTenant({ id: activeTenant.id, ...values }).unwrap();
        toast("Tenant updated.", { type: "success" });
      } else {
        await createTenant(values).unwrap();
        toast("Tenant added.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the tenant.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteTenant(pendingDelete.id).unwrap();
      toast("Tenant deleted.", { type: "success" });
    } catch {
      toast("Could not delete the tenant.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const handleBulkReminder = async () => {
    try {
      await sendBulkReminder({ tenant_ids: selectedIds }).unwrap();
      toast(`Reminder sent to ${selectedIds.length} tenant(s).`, { type: "success" });
      setSelectedIds([]);
    } catch {
      toast("Could not send reminders.", { type: "error" });
    }
  };

  const columns = [
    {
      key: "select",
      header: "",
      render: (row) => <Checkbox checked={selectedIds.includes(row.id)} onChange={() => toggleSelected(row.id)} />,
    },
    { key: "name", header: "Tenant", render: (row) => `${row.first_name} ${row.last_name}` },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "phone", header: "Phone" },
    { key: "balance", header: "Balance", render: (row) => formatBalance(row.balance) },
    { key: "account_number", header: "Account #", render: (row) => row.account_number ?? "—" },
  ];

  return (
    <div>
      <PageHeader
        title="Tenants"
        subtitle="Everyone occupying a unit across your portfolio"
        actions={
          <>
            <Button
              variant="ghost"
              leftIcon={<Download className="h-4 w-4" />}
              onClick={() => downloadFile("/tenants/export.pdf", { filename: "tenants.pdf" })}
            >
              Download PDF
            </Button>
            <Button leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
              Add tenant
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={3} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <SummaryCard label="Total tenants" value={totals.tenants} icon={<Users className="h-5 w-5" />} />
          <SummaryCard label="Total arrears" value={formatCurrency(totals.arrears)} icon={<AlertTriangle className="h-5 w-5" />} />
          <SummaryCard label="Leases expiring soon" value={totals.expiringLeases} icon={<CalendarClock className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={tenants}
          isLoading={isLoading}
          rowActions={(row) => (
            <Dropdown
              items={[
                { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                {
                  label: "View transactions",
                  icon: <Eye className="h-4 w-4" />,
                  onClick: () => navigate(LANDLORD_ROUTES.tenantTransactionsPath(row.id)),
                },
                {
                  label: "Send balance reminder",
                  icon: <Bell className="h-4 w-4" />,
                  onClick: () => setReminderTenant(row),
                },
                { label: "Add invoice", icon: <FileText className="h-4 w-4" />, onClick: () => navigate(`${LANDLORD_ROUTES.invoices}?tenant_id=${row.id}`) },
                { label: "Add payment", icon: <Wallet className="h-4 w-4" />, onClick: () => navigate(`${LANDLORD_ROUTES.payments}?tenant_id=${row.id}`) },
                {
                  label: "Send custom message",
                  icon: <MessageSquare className="h-4 w-4" />,
                  onClick: () => navigate(`${LANDLORD_ROUTES.communications}?tenant_id=${row.id}`),
                },
                {
                  label: "Send statement",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => sendStatement(row.id).then(() => toast("Statement sent.", { type: "success" })),
                },
                {
                  label: "Download statement",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => downloadFile(`/tenants/${row.id}/statement/download`, { filename: `${row.first_name}-statement.pdf` }),
                },
                {
                  label: "Download CSV",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => downloadFile(`/tenants/${row.id}/export.csv`, { filename: `${row.first_name}.csv`, format: "csv" }),
                },
                { label: "Shift tenant", icon: <ArrowRightLeft className="h-4 w-4" />, onClick: () => setShiftTenant(row) },
                { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
              ]}
            />
          )}
        />
        <Pagination
          page={pg.page}
          perPage={pg.perPage}
          total={meta.total}
          onPageChange={pg.setPage}
          onPerPageChange={pg.setPerPage}
        />
      </div>

      {selectedIds.length > 0 && (
        <div className="glass mt-4 flex items-center justify-between p-4 animate-fade-in-up">
          <span className="text-sm text-white/70">{selectedIds.length} tenant(s) selected</span>
          <Button size="sm" leftIcon={<Bell className="h-4 w-4" />} onClick={handleBulkReminder}>
            Send balance reminder
          </Button>
        </div>
      )}

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeTenant ? "Edit tenant" : "Add tenant"} size="lg">
        <TenantForm
          initialValues={activeTenant}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <ShiftTenantModal tenant={shiftTenant} units={units} onClose={() => setShiftTenant(null)} />

      <SendReminderModal tenant={reminderTenant} onClose={() => setReminderTenant(null)} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete tenant?"
        description={`"${pendingDelete?.first_name} ${pendingDelete?.last_name}" will be moved to the deleted-tenants list but will still appear in reports.`}
      />
    </div>
  );
}
