import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Receipt,
  Wallet,
  ReceiptText,
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
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { LANDLORD_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: LANDLORD_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true },
  { to: LANDLORD_ROUTES.invoices, label: "Invoices", icon: <Receipt className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.payments, label: "Payments", icon: <Wallet className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.expenses, label: "Expenses", icon: <ReceiptText className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.tenants, label: "Tenants", icon: <Users className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.properties, label: "Properties", icon: <Building2 className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.units, label: "Units", icon: <DoorOpen className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.utilities, label: "Utilities", icon: <Gauge className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.maintenance, label: "Maintenance", icon: <Wrench className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.groups, label: "Property Groups", icon: <FolderTree className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.reportsStatements, label: "Reports", icon: <BarChart3 className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.communications, label: "Communications", icon: <MessageSquare className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.messages, label: "Tenant Messages", icon: <MessagesSquare className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.notifications, label: "Notifications", icon: <Bell className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.settings.root, label: "Settings", icon: <SettingsIcon className="h-4 w-4" /> },
];

export default function LandlordSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <Sidebar
      items={NAV_ITEMS}
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
