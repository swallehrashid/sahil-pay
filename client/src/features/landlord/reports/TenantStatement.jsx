import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetTenantStatementQuery } from "./reportApiSlice";

// Tenant statement: transaction date, item, description, money due, money paid,
// running balance — generated on screen first, columns editable, then downloaded.
export default function TenantStatement({ tenants = [] }) {
  const [tenantId, setTenantId] = useState("");
  const [range, setRange] = useState({ start_date: "", end_date: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetTenantStatementQuery(
    submitted ? { id: submitted.tenantId, ...submitted.range } : undefined,
    { skip: !submitted }
  );

  return (
    <div className="glass space-y-6 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
          required
        />
        <DatePicker label="From" value={range.start_date} onChange={(e) => setRange((r) => ({ ...r, start_date: e.target.value }))} />
        <DatePicker label="To" value={range.end_date} onChange={(e) => setRange((r) => ({ ...r, end_date: e.target.value }))} />
        <Button className="self-end" disabled={!tenantId} onClick={() => setSubmitted({ tenantId, range })}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView
          document={data}
          endpoint={`/reports/statements/tenant/${submitted.tenantId}`}
          params={submitted.range}
          filenameBase="tenant-statement"
        />
      )}
    </div>
  );
}
