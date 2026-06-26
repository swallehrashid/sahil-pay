import { ChevronLeft, ChevronRight } from "lucide-react";
import clsx from "clsx";

// Pairs with the backend's ?page/?per_page list params.
export default function Pagination({ page = 1, perPage = 20, total = 0, onPageChange }) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  if (totalPages <= 1) return null;

  const from = (page - 1) * perPage + 1;
  const to = Math.min(total, page * perPage);
  const pages = Array.from({ length: totalPages }, (_, i) => i + 1).filter(
    (p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1
  );

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm text-white/60">
      <span>
        Showing {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange?.(page - 1)}
          className="rounded-lg p-2 transition-colors hover:bg-white/10 disabled:pointer-events-none disabled:opacity-30"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        {pages.map((p, idx) => (
          <span key={p} className="flex items-center">
            {idx > 0 && pages[idx - 1] !== p - 1 && <span className="px-1 text-white/30">…</span>}
            <button
              type="button"
              onClick={() => onPageChange?.(p)}
              className={clsx(
                "h-8 min-w-8 rounded-lg px-2 transition-colors duration-200",
                p === page ? "bg-secondary text-white" : "hover:bg-white/10"
              )}
            >
              {p}
            </button>
          </span>
        ))}
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onPageChange?.(page + 1)}
          className="rounded-lg p-2 transition-colors hover:bg-white/10 disabled:pointer-events-none disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
