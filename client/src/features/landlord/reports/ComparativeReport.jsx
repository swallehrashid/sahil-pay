import { useState } from "react";
import Tabs from "@/components/ui/Tabs";
import Button from "@/components/ui/Button";
import ExportButtons from "@/components/ui/ExportButtons";
import ComparativeChart from "@/components/charts/ComparativeChart";
import { useGetMonthOnMonthReportQuery, useGetYearOnYearReportQuery } from "./reportApiSlice";

// Month-on-month / year-on-year comparative performance (§4.11).
export default function ComparativeReport() {
  const [mode, setMode] = useState("month-on-month");
  const [hasGenerated, setHasGenerated] = useState(false);

  const monthQuery = useGetMonthOnMonthReportQuery(undefined, { skip: mode !== "month-on-month" || !hasGenerated });
  const yearQuery = useGetYearOnYearReportQuery(undefined, { skip: mode !== "year-on-year" || !hasGenerated });

  const { data, isFetching } = mode === "month-on-month" ? monthQuery : yearQuery;
  const endpoint = mode === "month-on-month" ? "/reports/statements/month-on-month" : "/reports/statements/year-on-year";

  return (
    <div className="glass space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "month-on-month", label: "Month-on-Month" },
            { key: "year-on-year", label: "Year-on-Year" },
          ]}
          activeKey={mode}
          onChange={(key) => {
            setMode(key);
            setHasGenerated(false);
          }}
        />
        <Button onClick={() => setHasGenerated(true)}>Generate</Button>
      </div>

      {hasGenerated && (
        <>
          <ExportButtons endpoint={endpoint} filenameBase={mode} />
          {isFetching ? <p className="text-sm text-white/40">Loading…</p> : <ComparativeChart data={data?.series ?? []} />}
        </>
      )}
    </div>
  );
}
