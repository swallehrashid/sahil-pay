import { Link } from "react-router-dom";
import { AlertTriangle, CheckCheck, Home, Wallet } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuth } from "@/hooks/useAuth";
import { TEAM_ROUTES } from "@/config/routePaths";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetDashboardSummaryQuery } from "@/features/landlord/landlordApiSlice";
import { useGetInvoiceQueueQuery } from "@/features/landlord/invoices/invoiceQueueApiSlice";

// Every page a member may open, in the order the sidebar lists them.
const QUICK_LINKS = [
  { to: TEAM_ROUTES.payments, label: "Payments", module: "payments" },
  { to: TEAM_ROUTES.invoices, label: "Invoices", module: "invoices" },
  { to: TEAM_ROUTES.reviewQueue, label: "Payment review queue", module: "payments" },
  { to: TEAM_ROUTES.payouts, label: "Owner payouts", module: "payments" },
  { to: TEAM_ROUTES.expenses, label: "Expenses", module: "expenses" },
  { to: TEAM_ROUTES.reportsPenalties, label: "Penalties", module: "penalties" },
  { to: TEAM_ROUTES.tenants, label: "Tenants", module: "tenants" },
  { to: TEAM_ROUTES.leases, label: "Leases", module: "leases" },
  { to: TEAM_ROUTES.maintenance, label: "Maintenance", module: "maintenance" },
  { to: TEAM_ROUTES.properties, label: "Properties", module: "properties" },
  { to: TEAM_ROUTES.units, label: "Units", module: "units" },
  { to: TEAM_ROUTES.utilities, label: "Utilities & meters", module: "utilities" },
  { to: TEAM_ROUTES.groups, label: "Property groups", module: "groups" },
  { to: TEAM_ROUTES.communications, label: "Send messages", module: "messages" },
  { to: TEAM_ROUTES.messages, label: "Tenant inbox", module: "messages" },
  { to: TEAM_ROUTES.reportsStatements, label: "Statements & reports", module: "reports" },
];

// Landing view scoped to what this team member is allowed to see. A member with
// Payments access gets the same money cards the owner sees; one who can bill is
// told when a caretaker has sent charges for review.
export default function TeamMemberDashboard() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canSeeMoney = can("payments", "view");
  const canBill = can("invoices", "edit");

  const { data: summary } = useGetDashboardSummaryQuery(undefined, { skip: !canSeeMoney });
  const { data: queue } = useGetInvoiceQueueQuery(undefined, { skip: !can("invoices", "view") });

  const visibleLinks = QUICK_LINKS.filter((link) => link.to && can(link.module, "view"));
  const name = user?.profile?.first_name || user?.first_name || user?.username || "";

  return (
    <div className="space-y-6">
      <PageHeader title={`Welcome${name ? `, ${name}` : ""}`} subtitle="Here's what you have access to" />

      {canSeeMoney && summary && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="team-kpis">
          <SummaryCard label="Collected this month" value={formatCurrency(summary.payments_this_month)} icon={<Wallet className="h-5 w-5" />} />
          <SummaryCard label="Invoiced this month" value={formatCurrency(summary.invoices_this_month)} icon={<Wallet className="h-5 w-5" />} />
          <SummaryCard label="Arrears" value={formatCurrency(summary.total_arrears)} icon={<AlertTriangle className="h-5 w-5" />} />
          <SummaryCard label="Occupancy" value={`${summary.occupancy_percent ?? 0}%`} icon={<Home className="h-5 w-5" />} />
        </div>
      )}

      {canBill && queue?.review_count > 0 && (
        <Link to={`${TEAM_ROUTES.invoices}?tab=queue`} className="glass card-hover flex items-center gap-3 border border-third/40 p-4"
              data-testid="team-review-nudge">
          <CheckCheck className="h-5 w-5 text-third-100" />
          <span className="text-sm text-white/85">
            {queue.review_count} charge{queue.review_count === 1 ? "" : "s"} waiting for your review
            ({formatCurrency(queue.review_total)})
          </span>
        </Link>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleLinks.map((link, index) => (
          <Link key={link.to} to={link.to} style={{ animationDelay: `${index * 40}ms` }} className="glass card-hover animate-fade-in-up p-6 text-white">
            <span className="text-base font-medium">{link.label}</span>
            <p className="mt-1 text-sm text-white/50">Open {link.label.toLowerCase()}</p>
          </Link>
        ))}
        {visibleLinks.length === 0 && <p className="text-sm text-white/50">No modules have been enabled for your account yet.</p>}
      </div>
    </div>
  );
}
