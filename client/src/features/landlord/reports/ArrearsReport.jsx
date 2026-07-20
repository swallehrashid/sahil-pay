import { useState } from "react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetArrearsReportQuery } from "./reportApiSlice";

// Tenants in arrears: unit, name, phone, arrears b/f, current-month bills,
// total arrears, days in arrears.
export default function ArrearsReport({ properties = [] }) {
  const [propertyId, setPropertyId] = useState("");
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetArrearsReportQuery(submitted ?? undefined, { skip: !submitted });

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
        <ReportView document={data} endpoint="/reports/statements/arrears" params={submitted} filenameBase="arrears-report" />
      )}
    </div>
  );
}
