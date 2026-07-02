import { useState } from "react";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetMonthOnMonthReportQuery } from "./reportApiSlice";

// Month-on-month comparative: one row per month across occupancy, rent, water,
// bills, paid, % paid and expenses — each metric also plotted as a graph.
export default function MonthOnMonthReport({ properties = [] }) {
  const [filters, setFilters] = useState({ property_id: "", year: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetMonthOnMonthReportQuery(submitted ?? undefined, { skip: !submitted });

  const cleaned = () => Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ""));

  return (
    <div className="glass space-y-6 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property (optional)"
          value={filters.property_id}
          onChange={(e) => setFilters((f) => ({ ...f, property_id: e.target.value }))}
          placeholder="All properties"
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Input label="Year (optional)" type="number" placeholder="e.g. 2026" value={filters.year} onChange={(e) => setFilters((f) => ({ ...f, year: e.target.value }))} />
        <Button className="self-end" onClick={() => setSubmitted(cleaned())}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView document={data} endpoint="/reports/statements/month-on-month" params={submitted} filenameBase="month-on-month-report" />
      )}
    </div>
  );
}
