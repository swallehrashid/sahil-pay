import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";

// §4.1 — three-series graph: payments made, invoices made, expenses incurred (last month).
export default function PerformanceChart({ data = [] }) {
  return (
    <div className="glass animate-fade-in-up p-6">
      <h3 className="mb-4 text-base font-medium text-white">Performance — Last 30 Days</h3>
      <ResponsiveContainer width="100%" height={300}>
        <AreaChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <defs>
            <linearGradient id="payments" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#B95F7B" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#B95F7B" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="invoices" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#7A66CF" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#7A66CF" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="expenses" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ffffff" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#ffffff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="label" stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <YAxis stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <Tooltip
            contentStyle={{ background: "#160653", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12 }}
            labelStyle={{ color: "#fff" }}
          />
          <Legend />
          <Area type="monotone" dataKey="payments" name="Payments" stroke="#B95F7B" fill="url(#payments)" strokeWidth={2} animationDuration={900} />
          <Area type="monotone" dataKey="invoices" name="Invoices" stroke="#7A66CF" fill="url(#invoices)" strokeWidth={2} animationDuration={900} />
          <Area type="monotone" dataKey="expenses" name="Expenses" stroke="#ffffff" fill="url(#expenses)" strokeWidth={2} animationDuration={900} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
