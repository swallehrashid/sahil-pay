import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";
import { useDemoMode } from "@/features/landlord/useDemoMode";

const SECTIONS = [
  { to: LANDLORD_ROUTES.settings.general, label: "General", dataTour: ANCHORS.settings.general },
  { to: LANDLORD_ROUTES.settings.account, label: "Account", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.alerts, label: "Alerts" },
  { to: LANDLORD_ROUTES.settings.backup, label: "Backup", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.documents, label: "Documents" },
  { to: LANDLORD_ROUTES.settings.receiptLayout, label: "Receipt layout" },
  { to: LANDLORD_ROUTES.settings.team, label: "Team", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.billing, label: "Billing", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.smsProvider, label: "SMS Provider", dataTour: ANCHORS.settings.smsProvider, accountLevel: true },
  { to: LANDLORD_ROUTES.settings.mpesa, label: "M-Pesa", dataTour: ANCHORS.settings.mpesa, accountLevel: true },
  { to: LANDLORD_ROUTES.settings.copilot, label: "Co-pilot", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.taxCompliance, label: "Tax Compliance", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.allocation, label: "Payments & Commission", accountLevel: true },
  { to: LANDLORD_ROUTES.settings.audit, label: "Audit Trail" },
  { to: LANDLORD_ROUTES.settings.impersonationRequests, label: "Client Support", accountLevel: true },
];

// Tabbed shell for every settings sub-page — the sub-pages render through <Outlet/>.
export default function SettingsLayout() {
  // Account-level sections (billing, team, backups, etc.) manage the real
  // account and are hidden while browsing the demo shadow (DEMO_MODE_SPEC.md
  // §5.6) — direct navigation is still caught by withDemoBlock in AppRoutes.jsx.
  const { isActive: isDemoActive } = useDemoMode();
  const sections = isDemoActive ? SECTIONS.filter((s) => !s.accountLevel) : SECTIONS;

  return (
    <div>
      <PageHeader title="Settings" subtitle="Configure your Sahil Pay account" />
      <div className="no-scrollbar mb-6 flex gap-1 overflow-x-auto border-b border-white/10">
        {sections.map((section) => (
          <NavLink
            key={section.to}
            to={section.to}
            data-tour={section.dataTour}
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
