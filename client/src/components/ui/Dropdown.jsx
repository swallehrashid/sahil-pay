import { cloneElement, isValidElement, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MoreVertical } from "lucide-react";
import clsx from "clsx";

const MENU_WIDTH = 208; // w-52
const EST_ITEM_HEIGHT = 40;

// Generic row-action menu. items: [{ label, icon, onClick, danger, disabled }]
// This is how every table's row actions (landlord, team member, admin, tenant) render.
//
// The menu portals into document.body instead of living inside the table's DOM
// position. Every ResponsiveTable wraps its <table> in an `overflow-x-auto`
// container (needed for horizontal scroll on dense tables) — any descendant
// positioned absolutely inside that container gets clipped/painted-under later
// rows regardless of z-index, since overflow != visible turns the ancestor into
// a clipping box. Rendering the menu into a portal, positioned with `fixed`
// coordinates taken from the trigger button's own bounding rect, escapes that
// clipping container entirely so the menu always paints above the table.
export default function Dropdown({ items = [], trigger, align = "right" }) {
  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState(null);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);

  const close = useCallback(() => setIsOpen(false), []);

  const place = useCallback(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const GAP = 8;
    const MARGIN = 8; // keep the menu at least this far from every viewport edge
    const fullHeight = items.length * EST_ITEM_HEIGHT + 12;
    const spaceBelow = window.innerHeight - rect.bottom - GAP - MARGIN;
    const spaceAbove = rect.top - GAP - MARGIN;
    // Prefer opening downward; flip up only when there's clearly more room above.
    const openUpward = spaceBelow < fullHeight && spaceAbove > spaceBelow;
    const available = openUpward ? spaceAbove : spaceBelow;
    // #3 — cap the menu to the space available (floor ~160px) so a tall menu on a
    // short viewport is never cut off the screen; it scrolls internally instead.
    const maxHeight = Math.max(Math.min(fullHeight, available), 160);
    const renderedHeight = Math.min(fullHeight, maxHeight);

    let top = openUpward ? rect.top - GAP - renderedHeight : rect.bottom + GAP;
    let left = align === "right" ? rect.right - MENU_WIDTH : rect.left;
    // Clamp fully inside the viewport in both axes.
    top = Math.max(MARGIN, Math.min(top, window.innerHeight - renderedHeight - MARGIN));
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - MENU_WIDTH - MARGIN));

    setCoords({ top, left, maxHeight });
  }, [align, items.length]);

  useEffect(() => {
    if (!isOpen) return undefined;
    place();

    function handleClickOutside(e) {
      if (buttonRef.current?.contains(e.target) || menuRef.current?.contains(e.target)) return;
      close();
    }
    function handleKeyDown(e) {
      if (e.key === "Escape") close();
    }
    // Any ancestor scrolling (including the table's own horizontal scroll
    // container) invalidates the computed position — close rather than track it.
    // But scrolling INSIDE the menu itself (a tall menu that overflows) must NOT
    // close it, so ignore scroll events originating within the menu. (#3)
    function handleScroll(e) {
      if (menuRef.current?.contains(e.target)) return;
      close();
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", close);
    };
  }, [isOpen, close, place]);

  const toggle = () => setIsOpen((open) => !open);

  // When the caller supplies their own <Button> as the trigger, ADOPT it rather
  // than wrapping it: wrapping produced <button><button>…</button></button>,
  // which is invalid HTML that React warns about and browsers recover from
  // unpredictably (a nested button is not reliably clickable). Cloning attaches
  // the ref and the toggle to the caller's element, so the markup stays flat
  // and the caller keeps their own styling. The bare-icon default still needs a
  // real button of its own.
  const triggerNode = isValidElement(trigger)
    ? cloneElement(trigger, {
        ref: buttonRef,
        onClick: (event) => {
          trigger.props?.onClick?.(event);
          toggle();
        },
        "aria-haspopup": "menu",
        "aria-expanded": isOpen,
      })
    : (
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        className="rounded-lg p-1.5 text-white/50 transition-colors duration-200 hover:bg-white/10 hover:text-white"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        {trigger || <MoreVertical className="h-4 w-4" />}
      </button>
    );

  return (
    <>
      {triggerNode}

      {isOpen && coords &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            style={{ position: "fixed", top: coords.top, left: coords.left, width: MENU_WIDTH, maxHeight: coords.maxHeight }}
            className="glass-dark z-50 origin-top animate-scale-in overflow-y-auto overscroll-contain p-1.5"
          >
            {items.map((item, index) => (
              <button
                key={item.label ?? index}
                type="button"
                role="menuitem"
                onClick={() => {
                  close();
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
          </div>,
          document.body
        )}
    </>
  );
}
