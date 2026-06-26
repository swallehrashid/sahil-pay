import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import ExportButtons from "@/components/ui/ExportButtons";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetTenantStatementQuery } from "./reportApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// Transaction date + item, money due, money paid, running balance (§4.11).
export default function TenantStatement({ tenants = [] }) {
  const [tenantId, setTenantId] = useState("");
  const [range, setRange] = useState({ date_from: "", date_to: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetTenantStatementQuery(submitted ? { id: submitted.tenantId, ...submitted.range } : undefined, {
    skip: !submitted,
  });
  const rows = toRows(data);

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date) },
    { key: "item", header: "Item" },
    { key: "due", header: "Money due", render: (row) => formatCurrency(row.due) },
    { key: "paid", header: "Money paid", render: (row) => formatCurrency(row.paid) },
    { key: "balance", header: "Running balance", render: (row) => formatCurrency(row.running_balance) },
  ];

  return (
    <div className="glass space-y-4 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
          required
        />
        <DatePicker label="From" value={range.date_from} onChange={(e) => setRange((r) => ({ ...r, date_from: e.target.value }))} />
        <DatePicker label="To" value={range.date_to} onChange={(e) => setRange((r) => ({ ...r, date_to: e.target.value }))} />
        <Button className="self-end" disabled={!tenantId} onClick={() => setSubmitted({ tenantId, range })}>
          Generate
        </Button>
      </div>

      {submitted && (
        <>
          <ExportButtons endpoint={`/reports/statements/tenant/${submitted.tenantId}`} filenameBase="tenant-statement" params={submitted.range} />
          <ResponsiveTable columns={columns} rows={rows} isLoading={isFetching} />
        </>
      )}
    </div>
  );
}
