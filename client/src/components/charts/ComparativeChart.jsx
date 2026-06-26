import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";

const DEFAULT_SERIES = [
  { key: "current", label: "Current Period", color: "#B95F7B" },
  { key: "previous", label: "Previous Period", color: "#7A66CF" },
];

// §4.11 — month-on-month / year-on-year comparative report chart.
export default function ComparativeChart({ data = [], seriesKeys = DEFAULT_SERIES }) {
  return (
    <div className="glass animate-fade-in-up p-6">
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="label" stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <YAxis stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <Tooltip
            contentStyle={{ background: "#160653", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12 }}
            labelStyle={{ color: "#fff" }}
          />
          <Legend />
          {seriesKeys.map((series) => (
            <Line
              key={series.key}
              type="monotone"
              dataKey={series.key}
              name={series.label}
              stroke={series.color}
              strokeWidth={2}
              dot={{ r: 3 }}
              animationDuration={900}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
