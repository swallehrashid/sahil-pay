import { AlertTriangle, TrendingUp, Home as HomeIcon, Receipt } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import PerformanceChart from "@/components/charts/PerformanceChart";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import QuickActions from "./components/QuickActions";
import SubscriptionShortcut from "./components/SubscriptionShortcut";
import ImpersonationBanner from "./components/ImpersonationBanner";
import { useGetDashboardSummaryQuery, useGetUnpaidTenantsQuery, useGetPerformanceGraphQuery } from "./landlordApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import GettingStartedChecklist from "./tutorials/GettingStartedChecklist";
import { ANCHORS } from "./tutorials/anchors";

// §4.1 — landlord dashboard: arrears/advances/occupancy, payments-vs-invoices,
// arrears overview, quick actions, subscription/SMS shortcuts and the performance graph.
export default function LandlordDashboard() {
  const { data: summary, isLoading: isSummaryLoading } = useGetDashboardSummaryQuery();
  const { data: unpaidTenants, isLoading: isUnpaidLoading } = useGetUnpaidTenantsQuery();
  const { data: performance } = useGetPerformanceGraphQuery();

  const unpaidRows = toRows(unpaidTenants);

  const columns = [
    {
      key: "name",
      header: "Tenant",
      render: (row) => `${row.first_name ?? ""} ${row.last_name ?? ""}`.trim() || row.name,
    },
    { key: "property", header: "Property", render: (row) => row.property_name ?? row.property },
    { key: "unit", header: "Unit", render: (row) => row.unit_name ?? row.unit },
    { key: "balance", header: "Balance", render: (row) => formatCurrency(row.balance) },
    { key: "status", header: "Status", render: () => <StatusBadge status="pending" /> },
  ];

  return (
    <div>
      <ImpersonationBanner />
      <PageHeader title="Dashboard" subtitle="An overview of how your portfolio is performing" />

      <GettingStartedChecklist />

      {isSummaryLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div data-tour={ANCHORS.dashboard.kpiCards} className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Total arrears" value={formatCurrency(summary?.total_arrears)} icon={<AlertTriangle className="h-5 w-5" />} />
          <SummaryCard label="Total advances" value={formatCurrency(summary?.total_advances)} icon={<TrendingUp className="h-5 w-5" />} />
          <SummaryCard label="Occupancy" value={summary?.occupancy_percent ?? 0} icon={<HomeIcon className="h-5 w-5" />} isCountUp accent="third" />
          <SummaryCard
            label="Paid vs invoiced"
            value={`${formatCurrency(summary?.payments_this_month)} / ${formatCurrency(summary?.invoices_this_month)}`}
            icon={<Receipt className="h-5 w-5" />}
            accent="third"
          />
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <PerformanceChart data={performance?.series ?? []} />
        </div>
        <div className="space-y-6">
          <QuickActions />
          <SubscriptionShortcut />
        </div>
      </div>

      <div className="mt-6">
        <h3 className="mb-3 text-base font-medium text-white">Tenants with arrears</h3>
        <ResponsiveTable
          columns={columns}
          rows={unpaidRows}
          isLoading={isUnpaidLoading}
          emptyState={<EmptyState title="No outstanding arrears" description="Every tenant is up to date." />}
        />
      </div>
    </div>
  );
}
