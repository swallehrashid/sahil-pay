import { useState } from "react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "./ReportView";
import { useGetGroupingReportQuery } from "./reportApiSlice";

// Property grouping: every property in the selected group compared across the
// same comparative metrics, with per-property graphs.
export default function GroupingReport({ groups = [] }) {
  const [groupId, setGroupId] = useState("");
  const [submitted, setSubmitted] = useState(null);

  const { data, isFetching } = useGetGroupingReportQuery(submitted ? { id: submitted } : undefined, { skip: !submitted });

  return (
    <div className="glass space-y-6 p-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Select
          label="Property group"
          value={groupId}
          onChange={(e) => setGroupId(e.target.value)}
          options={groups.map((g) => ({ value: g.id, label: g.name }))}
          required
        />
        <Button className="self-end" disabled={!groupId} onClick={() => setSubmitted(groupId)}>
          Generate
        </Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView document={data} endpoint={`/reports/statements/grouping/${submitted}`} filenameBase="grouping-report" />
      )}
    </div>
  );
}
