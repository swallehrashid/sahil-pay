import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetPropertyStatementQuery } from "./reportApiSlice";

// Property statement: four sections (tenants, expenses, occupancy, summary) with
// net-income roll-up. Generated on screen, columns editable, then downloaded.
export default function PropertyStatement({ properties = [] }) {
  const [propertyId, setPropertyId] = useState("");
  const [range, setRange] = useState({ start_date: "", end_date: "" });
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetPropertyStatementQuery(
    submitted ? { id: submitted.propertyId, ...submitted.range } : undefined,
    { skip: !submitted }
  );

  return (
    <div className="glass space-y-6 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property"
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
          required
        />
        <DatePicker label="From" value={range.start_date} onChange={(e) => setRange((r) => ({ ...r, start_date: e.target.value }))} />
        <DatePicker label="To" value={range.end_date} onChange={(e) => setRange((r) => ({ ...r, end_date: e.target.value }))} />
        <Button className="self-end" disabled={!propertyId} onClick={() => setSubmitted({ propertyId, range })}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView
          document={data}
          endpoint={`/reports/statements/property/${submitted.propertyId}`}
          params={submitted.range}
          filenameBase="property-statement"
        />
      )}
    </div>
  );
}
