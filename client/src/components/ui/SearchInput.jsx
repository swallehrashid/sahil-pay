import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import clsx from "clsx";

/**
 * The search box above a list.
 *
 * Debounced, because it drives a server round-trip. A property manager here has
 * ~1,000 tenants; the search has to run in the database, not over the twenty
 * rows the page happens to be holding, or typing "Wanjiku" finds nobody unless
 * Wanjiku is already on screen — which is exactly when you would not be
 * searching.
 *
 * The caller passes `onSearch`, which fires with the settled term. Resetting to
 * page 1 is the caller's job: the current page number means nothing once the
 * result set has changed underneath it.
 */
export default function SearchInput({
  value = "",
  onSearch,
  placeholder = "Search…",
  delay = 300,
  className,
  resultCount,
  "aria-label": ariaLabel,
}) {
  const [text, setText] = useState(value);

  // Keep in step when the parent clears the term (a "reset filters" button).
  useEffect(() => { setText(value); }, [value]);

  useEffect(() => {
    if (text === value) return undefined;
    const timer = setTimeout(() => onSearch?.(text.trim()), delay);
    return () => clearTimeout(timer);
    // `value` is deliberately excluded: including it re-arms the timer on every
    // parent re-render and the search fires in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, delay]);

  const clear = () => {
    setText("");
    onSearch?.("");
  };

  return (
    <div className={clsx("relative w-full sm:max-w-xs", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" />
      <input
        type="search"
        role="searchbox"
        aria-label={ariaLabel || placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") clear();
          // Enter searches immediately rather than waiting out the debounce —
          // somebody who has finished typing and pressed Enter has told you so.
          if (e.key === "Enter") onSearch?.(text.trim());
        }}
        placeholder={placeholder}
        className="glass-input w-full py-2 pl-9 pr-9 text-sm"
      />
      {text && (
        <button
          type="button"
          onClick={clear}
          aria-label="Clear search"
          className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-white/40 transition-colors hover:text-secondary"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
      {value && resultCount !== undefined && (
        <p className="mt-1 text-xs text-white/40">
          {resultCount} result{resultCount === 1 ? "" : "s"} for “{value}”
        </p>
      )}
    </div>
  );
}
