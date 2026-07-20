import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import { useGetTenantQuery, useGetTenantTransactionsQuery } from "./tenantApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default function TenantTransactions() {
  const { id } = useParams();
  const { data: tenant } = useGetTenantQuery(id);
  const { data, isLoading } = useGetTenantTransactionsQuery(id);
  const rows = toRows(data);

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date ?? row.created_at) },
    { key: "type", header: "Type", render: (row) => row.type ?? row.transaction_type },
    { key: "description", header: "Description", render: (row) => row.description ?? row.item },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "balance", header: "Running balance", render: (row) => formatCurrency(row.running_balance ?? row.balance) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div>
      <PageHeader
        title={tenant ? `${tenant.first_name} ${tenant.last_name} — Transactions` : "Tenant transactions"}
        subtitle="Full invoice & payment ledger for this tenant"
        breadcrumbs={[{ label: "Tenants", to: LANDLORD_ROUTES.tenants }, { label: "Transactions" }]}
        actions={
          <Link to={LANDLORD_ROUTES.tenants}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Back to tenants
            </Button>
          </Link>
        }
      />
      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
    </div>
  );
}
