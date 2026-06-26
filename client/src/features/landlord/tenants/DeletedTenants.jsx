import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Button from "@/components/ui/Button";
import { useGetDeletedTenantsQuery } from "./tenantApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

// Deleted tenants still surface here (and in reports) per the soft-delete rule — never hard-deleted.
export default function DeletedTenants() {
  const { data, isLoading } = useGetDeletedTenantsQuery();
  const rows = toRows(data);

  const columns = [
    { key: "name", header: "Tenant", render: (row) => `${row.first_name} ${row.last_name}` },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "balance", header: "Balance at deletion", render: (row) => formatCurrency(row.balance) },
    { key: "deleted_at", header: "Deleted on", render: (row) => formatDate(row.deleted_at) },
  ];

  return (
    <div>
      <PageHeader
        title="Deleted tenants"
        subtitle="Soft-deleted tenants — kept for record-keeping and reporting"
        breadcrumbs={[{ label: "Tenants", to: LANDLORD_ROUTES.tenants }, { label: "Deleted" }]}
        actions={
          <Link to={LANDLORD_ROUTES.tenants}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Back to tenants
            </Button>
          </Link>
        }
      />
      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} emptyState={<p className="text-sm text-white/50">No deleted tenants.</p>} />
    </div>
  );
}
