import { useNavigate } from "react-router-dom";
import { Settings2 } from "lucide-react";
import OccupancyChart from "@/components/charts/OccupancyChart";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import ExportButtons from "@/components/ui/ExportButtons";
import { useGetOccupancyInsightsQuery } from "./reportApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

// §4.12 — occupancy rate, days unoccupied and estimated lost rent, filterable by property.
export default function OccupancyInsights({ propertyId }) {
  const navigate = useNavigate();
  const { data, isLoading } = useGetOccupancyInsightsQuery({ property_id: propertyId });
  const rows = toRows(data);

  const columns = [
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "rent_amount", header: "Rent amount", render: (row) => formatCurrency(row.rent_amount) },
    { key: "days_unoccupied", header: "Days unoccupied" },
    { key: "lost_rent", header: "Estimated lost rent", render: (row) => formatCurrency(row.estimated_lost_rent) },
  ];

  return (
    <div className="space-y-6">
      <OccupancyChart data={data?.chart ?? []} />
      <div className="flex justify-end">
        <ExportButtons endpoint="/reports/insights/occupancy" filenameBase="occupancy-insights" params={{ property_id: propertyId }} />
      </div>
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowActions={() => (
          <button
            onClick={() => navigate(LANDLORD_ROUTES.properties)}
            className="rounded-lg p-1.5 text-white/50 transition-colors hover:bg-white/10 hover:text-white"
          >
            <Settings2 className="h-4 w-4" />
          </button>
        )}
      />
    </div>
  );
}
