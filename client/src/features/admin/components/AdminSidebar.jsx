import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Building2, Home, Layers, Users, UserCog, Tags, MessageSquare, Clock, ShieldCheck, FileSearch, Bell, LogOut, Handshake, Smartphone, Receipt, BookOpen } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import SahilPayLogo from "@/components/branding/SahilPayLogo";
import { ADMIN_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: ADMIN_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true },
  { to: ADMIN_ROUTES.landlords, label: "Landlords", icon: <Building2 className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.properties, label: "Properties", icon: <Home className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.units, label: "Units", icon: <Layers className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.tenants, label: "Tenants", icon: <Users className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.teamMembers, label: "Team members", icon: <UserCog className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.pricing, label: "Pricing", icon: <Tags className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.affiliates, label: "Affiliates", icon: <Handshake className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.sms, label: "SMS", icon: <MessageSquare className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.billing, label: "Billing", icon: <Receipt className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.copilot, label: "Co-pilot", icon: <Smartphone className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.helpContent, label: "Help Content", icon: <BookOpen className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.trials, label: "Trials", icon: <Clock className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.impersonation, label: "Client Support", icon: <ShieldCheck className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.audit, label: "Master Audit", icon: <FileSearch className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.notifications, label: "Notifications", icon: <Bell className="h-4 w-4" /> },
];

// Ultra-minimalist, dark-mode-by-default per the design system's admin theming rule.
export default function AdminSidebar({ isMobileOpen, onCloseMobile }) {
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
      header={
        <span className="flex items-center gap-2 text-white">
          <SahilPayLogo withSlogan={false} className="h-7" />
          <span className="text-sm font-light tracking-wide text-secondary">Admin</span>
        </span>
      }
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
