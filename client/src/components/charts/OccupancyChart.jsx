import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell } from "recharts";

// §4.12 — occupancy rate per property; bar color flags properties losing rent to vacancy.
export default function OccupancyChart({ data = [] }) {
  return (
    <div className="glass animate-fade-in-up p-6">
      <h3 className="mb-4 text-base font-medium text-white">Occupancy by Property</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="property" stroke="rgba(255,255,255,0.4)" fontSize={12} />
          <YAxis stroke="rgba(255,255,255,0.4)" fontSize={12} unit="%" />
          <Tooltip
            contentStyle={{ background: "#160653", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12 }}
            labelStyle={{ color: "#fff" }}
            formatter={(value, _name, item) => [`${value}%`, `Vacant units: ${item.payload.unoccupiedUnits ?? 0}`]}
          />
          <Bar dataKey="occupancyRate" name="Occupancy" radius={[8, 8, 0, 0]} animationDuration={900}>
            {data.map((entry, index) => (
              <Cell key={index} fill={entry.occupancyRate >= 80 ? "#34d399" : entry.occupancyRate >= 50 ? "#B95F7B" : "#fb7185"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
