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
} from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { TEAM_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";
import { usePermissions } from "@/hooks/usePermissions";

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
  { to: TEAM_ROUTES.reportsStatements, label: "Reports", icon: <BarChart3 className="h-4 w-4" />, module: "reports" },
  { to: TEAM_ROUTES.communications, label: "Communications", icon: <MessageSquare className="h-4 w-4" />, module: "messages" },
  { to: TEAM_ROUTES.messages, label: "Tenant Messages", icon: <MessagesSquare className="h-4 w-4" />, module: "messages" },
  { to: TEAM_ROUTES.notifications, label: "Notifications", icon: <Bell className="h-4 w-4" /> },
];

// Renders ONLY the modules this team member can view — a hidden module never renders
// in nav at all, even though the backend is the real enforcement boundary.
export default function TeamMemberSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { visibleNav } = usePermissions();

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <Sidebar
      items={visibleNav(NAV_ITEMS)}
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
