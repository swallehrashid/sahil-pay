import clsx from "clsx";

// tabs: [{ key, label, count }]
export default function Tabs({ tabs = [], activeKey, onChange, className }) {
  return (
    <div className={clsx("no-scrollbar flex items-center gap-1 overflow-x-auto border-b border-white/10", className)}>
      {tabs.map((tab) => {
        const isActive = tab.key === activeKey;
        return (
          <button
            key={tab.key}
            type="button"
            data-tour={tab.dataTour}
            onClick={() => onChange?.(tab.key)}
            className={clsx(
              "relative flex items-center gap-2 whitespace-nowrap px-4 py-3 text-sm font-medium transition-colors duration-200",
              isActive ? "text-white" : "text-white/50 hover:text-white/80"
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="rounded-full bg-white/10 px-1.5 py-0.5 text-xs">{tab.count}</span>
            )}
            {isActive && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-secondary transition-all duration-300" />
            )}
          </button>
        );
      })}
    </div>
  );
}
