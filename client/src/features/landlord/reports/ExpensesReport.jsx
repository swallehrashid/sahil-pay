import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import ExportButtons from "@/components/ui/ExportButtons";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetExpensesReportQuery } from "./reportApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function ExpensesReport({ properties = [] }) {
  const [filters, setFilters] = useState({ property_id: "", date_from: "", date_to: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetExpensesReportQuery(submitted, { skip: !submitted });
  const rows = toRows(data);

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.expense_date) },
    { key: "property", header: "Property" },
    { key: "category", header: "Category" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
  ];

  return (
    <div className="glass space-y-4 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property"
          value={filters.property_id}
          onChange={(e) => setFilters((f) => ({ ...f, property_id: e.target.value }))}
          placeholder="All properties"
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
        <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
        <Button className="self-end" onClick={() => setSubmitted(filters)}>
          Generate
        </Button>
      </div>

      {submitted && (
        <>
          <ExportButtons endpoint="/reports/statements/expenses" filenameBase="expenses-report" params={submitted} />
          <ResponsiveTable columns={columns} rows={rows} isLoading={isFetching} />
        </>
      )}
    </div>
  );
}
