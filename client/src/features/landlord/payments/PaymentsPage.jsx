import { useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { Plus, Wallet, Upload, Pencil, Trash2, Send, Download, ArrowRightLeft, FileBarChart, CheckCircle2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Tabs from "@/components/ui/Tabs";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import RecordPaymentForm from "./RecordPaymentForm";
import BankStatementUpload from "./BankStatementUpload";
import ReassignTenantModal from "./ReassignTenantModal";
import ConfirmPaymentModal from "./ConfirmPaymentModal";
import CopilotInboxTab from "./CopilotInboxTab";
import SendReminderModal from "../communications/SendReminderModal";
import { useGetPaymentsQuery, useCreatePaymentMutation, useUpdatePaymentMutation, useDeletePaymentMutation, useSendPaymentReceiptMutation } from "./paymentApiSlice";
import { useGetCopilotInboxSummaryQuery } from "./copilotInboxApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { useGetInvoicesQuery } from "../invoices/invoiceApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { PAYMENT_STATUSES, PAYMENT_SOURCES, PAYMENT_SOURCE_LABELS } from "@/utils/constants";
import { Smartphone } from "lucide-react";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

export default function PaymentsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const tenantIdFromQuery = searchParams.get("tenant_id");
  const statusFromQuery = searchParams.get("status");   // deep-link from the "payment awaiting confirmation" notification
  const tabFromQuery = searchParams.get("tab");

  const [tab, setTab] = useState(tabFromQuery === "copilot" ? "copilot" : "payments");
  const [filters, setFilters] = useState({ status: statusFromQuery || "", source: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState(statusFromQuery ? { status: statusFromQuery } : {});
  const { data: copilotSummary } = useGetCopilotInboxSummaryQuery();
  const copilotBadgeCount = (copilotSummary?.unparsed ?? 0) + (copilotSummary?.unmatched ?? 0);

  const pg = usePagination();
  const { data, isLoading } = useGetPaymentsQuery({ ...appliedFilters, ...pg.params });
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
  const [reviewPayment, setReviewPayment] = useState(null);
  const [reminderTenant, setReminderTenant] = useState(null); // #4

  const payments = toRows(data);
  const meta = toPaginationMeta(data);
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
    // Pull the receipt intent out before it reaches the payment endpoint.
    const { send_receipt, receipt_channels, ...payload } = values;
    try {
      if (activePayment?.id) {
        await updatePayment({ id: activePayment.id, ...payload }).unwrap();
        toast("Payment updated.", { type: "success" });
      } else {
        const created = await createPayment(payload).unwrap();
        toast("Payment recorded.", { type: "success" });
        if (send_receipt && receipt_channels?.length && created?.id) {
          try {
            await sendReceipt({ id: created.id, channels: receipt_channels }).unwrap();
            toast(`Receipt sent via ${receipt_channels.join(", ")}.`, { type: "success" });
          } catch (err) {
            toast(err?.data?.error || "Payment saved, but the receipt could not be sent.", { type: "error" });
          }
        }
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
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="flex items-center gap-2">
          {row.status === "pending" ? (
            <button onClick={() => setReviewPayment(row)} className="inline-flex items-center gap-1.5 rounded-full bg-amber-400/15 px-2.5 py-1 text-xs font-medium text-amber-300 transition-colors hover:bg-amber-400/25">
              <CheckCircle2 className="h-3.5 w-3.5" /> Review
            </button>
          ) : (
            <StatusBadge status={row.status} />
          )}
          {row.source === "co_pilot" && (
            <span title="Recorded via Co-pilot" className="inline-flex items-center gap-1 text-xs text-white/40">
              <Smartphone className="h-3.5 w-3.5" /> Co-pilot
            </span>
          )}
        </div>
      ),
    },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
  ];

  return (
    <div>
      <PageHeader
        title="Payments"
        subtitle="Every payment recorded against your tenants"
        actions={
          tab === "payments" && (
            <>
              <Button variant="ghost" leftIcon={<FileBarChart className="h-4 w-4" />} onClick={() => downloadFile("/payments/report", { filename: "payments-report.pdf" })}>
                Report
              </Button>
              <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setIsUploadOpen(true)}>
                Upload statement
              </Button>
              <Button data-tour={ANCHORS.payments.recordButton} leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
                Record payment
              </Button>
            </>
          )
        }
      />

      <Tabs
        tabs={[
          { key: "payments", label: "Payments" },
          { key: "copilot", label: "Co-Pilot", count: copilotBadgeCount > 0 ? copilotBadgeCount : undefined },
        ]}
        activeKey={tab}
        onChange={setTab}
        className="mb-6"
      />

      {tab === "copilot" ? (
        <CopilotInboxTab />
      ) : (
        <>
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
              onApply={() => { setAppliedFilters(filters); pg.reset(); }}
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
                options={PAYMENT_SOURCES.map((s) => ({ value: s, label: PAYMENT_SOURCE_LABELS[s] ?? s }))}
              />
            </FilterPanel>

            <div className="min-w-0 flex-1">
              <ResponsiveTable
                columns={columns}
                rows={payments}
                isLoading={isLoading}
                rowActions={(row) => (
                  <Dropdown
                    items={[
                      ...(row.status === "pending"
                        ? [{ label: "Review & confirm", icon: <CheckCircle2 className="h-4 w-4" />, onClick: () => setReviewPayment(row) }]
                        : []),
                      { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                      { label: "Send receipt", icon: <Send className="h-4 w-4" />, onClick: () => sendReceipt(row.id).then(() => toast("Receipt sent.", { type: "success" })) },
                      {
                        label: "Download receipt",
                        icon: <Download className="h-4 w-4" />,
                        onClick: () => downloadFile(`/payments/${row.id}/receipt/download`, { filename: `${row.payment_ref}.pdf` }),
                      },
                      { label: "Change tenant", icon: <ArrowRightLeft className="h-4 w-4" />, onClick: () => setReassignTarget(row) },
                      ...(row.tenant_id
                        ? [{
                            label: "Remind tenant",
                            icon: <Send className="h-4 w-4" />,
                            onClick: () => setReminderTenant({ id: row.tenant_id, first_name: (row.tenant_name || "").split(" ")[0] || "Tenant", last_name: (row.tenant_name || "").split(" ").slice(1).join(" ") }),
                          }]
                        : []),
                      { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
                    ]}
                  />
                )}
              />
              <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
            </div>
          </div>
        </>
      )}

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
      {reviewPayment && <ConfirmPaymentModal payment={reviewPayment} onClose={() => setReviewPayment(null)} />}
      <SendReminderModal tenant={reminderTenant} onClose={() => setReminderTenant(null)} />

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
