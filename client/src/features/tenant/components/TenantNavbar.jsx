import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Wallet, FileText, Wrench, User, LogOut } from "lucide-react";
import clsx from "clsx";
import { TENANT_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";

const LINKS = [
  { to: TENANT_ROUTES.dashboard, label: "Dashboard", icon: LayoutDashboard },
  { to: TENANT_ROUTES.pay, label: "Pay", icon: Wallet },
  { to: TENANT_ROUTES.statement, label: "Statement", icon: FileText },
  { to: TENANT_ROUTES.maintenance, label: "Maintenance", icon: Wrench },
  { to: TENANT_ROUTES.profile, label: "Profile", icon: User },
];

// Simple, friendly tenant nav (secondary-accented per the design system) — no left
// sidebar, since the tenant portal is intentionally lean.
export default function TenantNavbar() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.tenantLogin);
  };

  return (
    <header className="glass sticky top-4 z-20 mx-4 mt-4 flex items-center justify-between rounded-2xl px-4 py-3 sm:px-6">
      <span className="text-lg font-light tracking-wide text-white">
        Sahil<span className="text-secondary">Pay</span>
      </span>

      <nav className="no-scrollbar flex items-center gap-1 overflow-x-auto">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-2 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition-colors duration-200",
                isActive ? "bg-secondary/20 text-white" : "text-white/60 hover:text-white"
              )
            }
          >
            <link.icon className="h-4 w-4" />
            <span className="hidden sm:inline">{link.label}</span>
          </NavLink>
        ))}
      </nav>

      <button onClick={handleLogout} className="rounded-xl p-2 text-white/50 transition-colors hover:bg-white/10 hover:text-white">
        <LogOut className="h-4 w-4" />
      </button>
    </header>
  );
}
