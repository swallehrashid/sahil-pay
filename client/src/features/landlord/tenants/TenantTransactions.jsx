import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Send, Download, UserRound } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import Dropdown from "@/components/ui/Dropdown";
import SendReceiptModal from "@/features/landlord/payments/SendReceiptModal";
import { useGetTenantQuery, useGetTenantTransactionsQuery } from "./tenantApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { usePortalRoutes } from "@/hooks/usePortalRoutes";
import { usePermissions } from "@/hooks/usePermissions";

export default function TenantTransactions() {
  const ROUTES = usePortalRoutes();
  const { can } = usePermissions();
  const canSend = can("payments", "edit");
  const { id } = useParams();
  const { data: tenant } = useGetTenantQuery(id);
  const { data, isLoading } = useGetTenantTransactionsQuery(id);
  const rows = toRows(data);
  const [receiptPayment, setReceiptPayment] = useState(null);
  const tenantName = tenant ? `${tenant.first_name} ${tenant.last_name}` : "";

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date ?? row.created_at) },
    { key: "ref", header: "Reference", render: (row) => row.mpesa_reference ? `${row.ref} · ${row.mpesa_reference}` : row.ref },
    { key: "type", header: "Type", render: (row) => (row.type === "payment" ? `Payment (${row.item ?? "—"})` : "Invoice") },
    { key: "description", header: "Description", render: (row) => row.description ?? row.item ?? "—" },
    {
      key: "amount",
      header: "Amount",
      render: (row) => (
        <span className={row.type === "payment" ? "text-emerald-300" : ""}>
          {row.type === "payment" ? "− " : ""}{formatCurrency(row.amount ?? row.amount_due)}
          {row.brought_forward > 0 && (
            <span className="block text-xs text-white/40">+ {formatCurrency(row.brought_forward)} b/f (not counted twice)</span>
          )}
        </span>
      ),
    },
    { key: "balance", header: "Running balance", render: (row) => formatCurrency(row.running_balance ?? row.balance) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div>
      <PageHeader
        title={tenant ? `${tenantName} — Transactions` : "Tenant transactions"}
        subtitle="Full invoice & payment ledger for this tenant"
        breadcrumbs={[{ label: "Tenants", to: ROUTES.tenants }, { label: "Transactions" }]}
        actions={
          <Link to={ROUTES.tenants}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Back to tenants
            </Button>
          </Link>
        }
      />
      {tenant?.next_of_kin_name && (
        <div className="glass mb-4 flex flex-wrap items-center gap-x-6 gap-y-1 p-4 text-sm" data-testid="tenant-next-of-kin">
          <span className="inline-flex items-center gap-2 text-white/50"><UserRound className="h-4 w-4" /> Next of kin</span>
          <span className="text-white">{tenant.next_of_kin_name}</span>
          {tenant.next_of_kin_relationship && <span className="text-white/60">{tenant.next_of_kin_relationship}</span>}
          {tenant.next_of_kin_phone && <span className="text-white/60">{tenant.next_of_kin_phone}</span>}
        </div>
      )}
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowActions={(row) =>
          row.type === "payment" ? (
            row.receipt_available ? (
              <Dropdown
                items={[
                  canSend && {
                    label: "Send receipt",
                    icon: <Send className="h-4 w-4" />,
                    onClick: () => setReceiptPayment({
                      id: row.payment_id, payment_ref: row.ref, amount: row.amount,
                      mpesa_reference: row.mpesa_reference, tenant_name: tenantName,
                    }),
                  },
                  {
                    label: "Download receipt",
                    icon: <Download className="h-4 w-4" />,
                    onClick: () => downloadFile(`/payments/${row.payment_id}/receipt/download`, { filename: `${row.ref}.pdf` }),
                  },
                ].filter(Boolean)}
              />
            ) : (
              <span className="text-xs text-white/35" title={row.receipt_blocker || ""}>No receipt yet</span>
            )
          ) : null
        }
      />
      <SendReceiptModal payment={receiptPayment} onClose={() => setReceiptPayment(null)} />
    </div>
  );
}
