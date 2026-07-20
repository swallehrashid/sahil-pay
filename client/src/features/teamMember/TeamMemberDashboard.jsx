import { Link } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuth } from "@/hooks/useAuth";
import { TEAM_ROUTES } from "@/config/routePaths";

const QUICK_LINKS = [
  { to: TEAM_ROUTES.invoices, label: "Invoices", module: "invoices" },
  { to: TEAM_ROUTES.payments, label: "Payments", module: "payments" },
  { to: TEAM_ROUTES.tenants, label: "Tenants", module: "tenants" },
  { to: TEAM_ROUTES.properties, label: "Properties", module: "properties" },
  { to: TEAM_ROUTES.units, label: "Units", module: "units" },
  { to: TEAM_ROUTES.utilities, label: "Utilities", module: "utilities" },
  { to: TEAM_ROUTES.communications, label: "Communications", module: "messages" },
];

// Landing view scoped to what this team member is allowed to see — re-mounts the
// landlord module pages under permission guards rather than duplicating any UI.
export default function TeamMemberDashboard() {
  const { user } = useAuth();
  const { can } = usePermissions();

  const visibleLinks = QUICK_LINKS.filter((link) => can(link.module, "view"));

  return (
    <div>
      <PageHeader title={`Welcome, ${user?.first_name ?? user?.username ?? ""}`} subtitle="Here's what you have access to" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleLinks.map((link, index) => (
          <Link key={link.to} to={link.to} style={{ animationDelay: `${index * 60}ms` }} className="glass card-hover animate-fade-in-up p-6 text-white">
            <span className="text-base font-medium">{link.label}</span>
            <p className="mt-1 text-sm text-white/50">Open {link.label.toLowerCase()}</p>
          </Link>
        ))}
        {visibleLinks.length === 0 && <p className="text-sm text-white/50">No modules have been enabled for your account yet.</p>}
      </div>
    </div>
  );
}
