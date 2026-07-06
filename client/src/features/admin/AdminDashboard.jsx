import { useNavigate } from "react-router-dom";
import { Building2, Users, UserCog, Layers, Home } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetAdminDashboardQuery } from "./adminApiSlice";
import { toRows } from "@/utils/tableAdapters";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — platform overview. Every stat card and every landlord row is clickable
// and drills into the matching directory (landlords, units, tenants, team, properties).
export default function AdminDashboard() {
  const navigate = useNavigate();
  const { data, isLoading } = useGetAdminDashboardQuery();
  const totals = data?.platform_totals ?? {};
  const rows = toRows(data?.landlords);

  const cards = [
    { label: "Landlords / PMs", value: totals.total_landlords ?? 0, icon: <Building2 className="h-5 w-5" />, to: ADMIN_ROUTES.landlords },
    { label: "Properties", value: totals.total_properties ?? 0, icon: <Home className="h-5 w-5" />, to: ADMIN_ROUTES.properties },
    { label: "Total units", value: totals.total_units ?? 0, icon: <Layers className="h-5 w-5" />, to: ADMIN_ROUTES.units },
    { label: "Active tenants", value: totals.total_active_tenants ?? 0, icon: <Users className="h-5 w-5" />, to: ADMIN_ROUTES.tenants },
    { label: "Team members", value: totals.total_team_members ?? 0, icon: <UserCog className="h-5 w-5" />, to: ADMIN_ROUTES.teamMembers },
  ];

  const columns = [
    { key: "company_name", header: "Company" },
    { key: "units", header: "Units", render: (row) => row.unit_count ?? 0 },
    { key: "tenants", header: "Active tenants", render: (row) => row.active_tenants ?? 0 },
    { key: "team", header: "Team members", render: (row) => row.team_members ?? 0 },
  ];

  return (
    <div>
      <PageHeader title="Platform Overview" subtitle="Every landlord and property manager on SahilPay — click any card to drill in" />

      {isLoading ? (
        <SkeletonStatCards count={5} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-5">
          {cards.map((c) => (
            <button
              key={c.label}
              type="button"
              onClick={() => navigate(c.to)}
              className="rounded-2xl text-left transition-transform focus:outline-none focus-visible:ring-2 focus-visible:ring-third/60 hover:-translate-y-0.5"
            >
              <SummaryCard label={c.label} value={c.value} icon={c.icon} accent="third" />
            </button>
          ))}
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={rows}
          isLoading={isLoading}
          onRowClick={(row) => navigate(ADMIN_ROUTES.landlordDetailPath(row.id))}
        />
      </div>
    </div>
  );
}
