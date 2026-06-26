import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import { LANDLORD_ROUTES } from "@/config/routePaths";

const SECTIONS = [
  { to: LANDLORD_ROUTES.settings.general, label: "General" },
  { to: LANDLORD_ROUTES.settings.account, label: "Account" },
  { to: LANDLORD_ROUTES.settings.alerts, label: "Alerts" },
  { to: LANDLORD_ROUTES.settings.backup, label: "Backup" },
  { to: LANDLORD_ROUTES.settings.documents, label: "Documents" },
  { to: LANDLORD_ROUTES.settings.team, label: "Team" },
  { to: LANDLORD_ROUTES.settings.billing, label: "Billing" },
  { to: LANDLORD_ROUTES.settings.mpesa, label: "M-Pesa" },
  { to: LANDLORD_ROUTES.settings.audit, label: "Audit Trail" },
  { to: LANDLORD_ROUTES.settings.impersonationRequests, label: "Impersonation" },
];

// Tabbed shell for every settings sub-page — the sub-pages render through <Outlet/>.
export default function SettingsLayout() {
  return (
    <div>
      <PageHeader title="Settings" subtitle="Configure your SahilPay account" />
      <div className="no-scrollbar mb-6 flex gap-1 overflow-x-auto border-b border-white/10">
        {SECTIONS.map((section) => (
          <NavLink
            key={section.to}
            to={section.to}
            className={({ isActive }) =>
              clsx(
                "whitespace-nowrap px-4 py-3 text-sm font-medium transition-colors duration-200",
                isActive ? "border-b-2 border-secondary text-white" : "text-white/50 hover:text-white/80"
              )
            }
          >
            {section.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  );
}
