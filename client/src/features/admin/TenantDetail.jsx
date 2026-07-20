import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import DetailGrid from "./components/DetailGrid";
import { useGetAdminTenantQuery } from "./adminApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate, formatDateTime } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — full tenant profile: lease, deposit, unit/property/landlord, payments, invoices.
export default function TenantDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminTenantQuery(id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={data?.name ?? "Tenant detail"}
        subtitle={data?.company_name ? `${data.property?.name ?? ""} · ${data.company_name}` : "Tenant detail"}
        breadcrumbs={[{ label: "Tenants", to: ADMIN_ROUTES.tenants }, { label: "Detail" }]}
        actions={
          <Link to={ADMIN_ROUTES.tenants}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
          </Link>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Balance" value={formatCurrency(data?.balance)} accent="third" />
          <SummaryCard label="Unit" value={data?.unit?.name ?? "—"} accent="third" />
          <SummaryCard label="Deposit paid" value={formatCurrency(data?.deposit_paid)} accent="third" />
          <SummaryCard label="Phone" value={data?.phone ?? "—"} accent="third" />
        </div>
      )}

      <DetailGrid
        title="Tenant"
        items={[
          { label: "Name", value: data?.name },
          { label: "Phone", value: data?.phone },
          { label: "Secondary phone", value: data?.secondary_phone },
          { label: "Email", value: data?.email },
          { label: "National ID", value: data?.national_id },
          { label: "KRA PIN", value: data?.kra_pin },
          { label: "Account number", value: data?.account_number },
        ]}
      />

      <DetailGrid
        title="Lease & deposit"
        items={[
          { label: "Lease start", value: data?.lease_start_date ? formatDate(data.lease_start_date) : null },
          { label: "Lease expiry", value: data?.lease_expiry_date ? formatDate(data.lease_expiry_date) : null },
          { label: "Move in", value: data?.move_in_date ? formatDate(data.move_in_date) : null },
          { label: "Move out", value: data?.move_out_date ? formatDate(data.move_out_date) : null },
          { label: "Deposit amount", value: data?.deposit_amount != null ? formatCurrency(data.deposit_amount) : null },
          { label: "Deposit paid", value: data?.deposit_paid != null ? formatCurrency(data.deposit_paid) : null },
          { label: "Deposit returned", value: data?.deposit_returned != null ? formatCurrency(data.deposit_returned) : null },
        ]}
      />

      <DetailGrid
        title="Unit, property & landlord"
        items={[
          { label: "Unit", value: data?.unit?.name && (
            <Link className="text-third-100 hover:underline" to={ADMIN_ROUTES.unitDetailPath(data.unit.id)}>{data.unit.name}</Link>
          ) },
          { label: "Property", value: data?.property?.name },
          { label: "City", value: data?.property?.city },
          { label: "Landlord", value: data?.company_name && (
            <Link className="text-third-100 hover:underline" to={ADMIN_ROUTES.landlordDetailPath(data.landlord_id)}>{data.company_name}</Link>
          ) },
        ]}
      />

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Recent payments</h3>
        <ResponsiveTable
          columns={[
            { key: "created_at", header: "Date", render: (r) => formatDateTime(r.created_at) },
            { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount) },
            { key: "source", header: "Source" },
            { key: "status", header: "Status" },
          ]}
          rows={data?.recent_payments ?? []}
          isLoading={isLoading}
        />
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Recent invoices</h3>
        <ResponsiveTable
          columns={[
            { key: "created_at", header: "Date", render: (r) => formatDateTime(r.created_at) },
            { key: "title", header: "Title" },
            { key: "total_amount", header: "Amount", render: (r) => formatCurrency(r.total_amount) },
            { key: "status", header: "Status" },
          ]}
          rows={data?.recent_invoices ?? []}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
}
