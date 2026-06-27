import { Link } from "react-router-dom";
import { Wallet, Receipt, History } from "lucide-react";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { useGetPortalDashboardQuery } from "./tenantPortalApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { TENANT_ROUTES } from "@/config/routePaths";

// §6.2 — detailed balance breakdown: rent due, utilities due, previous month's balance.
export default function TenantDashboard() {
  const { data, isLoading } = useGetPortalDashboardQuery();
  const openInvoices = data?.open_invoices ?? [];

  const columns = [
    { key: "invoice_number", header: "Invoice" },
    { key: "type", header: "Type" },
    { key: "due_date", header: "Due", render: (row) => (row.due_date ? formatDate(row.due_date) : "—") },
    { key: "balance", header: "Balance", render: (row) => formatCurrency(row.balance) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-light tracking-wide text-white">Welcome back{data?.tenant_name ? `, ${data.tenant_name}` : ""}</h1>
          <p className="mt-1 text-sm text-white/50">Here's your current balance breakdown.</p>
        </div>
        <Link to={TENANT_ROUTES.pay}>
          <Button leftIcon={<Wallet className="h-4 w-4" />}>Pay now</Button>
        </Link>
      </div>

      {isLoading ? (
        <SkeletonStatCards count={3} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <SummaryCard label="Rent due" value={formatCurrency(data?.rent_due)} icon={<Receipt className="h-5 w-5" />} />
          <SummaryCard label="Utilities due" value={formatCurrency(data?.utility_due)} icon={<Receipt className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Previous balance" value={formatCurrency(data?.previous_balance)} icon={<History className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div>
        <h3 className="mb-3 text-base font-medium text-white">Open invoices</h3>
        <ResponsiveTable
          columns={columns}
          rows={openInvoices}
          isLoading={isLoading}
          emptyState={<p className="text-sm text-white/50">No open invoices — you're all caught up.</p>}
        />
      </div>
    </div>
  );
}
