import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Users, Wallet, Banknote, UserCircle } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import SahilPayLogo from "@/components/branding/SahilPayLogo";
import { AFFILIATE_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";

const NAV_ITEMS = [
  { to: AFFILIATE_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true },
  { to: AFFILIATE_ROUTES.referrals, label: "Referrals", icon: <Users className="h-4 w-4" /> },
  { to: AFFILIATE_ROUTES.earnings, label: "Earnings", icon: <Banknote className="h-4 w-4" /> },
  { to: AFFILIATE_ROUTES.withdrawals, label: "Withdrawals", icon: <Wallet className="h-4 w-4" /> },
  { to: AFFILIATE_ROUTES.profile, label: "Profile", icon: <UserCircle className="h-4 w-4" /> },
];

export default function AffiliateSidebar({ isMobileOpen, onCloseMobile }) {
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
          <span className="text-sm font-light tracking-wide text-white/40">Affiliate</span>
        </span>
      }
      footer={
        <div className="space-y-2 px-1">
          <p className="truncate text-xs text-white/40">{user?.email}</p>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
          >
            Log out
          </button>
        </div>
      }
    />
  );
}
