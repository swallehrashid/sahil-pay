import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Receipt,
  Wallet,
  Users,
  Building2,
  DoorOpen,
  Gauge,
  Wrench,
  FolderTree,
  BarChart3,
  MessageSquare,
  MessagesSquare,
  Bell,
  Banknote,
  LogOut,
  AlertTriangle,
  FileText,
  BookOpen,
  GraduationCap,
  Landmark,
  FileSpreadsheet,
} from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { TEAM_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";
import { useGetEtimsScopeQuery } from "@/features/landlord/etims/etimsApiSlice";

// Items without a `module` key are ungated (dashboard/notifications). Every other
// item names the permission module that governs it; buildVisibleNav hides a link
// entirely when the team member lacks view access to that module — matching the
// backend's @require_permission on the same routes.
const NAV_ITEMS = [
  { to: TEAM_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true },
  { to: TEAM_ROUTES.invoices, label: "Invoices", icon: <Receipt className="h-4 w-4" />, module: "invoices" },
  { to: TEAM_ROUTES.payments, label: "Payments", icon: <Wallet className="h-4 w-4" />, module: "payments" },
  { to: TEAM_ROUTES.expenses, label: "Expenses", icon: <Banknote className="h-4 w-4" />, module: "expenses" },
  { to: TEAM_ROUTES.tenants, label: "Tenants", icon: <Users className="h-4 w-4" />, module: "tenants" },
  { to: TEAM_ROUTES.properties, label: "Properties", icon: <Building2 className="h-4 w-4" />, module: "properties" },
  { to: TEAM_ROUTES.units, label: "Units", icon: <DoorOpen className="h-4 w-4" />, module: "units" },
  { to: TEAM_ROUTES.utilities, label: "Utilities", icon: <Gauge className="h-4 w-4" />, module: "utilities" },
  { to: TEAM_ROUTES.maintenance, label: "Maintenance", icon: <Wrench className="h-4 w-4" />, module: "maintenance" },
  { to: TEAM_ROUTES.groups, label: "Property Groups", icon: <FolderTree className="h-4 w-4" />, module: "groups" },
  { to: TEAM_ROUTES.leases, label: "Leases", icon: <FileText className="h-4 w-4" />, module: "tenants" },
  { to: TEAM_ROUTES.reportsStatements, label: "Reports", icon: <BarChart3 className="h-4 w-4" />, module: "reports" },
  { to: TEAM_ROUTES.reportsPenalties, label: "Penalties", icon: <AlertTriangle className="h-4 w-4" />, module: "reports" },
  { to: TEAM_ROUTES.communications, label: "Communications", icon: <MessageSquare className="h-4 w-4" />, module: "messages" },
  { to: TEAM_ROUTES.messages, label: "Tenant Messages", icon: <MessagesSquare className="h-4 w-4" />, module: "messages" },
  { to: TEAM_ROUTES.notifications, label: "Notifications", icon: <Bell className="h-4 w-4" /> },
  // Step-by-step product tours, filtered to the modules this member holds.
  { to: TEAM_ROUTES.tutorials, label: "Help & Tutorials", icon: <GraduationCap className="h-4 w-4" /> },
  // The admin-authored help library. Ungated — the server already filters
  // articles to the caller's role.
  { to: TEAM_ROUTES.help, label: "Guides", icon: <BookOpen className="h-4 w-4" /> },
];

// Shown only when an in-scope property has eTIMS switched on, and then still
// subject to the member's own permissions — same rule as the landlord sidebar.
const ETIMS_NAV_ITEMS = [
  { to: TEAM_ROUTES.etimsRegister, label: "eTIMS Register", icon: <Landmark className="h-4 w-4" />, module: "properties" },
  { to: TEAM_ROUTES.kraMonthly, label: "KRA Monthly Report", icon: <FileSpreadsheet className="h-4 w-4" />, module: "reports" },
];

// Renders ONLY the modules this team member can view — a hidden module never renders
// in nav at all, even though the backend is the real enforcement boundary.
export default function TeamMemberSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { visibleNav } = usePermissions();
  const { data: etimsScope } = useGetEtimsScopeQuery();

  // Slot the eTIMS links in just before Guides, so the reference material stays
  // at the bottom of the list.
  const items = etimsScope?.enabled
    ? [...NAV_ITEMS.slice(0, -1), ...ETIMS_NAV_ITEMS, NAV_ITEMS[NAV_ITEMS.length - 1]]
    : NAV_ITEMS;

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <Sidebar
      items={visibleNav(items)}
      isMobileOpen={isMobileOpen}
      onCloseMobile={onCloseMobile}
      footer={
        <div className="space-y-2 px-1">
          <p className="truncate text-xs text-white/40">{user?.email}</p>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogOut className="h-4 w-4" /> Log out
          </button>
        </div>
      }
    />
  );
}
