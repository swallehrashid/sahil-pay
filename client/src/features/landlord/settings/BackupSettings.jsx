import { useState } from "react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import ReportView from "@/features/landlord/reports/ReportView";
import { useGetBackupPreviewQuery } from "./settingsApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetPropertyGroupsQuery } from "../groups/groupApiSlice";
import { toRows } from "@/utils/tableAdapters";

// §4.15 — detailed, downloadable backups. Pick a scope, generate an on-screen
// preview, choose exactly which columns to back up, then download Excel/PDF.
const SCOPES = [
  { value: "tenants", label: "All tenants" },
  { value: "payments", label: "All payments" },
  { value: "units", label: "All units" },
  { value: "properties", label: "All properties" },
  { value: "property", label: "One property (units + tenants + payments)" },
  { value: "grouping", label: "One property group" },
];

export default function BackupSettings() {
  const [scopeType, setScopeType] = useState("tenants");
  const [scopeId, setScopeId] = useState("");
  const [submitted, setSubmitted] = useState(null);

  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: groupsData } = useGetPropertyGroupsQuery();
  const properties = toRows(propertiesData);
  const groups = toRows(groupsData);

  const needsScopeId = scopeType === "property" || scopeType === "grouping";
  const scopeOptions = scopeType === "property" ? properties : scopeType === "grouping" ? groups : [];

  const { data, isFetching } = useGetBackupPreviewQuery(submitted ?? undefined, { skip: !submitted });

  const handleGenerate = () => {
    const params = { scope_type: scopeType };
    if (needsScopeId && scopeId) params.scope_id = scopeId;
    setSubmitted(params);
  };

  return (
    <div className="space-y-6">
      <div className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Generate a backup</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select
            label="Scope"
            value={scopeType}
            onChange={(e) => { setScopeType(e.target.value); setScopeId(""); }}
            options={SCOPES}
          />
          {needsScopeId && (
            <Select
              label={scopeType === "property" ? "Property" : "Group"}
              value={scopeId}
              onChange={(e) => setScopeId(e.target.value)}
              options={scopeOptions.map((o) => ({ value: o.id, label: o.name }))}
              required
            />
          )}
          <Button className="self-end" disabled={needsScopeId && !scopeId} onClick={handleGenerate}>
            Generate backup
          </Button>
        </div>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <div className="glass p-6">
          <ReportView document={data} endpoint="/settings/backup/generate" params={submitted} filenameBase={`backup-${scopeType}`} />
        </div>
      )}
    </div>
  );
}
