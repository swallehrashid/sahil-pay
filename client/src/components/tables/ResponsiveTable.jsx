import clsx from "clsx";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { SkeletonTableRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";

// CORE: renders a real <table> on desktop, a stacked card list on mobile. This is the
// only way the platform enforces zero horizontal scroll for dense financial tables —
// every data table on the platform goes through this component.
export default function ResponsiveTable({
  columns = [],
  rows = [],
  keyField = "id",
  rowActions,
  isLoading = false,
  emptyState,
  onRowClick,
}) {
  const isMobile = useIsMobile();

  if (isLoading) return <SkeletonTableRows columns={columns.length} />;
  if (!rows.length) {
    return emptyState ?? <EmptyState title="No records found" description="Try adjusting your filters." />;
  }

  if (isMobile) {
    return (
      <div className="space-y-3">
        {rows.map((row, index) => (
          <div
            key={row[keyField] ?? index}
            onClick={() => onRowClick?.(row)}
            style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
            className={clsx(
              "glass row-hover animate-fade-in-up space-y-2 p-4",
              onRowClick ? "cursor-pointer" : "cursor-default"
            )}
          >
            {columns.map((col) => (
              <div key={col.key} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-white/40">{col.header}</span>
                <span className="text-right text-white/90">{col.render ? col.render(row) : row[col.key]}</span>
              </div>
            ))}
            {rowActions && <div className="flex justify-end border-t border-white/10 pt-2">{rowActions(row)}</div>}
          </div>
        ))}
      </div>
    );
  }

  return (
    // #1 — min-w-0 lets this box shrink inside flex/grid ancestors so the page body
    // never scrolls sideways; .table-scroll forces an always-present horizontal bar.
    <div className="glass table-scroll max-h-[65vh] w-full min-w-0 max-w-full">
      <table className="min-w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-primary-800">
          <tr className="border-b border-white/10 text-white/40">
            {columns.map((col) => (
              <th key={col.key} className={clsx("whitespace-nowrap px-4 py-3 font-medium", col.className)}>
                {col.header}
              </th>
            ))}
            {rowActions && <th className="px-4 py-3" />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={row[keyField] ?? index}
              onClick={() => onRowClick?.(row)}
              style={{ animationDelay: `${Math.min(index, 10) * 50}ms` }}
              className={clsx(
                "row-hover animate-fade-in-up border-b border-white/5 last:border-0",
                onRowClick && "cursor-pointer"
              )}
            >
              {columns.map((col) => (
                <td key={col.key} className={clsx("whitespace-nowrap px-4 py-3 text-white/80", col.className)}>
                  {col.render ? col.render(row) : row[col.key]}
                </td>
              ))}
              {rowActions && (
                <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                  {rowActions(row)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
