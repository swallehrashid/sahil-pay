import { useState } from "react";
import { Download } from "lucide-react";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { toast } from "@/components/ui/Toast";
import { useGenerateBackupMutation, useGetBackupsQuery } from "./settingsApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetPropertyGroupsQuery } from "../groups/groupApiSlice";
import { BACKUP_SCOPE_TYPES, BACKUP_FORMATS } from "@/utils/constants";
import { downloadFile } from "@/utils/downloadFile";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// §4.15 — scoped backups (property/grouping/tenants/payments/category) as Excel or PDF.
export default function BackupSettings() {
  const [generateBackup, { isLoading: isGenerating }] = useGenerateBackupMutation();
  const { data, isLoading } = useGetBackupsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: groupsData } = useGetPropertyGroupsQuery();

  const [form, setForm] = useState({ scope_type: "property", scope_id: "", format: "pdf" });

  const properties = toRows(propertiesData);
  const groups = toRows(groupsData);
  const backups = toRows(data);

  const scopeOptions = form.scope_type === "property" ? properties : form.scope_type === "grouping" ? groups : [];

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await generateBackup(form).unwrap();
      toast("Backup generated.", { type: "success" });
    } catch {
      toast("Could not generate the backup.", { type: "error" });
    }
  };

  const columns = [
    { key: "scope_type", header: "Scope" },
    { key: "format", header: "Format" },
    { key: "created_at", header: "Generated on", render: (row) => formatDate(row.created_at) },
    {
      key: "download",
      header: "",
      render: (row) =>
        row.file_url && (
          <button
            onClick={() => downloadFile(row.file_url, { filename: `backup-${row.id}.${row.format}` })}
            className="text-secondary hover:underline"
          >
            <Download className="h-4 w-4" />
          </button>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Generate a backup</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select
            label="Scope"
            value={form.scope_type}
            onChange={(e) => setForm({ scope_type: e.target.value, scope_id: "", format: form.format })}
            options={BACKUP_SCOPE_TYPES.map((s) => ({ value: s, label: s }))}
          />
          {(form.scope_type === "property" || form.scope_type === "grouping") && (
            <Select
              label="Select"
              value={form.scope_id}
              onChange={(e) => setForm((f) => ({ ...f, scope_id: e.target.value }))}
              options={scopeOptions.map((o) => ({ value: o.id, label: o.name }))}
            />
          )}
          <Select
            label="Format"
            value={form.format}
            onChange={(e) => setForm((f) => ({ ...f, format: e.target.value }))}
            options={BACKUP_FORMATS.map((f) => ({ value: f, label: f }))}
          />
        </div>
        <div className="flex justify-end">
          <Button type="submit" isLoading={isGenerating}>
            Generate backup
          </Button>
        </div>
      </form>

      <div>
        <h3 className="mb-3 text-base font-medium text-white">Generated backups</h3>
        <ResponsiveTable columns={columns} rows={backups} isLoading={isLoading} />
      </div>
    </div>
  );
}
