import {
  forwardRef, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Search } from "lucide-react";
import clsx from "clsx";

/**
 * A searchable, scrollable select. Drop-in replacement for the native one.
 *
 * WHY THIS IS NOT A <select>
 * --------------------------
 * A property manager on this platform has 100 properties, 1,000 units and
 * 1,000 tenants. A native <select> with a thousand <option>s can be scrolled
 * and nothing else: there is no way to find "Riverside Block C" except by
 * dragging a scrollbar past nine hundred other names. Every dropdown in the
 * app therefore filters as you type.
 *
 * The search box is shown on EVERY dropdown, not only long ones. A threshold
 * ("show it once there are more than eight options") reads as tidier and is
 * worse: the same control behaves differently depending on data you cannot see
 * from the outside, so you never learn whether typing will work, and a list
 * that is short today is long once the account has real data in it.
 *
 * THE API IS DELIBERATELY UNCHANGED
 * ---------------------------------
 * 131 call sites pass `onChange={(e) => set(e.target.value)}` and read a
 * STRING, because that is what a native select gives them. This emits the same
 * shape, with the value stringified, so no caller has to change and no form
 * quietly starts receiving numbers where it used to get strings.
 *
 * The panel is rendered through a portal. Every data table wraps itself in an
 * `overflow-x-auto` container for horizontal scrolling, and an absolutely
 * positioned child of one of those is clipped no matter what its z-index says
 * — the same reason Dropdown.jsx portals its menu.
 *
 * A real <select> is kept underneath, transparent and click-through, so
 * `required` still blocks a submit the way it always has and the field is still
 * a form control. Losing that quietly would turn "you must pick a property"
 * into a silent empty submit.
 */

const PANEL_MAX_HEIGHT = 288;   // ~8 rows; the list scrolls past that
const ROW_HEIGHT = 36;

