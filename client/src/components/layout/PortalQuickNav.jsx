import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import clsx from "clsx";
import { Plus, LayoutDashboard, Wallet, Users, Menu } from "lucide-react";

// Two pieces of navigation that sit OUTSIDE the grouped sidebar:
//
//  <NewActionMenu>  "+ New" — the everyday create actions (record a payment,
//                   add a tenant, send a lease…) one tap away from anywhere,
//                   each opening its form directly. The fastest path to the
//                   task a landlord came to do, per Fitts's law: frequent
//                   actions close to where the pointer/thumb already is.
//
//  <PortalBottomBar> phones only: Home · Payments · + New · Tenants · Menu,
//                   under the thumb, like the M-Pesa and banking apps people
//                   already use. "Menu" opens the full grouped sidebar.

export function NewActionMenu({ actions, variant = "sidebar" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const { pathname, search } = useLocation();
  const [openedAt, setOpenedAt] = useState(null);
  const isOpen = open && openedAt === pathname + search;

  useEffect(() => {
    if (!isOpen) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [isOpen]);

  if (!actions.length) return null;
  const toggle = () => { setOpenedAt(pathname + search); setOpen((v) => !(v && isOpen)); };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        data-testid="new-action-button"
        className={clsx(
          "flex items-center justify-center gap-2 bg-secondary font-medium text-white shadow-lg shadow-secondary/30 transition-transform active:scale-95",
          variant === "sidebar" ? "w-full rounded-xl px-4 py-2.5 text-sm hover:bg-secondary-600" : "h-12 w-12 rounded-full"
        )}
      >
        <Plus className={clsx("h-5 w-5 transition-transform", isOpen && "rotate-45")} />
        {variant === "sidebar" && "New"}
      </button>
      {isOpen && (
        <div
          role="menu"
          className={clsx(
            "z-[60] w-64 animate-scale-in rounded-2xl border border-white/15 bg-primary-900 p-1.5 shadow-2xl shadow-black/50",
            variant === "sidebar" ? "absolute left-0 right-0 top-full mt-2 w-auto" : "fixed inset-x-3 bottom-[84px] w-auto"
          )}
        >
          {actions.map((a) => (
            <Link key={a.to} to={a.to} role="menuitem" onClick={() => setOpen(false)}
                  className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-white/80 hover:bg-white/10 hover:text-white">
              <a.icon className="h-4 w-4 text-secondary-200" /> {a.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function PortalBottomBar({ routes, actions, onOpenMenu, canView = () => true }) {
  const items = [
    { to: routes.dashboard, label: "Home", icon: LayoutDashboard, end: true },
    canView("payments") && { to: routes.payments, label: "Payments", icon: Wallet },
    canView("tenants") && { to: routes.tenants, label: "Tenants", icon: Users },
  ].filter(Boolean);

  const link = (item) => (
    <NavLink key={item.to} to={item.to} end={item.end}
             className={({ isActive }) => clsx("flex min-h-[60px] flex-col items-center justify-center gap-1 text-[11px] font-medium",
               isActive ? "text-white" : "text-white/55")}>
      {({ isActive }) => (
        <>
          <span className={clsx("rounded-full px-4 py-1", isActive && "bg-secondary/25")}><item.icon className="h-5 w-5" /></span>
          {item.label}
        </>
      )}
    </NavLink>
  );

  return (
    <nav aria-label="Quick navigation"
         className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-primary-900/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
      <div className="grid grid-cols-5 items-center">
        {items.slice(0, 2).map(link)}
        <div className="flex justify-center"><NewActionMenu actions={actions} variant="fab" /></div>
        {items[2] ? link(items[2]) : <span />}
        <button type="button" onClick={onOpenMenu}
                className="flex min-h-[60px] flex-col items-center justify-center gap-1 text-[11px] font-medium text-white/55"
                data-testid="bottom-menu-button">
          <span className="rounded-full px-4 py-1"><Menu className="h-5 w-5" /></span>
          Menu
        </button>
      </div>
    </nav>
  );
}
