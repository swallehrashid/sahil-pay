import { useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Plus, Wallet, Upload, Pencil, Trash2, Send, Download, ArrowRightLeft, FileBarChart } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import RecordPaymentForm from "./RecordPaymentForm";
import BankStatementUpload from "./BankStatementUpload";
import ReassignTenantModal from "./ReassignTenantModal";
import { useGetPaymentsQuery, useCreatePaymentMutation, useUpdatePaymentMutation, useDeletePaymentMutation, useSendPaymentReceiptMutation } from "./paymentApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { useGetInvoicesQuery } from "../invoices/invoiceApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { PAYMENT_STATUSES, PAYMENT_SOURCES } from "@/utils/constants";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default function PaymentsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const tenantIdFromQuery = searchParams.get("tenant_id");

  const [filters, setFilters] = useState({ status: "", source: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});

  const { data, isLoading } = useGetPaymentsQuery(appliedFilters);
  const { data: tenantsData } = useGetTenantsQuery();
  const { data: invoicesData } = useGetInvoicesQuery();
  const [createPayment, { isLoading: isCreating }] = useCreatePaymentMutation();
  const [updatePayment, { isLoading: isUpdating }] = useUpdatePaymentMutation();
  const [deletePayment] = useDeletePaymentMutation();
  const [sendReceipt] = useSendPaymentReceiptMutation();

  const [activePayment, setActivePayment] = useState(() => (tenantIdFromQuery ? { tenant_id: tenantIdFromQuery } : null));
  const [isFormOpen, setIsFormOpen] = useState(() => Boolean(tenantIdFromQuery));
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [reassignTarget, setReassignTarget] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const payments = toRows(data);
  const tenants = toRows(tenantsData);
  const invoices = toRows(invoicesData);

  const totals = {
    total: data?.total_amount ?? payments.reduce((sum, p) => sum + Number(p.amount ?? 0), 0),
    count: data?.total_count ?? payments.length,
  };

  const openCreate = () => {
    setActivePayment(null);
    setIsFormOpen(true);
  };
  const openEdit = (payment) => {
    setActivePayment(payment);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activePayment?.id) {
        await updatePayment({ id: activePayment.id, ...values }).unwrap();
        toast("Payment updated.", { type: "success" });
      } else {
        await createPayment(values).unwrap();
        toast("Payment recorded.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the payment.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deletePayment(pendingDelete.id).unwrap();
      toast("Payment deleted.", { type: "success" });
    } catch {
      toast("Could not delete the payment.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.payment_date) },
    { key: "payment_ref", header: "Payment ID" },
    { key: "tenant", header: "Tenant", render: (row) => row.tenant_name ?? "—" },
    { key: "unit", header: "Property / Unit", render: (row) => `${row.property_name ?? ""} ${row.unit_name ?? ""}`.trim() || "—" },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
  ];

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Every payment recorded against your tenants"
        actions={
          <>
            <Button variant="ghost" leftIcon={<FileBarChart className="h-4 w-4" />} onClick={() => downloadFile("/payments/report", { filename: "payments-report.pdf" })}>
              Report
            </Button>
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setIsUploadOpen(true)}>
              Upload statement
            </Button>
            <Button leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
              Record payment
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={2} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <SummaryCard label="Total payments" value={totals.count} icon={<Wallet className="h-5 w-5" />} />
          <SummaryCard label="Total received" value={formatCurrency(totals.total)} icon={<Wallet className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6 flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => setAppliedFilters(filters)}
          onReset={() => {
            setFilters({ status: "", source: "", date_from: "", date_to: "" });
            setAppliedFilters({});
          }}
        >
          <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
          <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
          <Select
            label="Status"
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            options={PAYMENT_STATUSES.map((s) => ({ value: s, label: s }))}
          />
          <Select
            label="Source"
            value={filters.source}
            onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value }))}
            options={PAYMENT_SOURCES.map((s) => ({ value: s, label: s }))}
          />
        </FilterPanel>

        <div className="flex-1">
          <ResponsiveTable
            columns={columns}
            rows={payments}
            isLoading={isLoading}
            rowActions={(row) => (
              <Dropdown
                items={[
                  { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                  { label: "Send receipt", icon: <Send className="h-4 w-4" />, onClick: () => sendReceipt(row.id).then(() => toast("Receipt sent.", { type: "success" })) },
                  {
                    label: "Download receipt",
                    icon: <Download className="h-4 w-4" />,
                    onClick: () => downloadFile(`/payments/${row.id}/receipt/download`, { filename: `${row.payment_ref}.pdf` }),
                  },
                  { label: "Change tenant", icon: <ArrowRightLeft className="h-4 w-4" />, onClick: () => setReassignTarget(row) },
                  { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
                ]}
              />
            )}
          />
        </div>
      </div>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activePayment?.id ? "Edit payment" : "Record payment"} size="lg">
        <RecordPaymentForm
          initialValues={activePayment}
          tenants={tenants}
          invoices={invoices}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <BankStatementUpload
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploaded={(id) => id && navigate(LANDLORD_ROUTES.bankStatementReviewPath(id))}
      />
      <ReassignTenantModal payment={reassignTarget} tenants={tenants} onClose={() => setReassignTarget(null)} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete payment?"
        description={`Payment "${pendingDelete?.payment_ref}" will be soft-deleted.`}
      />
    </div>
  );
}
