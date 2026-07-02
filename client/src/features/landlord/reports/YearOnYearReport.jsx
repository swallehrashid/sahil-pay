import { useState } from "react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetYearOnYearReportQuery } from "./reportApiSlice";

// Year-on-year comparative: same metrics as month-on-month, bucketed by year,
// each with a graph.
export default function YearOnYearReport({ properties = [] }) {
  const [propertyId, setPropertyId] = useState("");
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetYearOnYearReportQuery(submitted ?? undefined, { skip: !submitted });

  return (
    <div className="glass space-y-6 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property (optional)"
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          placeholder="All properties"
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Button className="self-end" onClick={() => setSubmitted(propertyId ? { property_id: propertyId } : {})}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView document={data} endpoint="/reports/statements/year-on-year" params={submitted} filenameBase="year-on-year-report" />
      )}
    </div>
  );
}
