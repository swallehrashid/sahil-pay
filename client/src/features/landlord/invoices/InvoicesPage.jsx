import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus, FileText, Send, Download, Pencil, Trash2, Layers } from "lucide-react";
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
import InvoiceForm from "./InvoiceForm";
import BulkInvoices from "./BulkInvoices";
import GenerateRentInvoices from "./GenerateRentInvoices";
import GenerateRecurringInvoices from "./GenerateRecurringInvoices";
import GeneratePenaltyInvoices from "./GeneratePenaltyInvoices";
import GenerateCustomInvoices from "./GenerateCustomInvoices";
import { useGetInvoicesQuery, useCreateInvoiceMutation, useUpdateInvoiceMutation, useDeleteInvoiceMutation, useSendInvoiceMutation } from "./invoiceApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { INVOICE_STATUSES } from "@/utils/constants";

export default function InvoicesPage() {
  const [searchParams] = useSearchParams();
  const tenantIdFromQuery = searchParams.get("tenant_id");

  const [filters, setFilters] = useState({ status: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [activeGenerator, setActiveGenerator] = useState(null);

  const { data, isLoading } = useGetInvoicesQuery(appliedFilters);
  const { data: tenantsData } = useGetTenantsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const [createInvoice, { isLoading: isCreating }] = useCreateInvoiceMutation();
  const [updateInvoice, { isLoading: isUpdating }] = useUpdateInvoiceMutation();
  const [deleteInvoice] = useDeleteInvoiceMutation();
  const [sendInvoice] = useSendInvoiceMutation();

  const [activeInvoice, setActiveInvoice] = useState(() => (tenantIdFromQuery ? { tenant_id: tenantIdFromQuery } : null));
  const [isFormOpen, setIsFormOpen] = useState(() => Boolean(tenantIdFromQuery));
  const [pendingDelete, setPendingDelete] = useState(null);

  const invoices = toRows(data);
  const tenants = toRows(tenantsData);
  const properties = toRows(propertiesData);

  const totals = {
    total: data?.total_amount ?? invoices.reduce((sum, inv) => sum + Number(inv.total_amount ?? 0), 0),
    count: data?.total_count ?? invoices.length,
  };

  const openCreate = () => {
    setActiveInvoice(null);
    setIsFormOpen(true);
  };
  const openEdit = (invoice) => {
    setActiveInvoice(invoice);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activeInvoice?.id) {
        await updateInvoice({ id: activeInvoice.id, ...values }).unwrap();
        toast("Invoice updated.", { type: "success" });
      } else {
        await createInvoice(values).unwrap();
        toast("Invoice created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the invoice.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteInvoice(pendingDelete.id).unwrap();
      toast("Invoice deleted.", { type: "success" });
    } catch {
      toast("Could not delete the invoice.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "invoice_number", header: "Invoice #" },
    { key: "date", header: "Date", render: (row) => formatDate(row.issue_date) },
    { key: "tenant", header: "Tenant", render: (row) => row.tenant_name },
    { key: "item", header: "Item", render: (row) => row.invoice_type },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.total_amount) },
  ];

  return (
    <div>
      <PageHeader
        title="Invoices"
        subtitle="Every invoice you've sent, across every tenant"
        actions={
          <>
            <Dropdown
              align="right"
              trigger={
                <Button variant="ghost" leftIcon={<Layers className="h-4 w-4" />}>
                  Generate
                </Button>
              }
              items={[
                { label: "Generate rent invoices", onClick: () => setActiveGenerator("rent") },
                { label: "Generate recurring bills", onClick: () => setActiveGenerator("recurring") },
                { label: "Generate penalty invoices", onClick: () => setActiveGenerator("penalty") },
                { label: "Generate custom invoices", onClick: () => setActiveGenerator("custom") },
                { label: "Bulk add invoices", onClick: () => setActiveGenerator("bulk") },
              ]}
            />
            <Button
              variant="ghost"
              leftIcon={<Download className="h-4 w-4" />}
              onClick={() => downloadFile("/invoices/bulk-download", { filename: "invoices.zip", format: "zip" })}
            >
              Download all
            </Button>
            <Button leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
              Add invoice
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={2} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <SummaryCard label="Total invoices" value={totals.count} icon={<FileText className="h-5 w-5" />} />
          <SummaryCard label="Total invoiced" value={formatCurrency(totals.total)} icon={<FileText className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6 flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => setAppliedFilters(filters)}
          onReset={() => {
            setFilters({ status: "", date_from: "", date_to: "" });
            setAppliedFilters({});
          }}
        >
          <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
          <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
          <Select
            label="Status"
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            options={INVOICE_STATUSES.map((s) => ({ value: s, label: s }))}
          />
        </FilterPanel>

        <div className="flex-1">
          <ResponsiveTable
            columns={columns}
            rows={invoices}
            isLoading={isLoading}
            rowActions={(row) => (
              <Dropdown
                items={[
                  { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                  { label: "Send", icon: <Send className="h-4 w-4" />, onClick: () => sendInvoice(row.id).then(() => toast("Invoice sent.", { type: "success" })) },
                  {
                    label: "Download",
                    icon: <Download className="h-4 w-4" />,
                    onClick: () => downloadFile(`/invoices/${row.id}/download`, { filename: `${row.invoice_number}.pdf` }),
                  },
                  { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
                ]}
              />
            )}
          />
        </div>
      </div>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeInvoice?.id ? "Edit invoice" : "Add invoice"} size="lg">
        <InvoiceForm
          initialValues={activeInvoice}
          tenants={tenants}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <GenerateRentInvoices isOpen={activeGenerator === "rent"} onClose={() => setActiveGenerator(null)} properties={properties} />
      <GenerateRecurringInvoices isOpen={activeGenerator === "recurring"} onClose={() => setActiveGenerator(null)} properties={properties} />
      <GeneratePenaltyInvoices isOpen={activeGenerator === "penalty"} onClose={() => setActiveGenerator(null)} properties={properties} />
      <GenerateCustomInvoices isOpen={activeGenerator === "custom"} onClose={() => setActiveGenerator(null)} tenants={tenants} />
      <BulkInvoices isOpen={activeGenerator === "bulk"} onClose={() => setActiveGenerator(null)} tenants={tenants} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete invoice?"
        description={`Invoice "${pendingDelete?.invoice_number}" will be soft-deleted.`}
      />
    </div>
  );
}
