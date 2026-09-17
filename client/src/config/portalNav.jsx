import {
  LayoutDashboard, Receipt, Wallet, ReceiptText, Users, Building2, DoorOpen, Wrench, BarChart3,
  MessageSquare, Settings as SettingsIcon, Banknote, Home, LifeBuoy, UserPlus, Send,
} from "lucide-react";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

// ONE navigation structure for the landlord and team-member portals.
//
// Grouped by the job being done — the way a landlord describes their week:
// "collect the money, look after tenants, look after the buildings, talk to
// people, see how it's going". Eight entries instead of twenty-one flat links.
//
//   Dashboard
//   Money       Payments · Invoices · Review queue · Expenses · Penalties · Owner payouts · (eTIMS)
//   Tenants     Tenants · Leases · Maintenance
//   Properties  Properties · Units · Utilities · Property groups · Import from Excel
//   Messages    Send messages · Tenant inbox · Notifications
//   Reports     Statements · Insights · (KRA monthly)
//   Help        Tutorials · Guides
//   Settings    (landlord only — its own grouped sub-menu)
//
// `module` gates a link for team members (see utils/permissions.js); a group
// whose links are all hidden disappears.

const icon = (Icon) => <Icon className="h-4 w-4" />;

export function buildPortalNav(routes, { etims = false, leaseReviewCount = 0, isLandlord = true } = {}) {
  const nav = [
    { to: routes.dashboard, label: "Dashboard", icon: icon(LayoutDashboard), end: true, dataTour: ANCHORS.sidebar.dashboard },
    {
      key: "money", label: "Money", icon: icon(Wallet),
      children: [
        { to: routes.payments, label: "Payments", module: "payments", dataTour: ANCHORS.sidebar.payments },
        { to: routes.invoices, label: "Invoices", module: "invoices", dataTour: ANCHORS.sidebar.invoices },
        // Money that arrived but couldn't be matched with certainty — next to
        // Payments, where someone looks when a tenant says "I paid".
        ...(isLandlord ? [{ to: routes.reviewQueue, label: "Review queue", module: "payments" }] : []),
        { to: routes.expenses, label: "Expenses", module: "expenses" },
        { to: routes.reportsPenalties, label: "Penalties", module: "penalties" },
        ...(isLandlord ? [{ to: routes.payouts, label: "Owner payouts", module: "payments" }] : []),
        ...(etims ? [{ to: routes.etimsRegister, label: "eTIMS register", module: "properties" }] : []),
      ],
    },
    {
      key: "tenants", label: "Tenants", icon: icon(Users),
      children: [
        { to: routes.tenants, label: "Tenants", module: "tenants", dataTour: ANCHORS.sidebar.tenants },
        { to: routes.leases, label: "Leases", module: "leases", badge: leaseReviewCount },
        { to: routes.maintenance, label: "Maintenance", module: "maintenance" },
      ],
    },
    {
      key: "properties", label: "Properties", icon: icon(Building2),
      children: [
        { to: routes.properties, label: "Properties", module: "properties", dataTour: ANCHORS.sidebar.properties },
        { to: routes.units, label: "Units", module: "units", dataTour: ANCHORS.sidebar.units },
        { to: routes.utilities, label: "Utilities & meters", module: "utilities", dataTour: ANCHORS.sidebar.utilities },
        { to: routes.groups, label: "Property groups", module: "groups" },
        { to: routes.imports, label: "Import from Excel", module: "tenants", requires: "edit" },
      ],
    },
    {
      key: "messages", label: "Messages", icon: icon(MessageSquare),
      children: [
        { to: routes.communications, label: "Send messages", module: "messages", dataTour: ANCHORS.sidebar.communications },
        { to: routes.messages, label: "Tenant inbox", module: "messages" },
        { to: routes.notifications, label: "Notifications", dataTour: ANCHORS.sidebar.notifications },
      ],
    },
    {
      key: "reports", label: "Reports", icon: icon(BarChart3),
      children: [
        { to: routes.reportsStatements, label: "Statements & reports", module: "reports", dataTour: ANCHORS.sidebar.reports },
        { to: routes.reportsInsights, label: "Insights", module: "reports" },
        ...(etims ? [{ to: routes.kraMonthly, label: "KRA monthly report", module: "reports" }] : []),
      ],
    },
    {
      key: "help", label: "Help", icon: icon(LifeBuoy),
      children: [
        { to: routes.tutorials, label: "Tutorials", dataTour: ANCHORS.sidebar.tutorials },
        { to: routes.help, label: "Guides" },
      ],
    },
  ];
  if (isLandlord && routes.settings) {
    nav.push({ to: routes.settings.root, label: "Settings", icon: icon(SettingsIcon), dataTour: ANCHORS.sidebar.settings });
  }
  return nav;
}

/** Apply team-member permissions to a grouped nav; empty groups are dropped. */
export function filterPortalNav(nav, canView) {
  return nav
    .map((item) => {
      if (!item.children) return !item.module || canView(item.module, item.requires) ? item : null;
      const children = item.children.filter((c) => !c.module || canView(c.module, c.requires));
      return children.length ? { ...item, children } : null;
    })
    .filter(Boolean);
}

/** What "+ New" offers. Each opens the create form directly (?new=1). */
export function buildNewActions(routes) {
  return [
    { to: `${routes.payments}?new=1`, label: "Record a payment", icon: Banknote, module: "payments", requires: "edit" },
    { to: `${routes.invoices}?new=1`, label: "Create an invoice", icon: Receipt, module: "invoices", requires: "edit" },
    { to: `${routes.tenants}?new=1`, label: "Add a tenant", icon: UserPlus, module: "tenants", requires: "edit" },
    { to: `${routes.leases}?new=1`, label: "Send a lease", icon: Send, module: "leases", requires: "edit" },
    { to: `${routes.properties}?new=1`, label: "Add a property", icon: Home, module: "properties", requires: "edit" },
    { to: `${routes.units}?new=1`, label: "Add a unit", icon: DoorOpen, module: "units", requires: "edit" },
    { to: `${routes.expenses}?new=1`, label: "Record an expense", icon: ReceiptText, module: "expenses", requires: "edit" },
    { to: `${routes.maintenance}?new=1`, label: "Log a repair", icon: Wrench, module: "maintenance", requires: "edit" },
  ];
}