const Select = forwardRef(function Select(
  {
    label, error, hint, options = [], placeholder = "Select…", className, id, required,
    searchPlaceholder = "Type to search…",
    emptyMessage = "Nothing matches that.",
    value, onChange, name, disabled, ...props
  },
  ref
) {
  const reactId = useId();
  const selectId = id || name || `select-${reactId}`;
  const listboxId = `${selectId}-listbox`;

  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [coords, setCoords] = useState(null);

  const triggerRef = useRef(null);
  const panelRef = useRef(null);
  const searchRef = useRef(null);
  const listRef = useRef(null);

  // Values arrive as numbers as often as strings (`value={p.id}`), and a native
  // select compares them as strings. Match that, or selecting unit 7 fails to
  // highlight the option whose value is the number 7.
  const asKey = (v) => (v === null || v === undefined ? "" : String(v));
  const currentKey = asKey(value);

  const selected = useMemo(
    () => options.find((o) => asKey(o.value) === currentKey),
    [options, currentKey]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => String(o.label ?? o.value ?? "").toLowerCase().includes(q));
  }, [options, query]);

  const place = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const GAP = 6;
    const MARGIN = 8;
    const spaceBelow = window.innerHeight - rect.bottom - GAP - MARGIN;
    const spaceAbove = rect.top - GAP - MARGIN;
    // Prefer downward; flip only when there is clearly more room above, so a
    // dropdown near the bottom of a long form is not cut off by the viewport.
    const openUp = spaceBelow < Math.min(PANEL_MAX_HEIGHT, 200) && spaceAbove > spaceBelow;
    const maxHeight = Math.max(Math.min(PANEL_MAX_HEIGHT, openUp ? spaceAbove : spaceBelow), 160);
    setCoords({
      left: Math.max(MARGIN, Math.min(rect.left, window.innerWidth - rect.width - MARGIN)),
      width: rect.width,
      maxHeight,
      ...(openUp ? { bottom: window.innerHeight - rect.top + GAP } : { top: rect.bottom + GAP }),
    });
  }, []);

  useLayoutEffect(() => {
    if (isOpen) place();
  }, [isOpen, place]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onDocMouseDown = (e) => {
      if (triggerRef.current?.contains(e.target) || panelRef.current?.contains(e.target)) return;
      setIsOpen(false);
    };
    // An ancestor scrolling invalidates the fixed coordinates. Reposition rather
    // than close: closing on scroll makes the control feel broken on a long form.
    const onScroll = (e) => {
      if (panelRef.current?.contains(e.target)) return;
      place();
    };
    document.addEventListener("mousedown", onDocMouseDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
  }, [isOpen, place]);

  // Opening lands on the current selection, so Enter without typing is a no-op
  // rather than silently changing the value to whatever is first in the list.
  const open = () => {
    if (disabled) return;
    setQuery("");
    const at = filtered.findIndex((o) => asKey(o.value) === currentKey);
    setActiveIndex(at >= 0 ? at : 0);
    setIsOpen(true);
    requestAnimationFrame(() => searchRef.current?.focus());
  };

  const close = ({ refocus = true } = {}) => {
    setIsOpen(false);
    setQuery("");
    if (refocus) triggerRef.current?.focus();
  };

  const commit = (option) => {
    // The same shape a native select emits, so every existing
    // `onChange={(e) => set(e.target.value)}` keeps working untouched.
    onChange?.({ target: { value: asKey(option.value), name: name ?? selectId } });
    close();
  };

  const onTriggerKeyDown = (e) => {
    if (disabled) return;
    if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      open();
    }
  };

  const onSearchKeyDown = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Tab") {
      close({ refocus: false });
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!filtered.length) return;
      setActiveIndex((i) => {
        const next = e.key === "ArrowDown" ? i + 1 : i - 1;
        return (next + filtered.length) % filtered.length;
      });
      return;
    }
    if (e.key === "Home") { e.preventDefault(); setActiveIndex(0); return; }
    if (e.key === "End") { e.preventDefault(); setActiveIndex(filtered.length - 1); return; }
    if (e.key === "Enter") {
      e.preventDefault();
      const option = filtered[activeIndex];
      if (option) commit(option);
    }
  };

  // Keep the highlighted row in view while arrowing through a thousand units.
  useEffect(() => {
    if (!isOpen || !listRef.current) return;
    const row = listRef.current.children[activeIndex];
    row?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, isOpen]);

  useEffect(() => { setActiveIndex(0); }, [query]);

  return (
    <div className="w-full">
      {label && (
        <label htmlFor={selectId} className="mb-1.5 block text-sm font-medium text-white/70">
          {label} {required && <span className="text-secondary">*</span>}
        </label>
      )}

      <div className="relative">
        <button
          {...props}
          ref={(node) => {
            triggerRef.current = node;
            if (typeof ref === "function") ref(node);
            else if (ref) ref.current = node;
          }}
          id={selectId}
          type="button"
          role="combobox"
          aria-haspopup="listbox"
          aria-expanded={isOpen}
          aria-controls={isOpen ? listboxId : undefined}
          aria-invalid={Boolean(error) || undefined}
          disabled={disabled}
          onClick={() => (isOpen ? close() : open())}
          onKeyDown={onTriggerKeyDown}
          className={clsx(
            "glass-input flex w-full items-center justify-between gap-2 pr-10 text-left",
            error && "border-b-secondary",
            disabled && "cursor-not-allowed opacity-50",
            className
          )}
        >
          <span className={clsx("truncate", !selected && "text-white/40")}>
            {selected ? selected.label : placeholder}
          </span>
        </button>
        <ChevronDown
          className={clsx(
            "pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/40 transition-transform",
            isOpen && "rotate-180"
          )}
        />

        {/*
          The real form control, transparent and click-through, laid exactly over
          the trigger. It is what makes `required` still block a submit and what
          puts the browser's own validation bubble in the right place. Clicks
          pass through to the button above it; tabbing skips it so keyboard users
          reach the combobox instead.
        */}
        <select
          aria-hidden="true"
          tabIndex={-1}
          name={name}
          required={required}
          disabled={disabled}
          value={currentKey}
          onChange={(e) => onChange?.(e)}
          className="pointer-events-none absolute inset-0 h-full w-full opacity-0"
        >
          <option value="" />
          {options.map((o) => (
            <option key={asKey(o.value)} value={asKey(o.value)}>{o.label}</option>
          ))}
        </select>
      </div>

      {hint && !error && <p className="mt-1 text-xs text-white/40">{hint}</p>}
      {error && <p className="mt-1 text-xs text-secondary-300">{error}</p>}

      {isOpen && coords && createPortal(
        <div
          ref={panelRef}
          style={{
            position: "fixed", left: coords.left, width: coords.width,
            ...(coords.top !== undefined ? { top: coords.top } : { bottom: coords.bottom }),
            maxHeight: coords.maxHeight,
            // Set here rather than as a utility class: glass-dark already
            // declares bg-primary-900/40, and two classes from the same utility
            // family are decided by stylesheet order, not the order they appear
            // in the attribute — so the override lost. At 40% the form labels
            // underneath read straight through the panel and the options become
            // genuinely hard to pick out.
            backgroundColor: "rgb(15 2 70 / 0.97)",
          }}
          className="glass-dark z-[60] flex origin-top animate-scale-in flex-col overflow-hidden p-1.5"
        >
          <div className="relative mb-1.5 flex-shrink-0">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-white/35" />
            <input
              ref={searchRef}
              type="text"
              role="searchbox"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKeyDown}
              placeholder={searchPlaceholder}
              aria-label={`Search ${label || "options"}`}
              aria-controls={listboxId}
              className="w-full rounded-lg bg-white/5 py-1.5 pl-8 pr-2 text-sm text-white placeholder-white/30 outline-none ring-1 ring-white/10 focus:ring-secondary/50"
            />
          </div>

          <ul
            ref={listRef}
            id={listboxId}
            role="listbox"
            aria-label={label || "Options"}
            className="min-h-0 overflow-y-auto overscroll-contain"
          >
            {filtered.map((option, index) => {
              const key = asKey(option.value);
              const isSelected = key === currentKey;
              return (
                <li
                  key={key}
                  role="option"
                  aria-selected={isSelected}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => commit(option)}
                  style={{ minHeight: ROW_HEIGHT }}
                  className={clsx(
                    "flex cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
                    index === activeIndex ? "bg-white/10 text-white" : "text-white/75",
                    isSelected && "text-secondary-200"
                  )}
                >
                  <span className="truncate">{option.label}</span>
                  {isSelected && <Check className="h-3.5 w-3.5 flex-shrink-0" />}
                </li>
              );
            })}
            {!filtered.length && (
              <li className="px-3 py-4 text-center text-xs text-white/40">{emptyMessage}</li>
            )}
          </ul>

          {options.length > 0 && (
            <p className="flex-shrink-0 border-t border-white/10 px-3 pt-1.5 text-[10px] text-white/30">
              {filtered.length} of {options.length}
            </p>
          )}
        </div>,
        document.body
      )}
    </div>
  );
});

export default Select;
