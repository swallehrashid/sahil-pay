import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import { formatCompactCurrency } from "@/utils/currencyFormatter";

// §7.2 — monthly paid-subscription revenue for a single package. One measure over
// discrete months → bars. Single series, so the title names it (no legend needed).
export default function PackageRevenueChart({ data = [], title = "Revenue — last months" }) {
  return (
    <div className="glass animate-fade-in-up p-6">
      <h3 className="mb-4 text-base font-medium text-white">{title}</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis dataKey="month" stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <YAxis stroke="rgba(255,255,255,0.4)" fontSize={12} tickFormatter={(v) => formatCompactCurrency(v)} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            contentStyle={{ background: "#160653", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12 }}
            labelStyle={{ color: "#fff" }}
            formatter={(value, name) => [name === "revenue" ? formatCompactCurrency(value) : value, name === "revenue" ? "Revenue" : name]}
          />
          <Bar dataKey="revenue" name="Revenue" fill="#B95F7B" radius={[4, 4, 0, 0]} maxBarSize={48} animationDuration={800} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
