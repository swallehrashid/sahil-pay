import { Building2, Users, UserCog, Layers } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetAdminDashboardQuery } from "./adminApiSlice";
import { toRows } from "@/utils/tableAdapters";

// §7 — every landlord/PM, their units, active tenants and team members, for platform monitoring.
export default function AdminDashboard() {
  const { data, isLoading } = useGetAdminDashboardQuery();
  const rows = toRows(data?.landlords);

  const columns = [
    { key: "company_name", header: "Company" },
    { key: "units", header: "Units", render: (row) => row.unit_count ?? 0 },
    { key: "tenants", header: "Active tenants", render: (row) => row.active_tenant_count ?? 0 },
    { key: "team", header: "Team members", render: (row) => row.team_member_count ?? 0 },
  ];

  return (
    <div>
      <PageHeader title="Platform Overview" subtitle="Every landlord and property manager on SahilPay" />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Landlords / PMs" value={data?.total_landlords ?? 0} icon={<Building2 className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Total units" value={data?.total_units ?? 0} icon={<Layers className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Active tenants" value={data?.total_active_tenants ?? 0} icon={<Users className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Team members" value={data?.total_team_members ?? 0} icon={<UserCog className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
      </div>
    </div>
  );
}
