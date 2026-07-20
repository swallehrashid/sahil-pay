import { useParams, useNavigate, Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import DetailGrid from "./components/DetailGrid";
import { useGetAdminPropertyQuery } from "./adminApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — full property detail: landlord, plan/trial funding, occupancy, and every
// unit with its occupant. This is the "company / property" drill-down.
export default function PropertyDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, isLoading } = useGetAdminPropertyQuery(id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={data?.name ?? "Property detail"}
        subtitle={data?.landlord?.company_name ? `${data.landlord.company_name} · ${data.city ?? ""}` : "Property detail"}
        breadcrumbs={[{ label: "Properties", to: ADMIN_ROUTES.properties }, { label: "Detail" }]}
        actions={
          <Link to={ADMIN_ROUTES.properties}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
          </Link>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Total units" value={data?.unit_count ?? 0} accent="third" />
          <SummaryCard label="Occupied" value={data?.occupied_units ?? 0} accent="third" />
          <SummaryCard label="Vacant" value={data?.vacant_units ?? 0} accent="third" />
          <SummaryCard label="Plan" value={data?.is_on_trial ? <Badge color="amber">On trial</Badge> : <Badge color="emerald">Paid</Badge>} />
        </div>
      )}

      <DetailGrid
        title="Property"
        items={[
          { label: "Name", value: data?.name },
          { label: "City", value: data?.city },
          { label: "Street", value: data?.street_name },
          { label: "Declared units", value: data?.number_of_units },
          { label: "Tax rate", value: data?.tax_rate != null ? `${data.tax_rate}%` : null },
          { label: "Management fee", value: data?.management_fee != null ? formatCurrency(data.management_fee) : null },
          { label: "Owner phone", value: data?.owner_phone },
          { label: "M-Pesa", value: data?.mpesa_details },
        ]}
      />

      <DetailGrid
        title="Landlord & plan"
        items={[
          { label: "Landlord", value: data?.landlord?.company_name && (
            <Link className="text-third-100 hover:underline" to={ADMIN_ROUTES.landlordDetailPath(data.landlord.landlord_id)}>{data.landlord.company_name}</Link>
          ) },
          { label: "Landlord email", value: data?.landlord?.landlord_email },
          { label: "Package", value: data?.package?.name },
          { label: "Subscription cost", value: data?.subscription_cost != null ? formatCurrency(data.subscription_cost) : null },
          { label: "Subscription status", value: data?.subscription_status },
          { label: "On trial", value: data?.is_on_trial ? "Yes" : "No" },
          { label: "Trial ends", value: data?.trial_ends_at ? formatDate(data.trial_ends_at) : null },
        ]}
      />

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Units & occupancy</h3>
        <ResponsiveTable
          columns={[
            { key: "name", header: "Unit" },
            { key: "rent_amount", header: "Rent", render: (r) => formatCurrency(r.rent_amount) },
            { key: "is_occupied", header: "Status", render: (r) => <Badge color={r.is_occupied ? "emerald" : "secondary"}>{r.is_occupied ? "Occupied" : "Vacant"}</Badge> },
            { key: "occupant", header: "Occupant", render: (r) => r.occupant?.name ?? "—" },
            { key: "balance", header: "Balance", render: (r) => (r.occupant?.balance != null ? formatCurrency(r.occupant.balance) : "—") },
          ]}
          rows={data?.units ?? []}
          isLoading={isLoading}
          onRowClick={(row) => navigate(ADMIN_ROUTES.unitDetailPath(row.id))}
        />
      </div>
    </div>
  );
}
