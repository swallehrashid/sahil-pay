import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import { formatCompactCurrency } from "@/utils/currencyFormatter";

// §9.3 — monthly SMS reselling revenue vs SahilPay's platform cost. Two measures
// over discrete months → grouped bars; a legend distinguishes the two series.
export default function SmsRevenueCostChart({ data = [], title = "Revenue vs cost — by month" }) {
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
            formatter={(value, name) => [formatCompactCurrency(value), name]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "rgba(255,255,255,0.6)" }} />
          <Bar dataKey="revenue" name="Revenue" fill="#B95F7B" radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={800} />
          <Bar dataKey="cost" name="Platform cost" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={800} />
          <Bar dataKey="margin" name="Margin" fill="#34d399" radius={[4, 4, 0, 0]} maxBarSize={28} animationDuration={800} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
