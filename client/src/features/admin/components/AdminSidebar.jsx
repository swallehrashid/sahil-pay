import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Building2, Tags, Clock, ShieldCheck, FileSearch, LogOut } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { ADMIN_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: ADMIN_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true },
  { to: ADMIN_ROUTES.landlords, label: "Landlords", icon: <Building2 className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.pricing, label: "Pricing", icon: <Tags className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.trials, label: "Trials", icon: <Clock className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.impersonation, label: "Impersonation", icon: <ShieldCheck className="h-4 w-4" /> },
  { to: ADMIN_ROUTES.audit, label: "Master Audit", icon: <FileSearch className="h-4 w-4" /> },
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
        <span className="text-lg font-light tracking-wide text-white">
          SahilPay <span className="text-secondary">Admin</span>
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
