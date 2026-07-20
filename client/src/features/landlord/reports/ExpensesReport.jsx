import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetExpensesReportQuery } from "./reportApiSlice";

// Detailed expenses: date, property, unit, category, description, amount.
export default function ExpensesReport({ properties = [] }) {
  const [filters, setFilters] = useState({ property_id: "", start_date: "", end_date: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetExpensesReportQuery(submitted ?? undefined, { skip: !submitted });

  const cleaned = () =>
    Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== ""));

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
        <DatePicker label="From" value={filters.start_date} onChange={(e) => setFilters((f) => ({ ...f, start_date: e.target.value }))} />
        <DatePicker label="To" value={filters.end_date} onChange={(e) => setFilters((f) => ({ ...f, end_date: e.target.value }))} />
        <Button className="self-end" onClick={() => setSubmitted(cleaned())}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView document={data} endpoint="/reports/statements/expenses" params={submitted} filenameBase="expenses-report" />
      )}
    </div>
  );
}
