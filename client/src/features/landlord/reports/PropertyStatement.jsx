import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import ExportButtons from "@/components/ui/ExportButtons";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetPropertyStatementQuery } from "./reportApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function PropertyStatement({ properties = [] }) {
  const [propertyId, setPropertyId] = useState("");
  const [range, setRange] = useState({ date_from: "", date_to: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetPropertyStatementQuery(
    submitted ? { id: submitted.propertyId, ...submitted.range } : undefined,
    { skip: !submitted }
  );
  const rows = toRows(data);

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date) },
    { key: "tenant", header: "Tenant" },
    { key: "description", header: "Description" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
  ];

  return (
    <div className="glass space-y-4 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property"
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
          required
        />
        <DatePicker label="From" value={range.date_from} onChange={(e) => setRange((r) => ({ ...r, date_from: e.target.value }))} />
        <DatePicker label="To" value={range.date_to} onChange={(e) => setRange((r) => ({ ...r, date_to: e.target.value }))} />
        <Button className="self-end" disabled={!propertyId} onClick={() => setSubmitted({ propertyId, range })}>
          Generate
        </Button>
      </div>

      {submitted && (
        <>
          <ExportButtons endpoint={`/reports/statements/property/${submitted.propertyId}`} filenameBase="property-statement" params={submitted.range} />
          <ResponsiveTable columns={columns} rows={rows} isLoading={isFetching} />
        </>
      )}
    </div>
  );
}
