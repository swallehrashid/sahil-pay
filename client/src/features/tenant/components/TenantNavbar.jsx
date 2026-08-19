import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Wallet, FileText, Wrench, MessageSquare, User, LogOut, BookOpen, ScrollText } from "lucide-react";
import clsx from "clsx";
import { TENANT_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";
import NotificationBell from "@/features/notifications/NotificationBell";
import SahilPayLogo, { SahilPayMark } from "@/components/branding/SahilPayLogo";

const LINKS = [
  { to: TENANT_ROUTES.dashboard, label: "Dashboard", icon: LayoutDashboard },
  { to: TENANT_ROUTES.pay, label: "Pay", icon: Wallet },
  { to: TENANT_ROUTES.statement, label: "Statement", icon: FileText },
  { to: TENANT_ROUTES.maintenance, label: "Maintenance", icon: Wrench },
  { to: TENANT_ROUTES.messages, label: "Messages", icon: MessageSquare },
  { to: TENANT_ROUTES.lease, label: "Lease", icon: ScrollText },
  // Admin-authored guides, filtered server-side to tenant-facing articles.
  { to: TENANT_ROUTES.help, label: "Guides", icon: BookOpen },
  { to: TENANT_ROUTES.profile, label: "Profile", icon: User },
];

// Simple, friendly tenant nav (secondary-accented per the design system) — no left
// sidebar, since the tenant portal is intentionally lean.
//
// EVERY LINK CARRIES ITS NAME. The labels used to be `hidden sm:inline`, which
// on a phone — where this portal is almost entirely used — left eight identical
// glass squares with no text and no aria-label, in a strip narrower than the
// links it held. "My landlord sent a lease and the tenant never saw it" was
// partly this: the Lease link was real, reachable and completely undiscoverable,
// sitting off the right edge behind a scroll nobody could see was there. The
// labels are now always rendered (smaller on narrow screens), the strip fades at
// its scrollable edge, and aria-label makes each destination announceable
// whatever the width.
export default function TenantNavbar() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.tenantLogin);
  };

  return (
    <header className="glass sticky top-4 z-20 mx-4 mt-4 flex items-center justify-between rounded-2xl px-4 py-3 sm:px-6">
      <span className="text-white">
        <SahilPayLogo withSlogan={false} className="hidden h-7 sm:flex md:h-8" />
        <SahilPayMark className="h-7 sm:hidden" />
      </span>

      <nav
        aria-label="Tenant portal"
        className="no-scrollbar -mx-1 flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto px-1
                   [mask-image:linear-gradient(to_right,transparent,black_12px,black_calc(100%-12px),transparent)]
                   sm:[mask-image:none] sm:gap-1"
      >
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            aria-label={link.label}
            title={link.label}
            className={({ isActive }) =>
              clsx(
                "flex flex-shrink-0 flex-col items-center gap-0.5 whitespace-nowrap rounded-xl px-2.5 py-1.5",
                "text-[10px] transition-colors duration-200",
                "sm:flex-row sm:gap-2 sm:px-3 sm:py-2 sm:text-sm",
                isActive ? "bg-secondary/20 text-white" : "text-white/60 hover:text-white"
              )
            }
          >
            <link.icon className="h-4 w-4 flex-shrink-0" />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-2">
        <NotificationBell notificationsPath={TENANT_ROUTES.notifications} />
        <button onClick={handleLogout} className="rounded-xl p-2 text-white/50 transition-colors hover:bg-white/10 hover:text-white">
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
