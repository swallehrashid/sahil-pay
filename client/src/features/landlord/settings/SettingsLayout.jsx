import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";
import { useDemoMode } from "@/features/landlord/useDemoMode";

const R = LANDLORD_ROUTES.settings;

// Settings, grouped the way people look for them. Sixteen tabs in one sideways
// strip meant scrolling past "Backup" and "Audit Trail" to find "Billing".
//
// LAPTOP & UP: a left sub-menu with four headed groups, always visible.
// PHONE: one "Jump to" menu with the same groups — no hidden sideways scroll.
const GROUPS = [
  {
    label: "Your business",
    items: [
      { to: R.general, label: "Company, logo & contacts", dataTour: ANCHORS.settings.general },
      { to: R.receiptLayout, label: "Receipts & colours" },
      { to: R.documents, label: "Documents & lease templates" },
      { to: R.account, label: "My account", accountLevel: true },
    ],
  },
  {
    label: "Money",
    items: [
      { to: R.billing, label: "Billing & subscription", accountLevel: true },
      { to: R.mpesa, label: "M-Pesa", dataTour: ANCHORS.settings.mpesa, accountLevel: true },
      { to: R.allocation, label: "Payments & commission", accountLevel: true },
      { to: R.penalties, label: "Late-payment penalties", accountLevel: true },
      { to: R.taxCompliance, label: "Tax (KRA eTIMS)", accountLevel: true },
    ],
  },
  {
    label: "Messages",
    items: [
      { to: R.smsProvider, label: "SMS sender", dataTour: ANCHORS.settings.smsProvider, accountLevel: true },
      { to: R.alerts, label: "Alerts" },
      { to: R.copilot, label: "Co-pilot (SMS forwarding)", accountLevel: true },
    ],
  },
  {
    label: "Team & security",
    items: [
      { to: R.team, label: "Team members", accountLevel: true },
      { to: R.audit, label: "Audit trail" },
      { to: R.impersonationRequests, label: "Support access", accountLevel: true },
      { to: R.backup, label: "Backup & export", accountLevel: true },
    ],
  },
];

export default function SettingsLayout() {
  // Account-level sections are hidden while browsing the demo shadow
  // (DEMO_MODE_SPEC.md §5.6); direct navigation is still caught by withDemoBlock.
  const { isActive: isDemoActive } = useDemoMode();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const groups = GROUPS
    .map((g) => ({ ...g, items: isDemoActive ? g.items.filter((i) => !i.accountLevel) : g.items }))
    .filter((g) => g.items.length);
  const current = groups.flatMap((g) => g.items).find((i) => pathname.startsWith(i.to));

  return (
    <div>
      <PageHeader title="Settings" subtitle={current ? current.label : "Configure your Sahil Pay account"} />

      <label className="mb-5 block lg:hidden">
        <span className="mb-1.5 block text-sm font-medium text-white/70">Jump to</span>
        <select
          className="glass-input w-full"
          value={current?.to ?? ""}
          onChange={(e) => navigate(e.target.value)}
          data-testid="settings-jump"
        >
          {groups.map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.items.map((i) => <option key={i.to} value={i.to}>{i.label}</option>)}
            </optgroup>
          ))}
        </select>
      </label>

      <div className="lg:grid lg:grid-cols-[230px_minmax(0,1fr)] lg:gap-8 2xl:grid-cols-[260px_minmax(0,1fr)]">
        <nav aria-label="Settings" className="hidden lg:block">
          <div className="glass sticky top-6 space-y-5 p-3">
            {groups.map((g) => (
              <div key={g.label}>
                <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/40">{g.label}</p>
                <ul className="space-y-0.5">
                  {g.items.map((i) => (
                    <li key={i.to}>
                      <NavLink
                        to={i.to}
                        data-tour={i.dataTour}
                        className={({ isActive }) =>
                          clsx("block rounded-lg px-3 py-2 text-sm transition-colors",
                            isActive ? "bg-secondary/20 text-white" : "text-white/60 hover:bg-white/5 hover:text-white")
                        }
                      >
                        {i.label}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </nav>
        <div className="min-w-0">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
