import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useSelector } from "react-redux";
import clsx from "clsx";
import { X, ChevronDown } from "lucide-react";
import SahilPayLogo from "@/components/branding/SahilPayLogo";

// The portal sidebar — a SHORT list of groups, each opening to its pages.
//
// Twenty-odd flat links meant scanning the whole column to find "Leases". Items
// are now grouped by the job a landlord is doing (Money, Tenants, Properties,
// Messages, Reports), following established menu guidance:
//   • groups open on CLICK (not hover), with a caret and aria-expanded;
//   • the group holding the page you are on is open and marked, so "where am
//     I?" is always answered;
//   • labels are plain words, front-loaded, left-aligned;
//   • what you opened is remembered between visits.
// While a product tour runs, every group is open so the tour can point at any
// link inside one.
//
// An item is either a link { to, label, icon } or a group
// { key, label, icon, children: [links] }. Each portal passes its own list,
// already permission-filtered.

const STORAGE_KEY = "sahilpay_nav_open_groups";

function readOpen() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function writeOpen(value) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch { /* private mode — just not remembered */ }
}

function isUnder(pathname, to, end) {
  if (!to) return false;
  return end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
}

function LinkRow({ item, onNavigate, nested = false }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      data-tour={item.dataTour}
      onClick={onNavigate}
      className={({ isActive }) =>
        clsx(
          "flex items-center gap-3 rounded-xl text-sm transition-colors duration-200",
          nested ? "py-2 pl-10 pr-3" : "px-3 py-2.5",
          isActive ? "bg-secondary/20 text-white shadow-glow" : "text-white/65 hover:bg-white/5 hover:text-white"
        )
      }
    >
      {!nested && item.icon && <span className="h-4 w-4 flex-shrink-0">{item.icon}</span>}
      <span className="flex-1 truncate">{item.label}</span>
      {item.badge ? (
        <span className="min-w-[20px] rounded-full bg-secondary px-1.5 text-center text-[11px] font-semibold leading-5 text-white">
          {item.badge > 99 ? "99+" : item.badge}
        </span>
      ) : null}
    </NavLink>
  );
}

export default function Sidebar({ items = [], isMobileOpen, onCloseMobile, header, footer, topSlot }) {
  const { pathname } = useLocation();
  const tourActive = useSelector((s) => Boolean(s.tour?.activeTutorialId));
  const [open, setOpen] = useState(readOpen);

  const toggle = (key, currentlyOpen) => {
    setOpen((prev) => {
      const next = { ...prev, [key]: !currentlyOpen };
      writeOpen(next);
      return next;
    });
  };

  return (
    <>
      {isMobileOpen && (
        <div className="fixed inset-0 z-40 bg-primary-950/70 backdrop-blur-sm lg:hidden" onClick={onCloseMobile} />
      )}
      <aside
        className={clsx(
          "glass-dark fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] transform flex-col overflow-y-auto p-4 transition-transform duration-300 lg:w-64 lg:translate-x-0",
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Main navigation"
      >
        <div className="mb-5 flex items-center justify-between px-2">
          {header ?? <SahilPayLogo withSlogan={false} className="h-7 text-white" />}
          <button onClick={onCloseMobile} className="rounded-lg p-1 text-white/50 hover:bg-white/10 lg:hidden" aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>

        {topSlot && <div className="mb-4">{topSlot}</div>}

        <nav className="flex-1 space-y-1">
          {items.map((item) => {
            if (!item.children) return <LinkRow key={item.to} item={item} onNavigate={onCloseMobile} />;

            const containsActive = item.children.some((c) => isUnder(pathname, c.to, c.end));
            const isOpen = tourActive || containsActive || Boolean(open[item.key]);
            const badge = item.children.reduce((sum, c) => sum + (c.badge || 0), 0);
            const panelId = `nav-group-${item.key}`;
            return (
              <div key={item.key}>
                <button
                  type="button"
                  onClick={() => toggle(item.key, isOpen)}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  data-tour={item.dataTour}
                  data-testid={`nav-group-${item.key}`}
                  className={clsx(
                    "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors duration-200",
                    containsActive ? "text-white" : "text-white/65 hover:bg-white/5 hover:text-white"
                  )}
                >
                  <span className={clsx("h-4 w-4 flex-shrink-0", containsActive && "text-secondary-200")}>{item.icon}</span>
                  <span className="flex-1 truncate font-medium">{item.label}</span>
                  {!isOpen && badge > 0 && (
                    <span className="min-w-[20px] rounded-full bg-secondary px-1.5 text-center text-[11px] font-semibold leading-5 text-white">
                      {badge > 99 ? "99+" : badge}
                    </span>
                  )}
                  <ChevronDown className={clsx("h-4 w-4 flex-shrink-0 text-white/40 transition-transform duration-200", isOpen && "rotate-180")} />
                </button>
                {isOpen && (
                  <div id={panelId} className="relative mt-0.5 space-y-0.5 before:absolute before:bottom-2 before:left-[1.4rem] before:top-1 before:w-px before:bg-white/10">
                    {item.children.map((child) => (
                      <LinkRow key={child.to} item={child} onNavigate={onCloseMobile} nested />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {footer && <div className="mt-6 border-t border-white/10 pt-4">{footer}</div>}
      </aside>
    </>
  );
}
