import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Wallet, FileText, Wrench, MessageSquare, User, LogOut, BookOpen,
  ScrollText, MoreHorizontal, X,
} from "lucide-react";
import clsx from "clsx";
import { TENANT_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";
import NotificationBell from "@/features/notifications/NotificationBell";
import SahilPayLogo, { SahilPayMark } from "@/components/branding/SahilPayLogo";
import { useGetPortalLeasesQuery } from "@/features/landlord/leases/leaseApiSlice";

// Tenant navigation, mobile first.
//
// PHONE (<768px): a fixed bottom tab bar — Home, Pay, Leases, Statement, More —
// sitting under the thumb, the pattern every banking and M-Pesa app uses. The
// four things tenants do most are one tap away with a label each; the rest live
// in "More". This replaces a sideways-scrolling strip in the header where the
// Lease link sat off the right edge of the screen: a lease could be sent and
// the tenant would never find it.
//
// TABLET / LAPTOP / TV: every destination is in the header, labelled.
//
// Leases carries a badge with how many agreements wait on the tenant.

const PRIMARY = [
  { to: TENANT_ROUTES.dashboard, label: "Home", icon: LayoutDashboard },
  { to: TENANT_ROUTES.pay, label: "Pay", icon: Wallet },
  { to: TENANT_ROUTES.leases, label: "Leases", icon: ScrollText, badge: "leases" },
  { to: TENANT_ROUTES.statement, label: "Statement", icon: FileText },
];

const SECONDARY = [
  { to: TENANT_ROUTES.maintenance, label: "Maintenance", icon: Wrench },
  { to: TENANT_ROUTES.messages, label: "Messages", icon: MessageSquare },
  { to: TENANT_ROUTES.help, label: "Guides", icon: BookOpen },
  { to: TENANT_ROUTES.profile, label: "Profile", icon: User },
];

function Badge({ count }) {
  if (!count) return null;
  return (
    <span
      className="absolute -right-2 -top-1.5 min-w-[18px] rounded-full bg-secondary px-1 text-center text-[10px] font-semibold leading-[18px] text-white ring-2 ring-primary-900"
      aria-label={`${count} waiting`}
    >
      {count > 9 ? "9+" : count}
    </span>
  );
}

export default function TenantNavbar() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // Remember WHERE the sheet was opened; navigating anywhere closes it without
  // an effect (the "More" sheet only counts as open on the page it opened on).
  const [moreOpenAt, setMoreOpenAt] = useState(null);
  const moreOpen = moreOpenAt === location.pathname;
  const setMoreOpen = (open) => setMoreOpenAt(open ? location.pathname : null);
  const { data: leaseData } = useGetPortalLeasesQuery(undefined, { pollingInterval: 60000 });
  const counts = { leases: leaseData?.action_needed ?? 0 };

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.tenantLogin);
  };

  const moreActive = SECONDARY.some((l) => location.pathname.startsWith(l.to));

  return (
    <>
      <header className="glass sticky top-3 z-30 mx-3 mt-3 flex items-center justify-between gap-3 rounded-2xl px-3 py-2.5 sm:mx-4 sm:px-5 lg:mx-auto lg:max-w-7xl">
        <span className="text-white">
          <SahilPayLogo withSlogan={false} className="hidden h-7 md:flex lg:h-8" />
          <SahilPayMark className="h-7 md:hidden" />
        </span>

        <nav aria-label="Tenant portal" className="hidden min-w-0 flex-1 items-center justify-center gap-0.5 md:flex lg:gap-1">
          {[...PRIMARY, ...SECONDARY].map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                clsx(
                  "relative flex items-center gap-2 whitespace-nowrap rounded-xl px-2.5 py-2 text-sm transition-colors lg:px-3",
                  isActive ? "bg-secondary/20 text-white" : "text-white/65 hover:bg-white/5 hover:text-white"
                )
              }
            >
              <span className="relative">
                <link.icon className="h-4 w-4" />
                {link.badge && <Badge count={counts[link.badge]} />}
              </span>
              <span className="hidden lg:inline">{link.label}</span>
              <span className="lg:hidden">{link.label === "Maintenance" ? "Repairs" : link.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center gap-1.5">
          <NotificationBell notificationsPath={TENANT_ROUTES.notifications} />
          <button
            onClick={handleLogout}
            className="rounded-xl p-2 text-white/55 transition-colors hover:bg-white/10 hover:text-white"
            aria-label="Log out"
            title="Log out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </header>

      {/* Phone: bottom tab bar */}
      <nav
        aria-label="Tenant portal"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-primary-900/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
      >
        <ul className="grid grid-cols-5">
          {PRIMARY.map((link) => (
            <li key={link.to}>
              <NavLink
                to={link.to}
                className={({ isActive }) =>
                  clsx(
                    "flex min-h-[60px] flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors",
                    isActive ? "text-white" : "text-white/55"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={clsx("relative rounded-full px-4 py-1", isActive && "bg-secondary/25")}>
                      <link.icon className="h-5 w-5" />
                      {link.badge && <Badge count={counts[link.badge]} />}
                    </span>
                    {link.label}
                  </>
                )}
              </NavLink>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              aria-expanded={moreOpen}
              className={clsx(
                "flex min-h-[60px] w-full flex-col items-center justify-center gap-1 text-[11px] font-medium",
                moreActive ? "text-white" : "text-white/55"
              )}
            >
              <span className={clsx("rounded-full px-4 py-1", moreActive && "bg-secondary/25")}>
                <MoreHorizontal className="h-5 w-5" />
              </span>
              More
            </button>
          </li>
        </ul>
      </nav>

      {moreOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="More">
          <button className="absolute inset-0 bg-primary-950/70 backdrop-blur-sm" aria-label="Close" onClick={() => setMoreOpen(false)} />
          <div className="glass-dark absolute inset-x-0 bottom-0 animate-fade-in-up rounded-b-none rounded-t-3xl p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-medium text-white">More</p>
              <button onClick={() => setMoreOpen(false)} className="rounded-lg p-1.5 text-white/60 hover:bg-white/10" aria-label="Close">
                <X className="h-5 w-5" />
              </button>
            </div>
            <ul className="grid grid-cols-2 gap-2">
              {SECONDARY.map((link) => (
                <li key={link.to}>
                  <NavLink
                    to={link.to}
                    className={({ isActive }) =>
                      clsx("flex items-center gap-3 rounded-2xl border px-4 py-3.5 text-sm",
                        isActive ? "border-secondary bg-secondary/15 text-white" : "border-white/10 bg-white/5 text-white/80")
                    }
                  >
                    <link.icon className="h-5 w-5" /> {link.label}
                  </NavLink>
                </li>
              ))}
              <li className="col-span-2">
                <button onClick={handleLogout} className="flex w-full items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3.5 text-sm text-white/80">
                  <LogOut className="h-5 w-5" /> Log out
                </button>
              </li>
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
