import { useEffect, useRef, useState } from "react";
import { MoreVertical } from "lucide-react";
import clsx from "clsx";

// Generic row-action menu. items: [{ label, icon, onClick, danger, disabled }]
// This is how the tenant's 11 row-actions (and similar lists elsewhere) are rendered.
export default function Dropdown({ items = [], trigger, align = "right" }) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setIsOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="rounded-lg p-1.5 text-white/50 transition-colors duration-200 hover:bg-white/10 hover:text-white"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        {trigger || <MoreVertical className="h-4 w-4" />}
      </button>

      {isOpen && (
        <div
          role="menu"
          className={clsx(
            "glass-dark absolute z-30 mt-2 w-52 origin-top animate-scale-in overflow-hidden p-1.5",
            align === "right" ? "right-0" : "left-0"
          )}
        >
          {items.map((item, index) => (
            <button
              key={item.label ?? index}
              type="button"
              role="menuitem"
              onClick={() => {
                setIsOpen(false);
                item.onClick?.();
              }}
              disabled={item.disabled}
              className={clsx(
                "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors duration-150",
                item.danger ? "text-secondary-300 hover:bg-secondary/15" : "text-white/80 hover:bg-white/10",
                item.disabled && "pointer-events-none opacity-40"
              )}
            >
              {item.icon && <span className="h-4 w-4">{item.icon}</span>}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
