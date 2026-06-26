import { useState } from "react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import ExportButtons from "@/components/ui/ExportButtons";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetGroupingReportQuery } from "./reportApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function GroupingReport({ groups = [] }) {
  const [groupId, setGroupId] = useState("");
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetGroupingReportQuery(submitted ? { id: submitted } : undefined, { skip: !submitted });
  const rows = toRows(data);

  const columns = [
    { key: "property", header: "Property" },
    { key: "collected", header: "Collected", render: (row) => formatCurrency(row.collected) },
    { key: "arrears", header: "Arrears", render: (row) => formatCurrency(row.arrears) },
    { key: "occupancy", header: "Occupancy", render: (row) => `${row.occupancy_rate ?? 0}%` },
  ];

  return (
    <div className="glass space-y-4 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select label="Property group" value={groupId} onChange={(e) => setGroupId(e.target.value)} options={groups.map((g) => ({ value: g.id, label: g.name }))} required />
        <Button className="self-end" disabled={!groupId} onClick={() => setSubmitted(groupId)}>
          Generate
        </Button>
      </div>

      {submitted && (
        <>
          <ExportButtons endpoint={`/reports/statements/grouping/${submitted}`} filenameBase="grouping-report" />
          <ResponsiveTable columns={columns} rows={rows} isLoading={isFetching} />
        </>
      )}
    </div>
  );
}
