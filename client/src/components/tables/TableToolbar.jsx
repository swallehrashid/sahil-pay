export default function TableToolbar({ title, subtitle, actions, bulkActions, selectedCount = 0 }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 pb-4">
      <div>
        {title && <h3 className="text-base font-medium text-white">{title}</h3>}
        {subtitle && <p className="text-sm text-white/50">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {selectedCount > 0 && bulkActions && (
          <div className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-1.5 text-sm text-white/70">
            <span>{selectedCount} selected</span>
            {bulkActions}
          </div>
        )}
        {actions}
      </div>
    </div>
  );
}
