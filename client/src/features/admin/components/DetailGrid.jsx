// A labelled key/value grid rendered inside a glass card — the shared building
// block for every admin drill-down detail page. `items` is an array of
// { label, value } where value may be any renderable node (string, Badge, …).
export default function DetailGrid({ title, items }) {
  const visible = items.filter((i) => i && i.value !== undefined && i.value !== null && i.value !== "");
  if (!visible.length) return null;

  return (
    <div className="glass p-6">
      {title && <h3 className="mb-4 text-sm font-medium text-white/70">{title}</h3>}
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((item) => (
          <div key={item.label}>
            <dt className="text-xs uppercase tracking-wide text-white/40">{item.label}</dt>
            <dd className="mt-1 text-sm text-white">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
