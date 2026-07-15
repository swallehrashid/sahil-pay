import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { X } from "lucide-react";

// Renders ONLY the nav items it is given — each portal supplies its own list (already
// filtered through buildVisibleNav() for team members, so a hidden module never renders).
export default function Sidebar({ items = [], isMobileOpen, onCloseMobile, header, footer }) {
  return (
    <>
      {isMobileOpen && (
        <div className="fixed inset-0 z-40 bg-primary-950/70 backdrop-blur-sm lg:hidden" onClick={onCloseMobile} />
      )}
      <aside
        className={clsx(
          "glass-dark fixed inset-y-0 left-0 z-50 w-64 transform overflow-y-auto p-4 transition-transform duration-300 lg:translate-x-0",
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="mb-6 flex items-center justify-between px-2">
          {header ?? <span className="text-lg font-light tracking-wide text-white">SahilPay</span>}
          <button onClick={onCloseMobile} className="rounded-lg p-1 text-white/50 hover:bg-white/10 lg:hidden">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="space-y-1">
          {items.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              data-tour={item.dataTour}
              onClick={onCloseMobile}
              style={{ animationDelay: `${index * 50}ms` }}
              className={({ isActive }) =>
                clsx(
                  "flex animate-fade-in-up items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-200",
                  isActive ? "bg-secondary/20 text-white shadow-glow" : "text-white/60 hover:bg-white/5 hover:text-white"
                )
              }
            >
              {item.icon && <span className="h-4 w-4 flex-shrink-0">{item.icon}</span>}
              <span className="truncate">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {footer && <div className="mt-6 border-t border-white/10 pt-4">{footer}</div>}
      </aside>
    </>
  );
}
