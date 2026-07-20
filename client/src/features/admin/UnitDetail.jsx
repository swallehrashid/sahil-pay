import { useParams, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import DetailGrid from "./components/DetailGrid";
import { useGetAdminUnitQuery } from "./adminApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate, formatDateTime } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — full detail on one unit: property, landlord, occupant history, recent payments.
export default function UnitDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminUnitQuery(id);

  const occupant = data?.occupant;

  return (
    <div className="space-y-6">
      <PageHeader
        title={data?.name ?? "Unit detail"}
        subtitle={data?.property_name ? `${data.property_name} · ${data.company_name ?? ""}` : "Unit detail"}
        breadcrumbs={[{ label: "Units", to: ADMIN_ROUTES.units }, { label: "Detail" }]}
        actions={
          <Link to={ADMIN_ROUTES.units}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
          </Link>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Rent" value={formatCurrency(data?.rent_amount)} accent="third" />
          <SummaryCard label="Occupancy" value={<Badge color={data?.is_occupied ? "emerald" : "secondary"}>{data?.is_occupied ? "Occupied" : "Vacant"}</Badge>} />
          <SummaryCard label="Occupant" value={occupant ? `${occupant.first_name} ${occupant.last_name}` : "—"} accent="third" />
          <SummaryCard label="Occupant balance" value={occupant ? formatCurrency(occupant.balance) : "—"} accent="third" />
        </div>
      )}

      <DetailGrid
        title="Unit"
        items={[
          { label: "Name", value: data?.name },
          { label: "Rent", value: data?.rent_amount != null ? formatCurrency(data.rent_amount) : null },
          { label: "Tax rate", value: data?.tax_rate != null ? `${data.tax_rate}%` : null },
          { label: "Notes", value: data?.notes },
        ]}
      />

      <DetailGrid
        title="Property & landlord"
        items={[
          { label: "Property", value: data?.property?.name },
          { label: "City", value: data?.property?.city },
          { label: "Landlord", value: data?.company_name && (
            <Link className="text-third-100 hover:underline" to={ADMIN_ROUTES.landlordDetailPath(data.landlord_id)}>{data.company_name}</Link>
          ) },
          { label: "Landlord email", value: data?.landlord_email },
        ]}
      />

      {occupant && (
        <DetailGrid
          title="Current occupant"
          items={[
            { label: "Name", value: `${occupant.first_name} ${occupant.last_name}` },
            { label: "Phone", value: occupant.phone },
            { label: "Email", value: occupant.email },
            { label: "Balance", value: occupant.balance != null ? formatCurrency(occupant.balance) : null },
            { label: "Lease start", value: occupant.lease_start_date ? formatDate(occupant.lease_start_date) : null },
            { label: "Lease expiry", value: occupant.lease_expiry_date ? formatDate(occupant.lease_expiry_date) : null },
          ]}
        />
      )}

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Occupancy history</h3>
        <ResponsiveTable
          columns={[
            { key: "name", header: "Tenant" },
            { key: "phone", header: "Phone" },
            { key: "move_in_date", header: "Moved in", render: (r) => (r.move_in_date ? formatDate(r.move_in_date) : "—") },
            { key: "move_out_date", header: "Moved out", render: (r) => (r.move_out_date ? formatDate(r.move_out_date) : "—") },
            { key: "is_deleted", header: "Status", render: (r) => <Badge color={r.is_deleted ? "secondary" : "emerald"}>{r.is_deleted ? "Removed" : "Active"}</Badge> },
          ]}
          rows={data?.tenants_all ?? []}
          isLoading={isLoading}
        />
      </div>

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
    </div>
  );
}
