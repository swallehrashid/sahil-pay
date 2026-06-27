import { useState } from "react";
import { RotateCcw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { useGetMasterAuditLogsQuery, useRevertAuditActionMutation, useGetAdminLandlordsQuery } from "./adminApiSlice";
import { AUDIT_ENTITY_TYPES } from "@/utils/constants";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// §7.4 — master audit logs across every landlord account, with full revert authority.
export default function MasterAuditLogs() {
  const [filters, setFilters] = useState({ landlord_id: "", entity_type: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [pendingRevert, setPendingRevert] = useState(null);
  const [revertReason, setRevertReason] = useState("");

  const { data, isLoading } = useGetMasterAuditLogsQuery(appliedFilters);
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [revertAction, { isLoading: isReverting }] = useRevertAuditActionMutation();

  const logs = toRows(data);
  const landlords = toRows(landlordsData);
  // AuditLog only carries landlord_id, not a denormalized name — resolve it from the
  // landlords list we already fetch for the filter dropdown.
  const landlordNameById = Object.fromEntries(landlords.map((l) => [l.id, l.company_name]));

  const handleRevert = async () => {
    if (!revertReason.trim()) {
      toast("A reason is required.", { type: "error" });
      return;
    }
    try {
      await revertAction({ auditId: pendingRevert.id, reason: revertReason }).unwrap();
      toast("Action reverted.", { type: "success" });
      setPendingRevert(null);
      setRevertReason("");
    } catch {
      toast("Could not revert the action.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date & time", render: (row) => formatDateTime(row.created_at) },
    { key: "landlord", header: "Landlord", render: (row) => landlordNameById[row.landlord_id] ?? "Platform" },
    { key: "actor", header: "User", render: (row) => row.actor_username },
    { key: "action", header: "Action" },
    { key: "description", header: "Description" },
  ];

  return (
    <div>
      <PageHeader title="Master Audit Logs" subtitle="Every action across every account, with full revert authority" />

      <div className="flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => setAppliedFilters(filters)}
          onReset={() => {
            setFilters({ landlord_id: "", entity_type: "", date_from: "", date_to: "" });
            setAppliedFilters({});
          }}
        >
          <Select
            label="Landlord"
            value={filters.landlord_id}
            onChange={(e) => setFilters((f) => ({ ...f, landlord_id: e.target.value }))}
            placeholder="All landlords"
            options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
          />
          <Select
            label="Entity"
            value={filters.entity_type}
            onChange={(e) => setFilters((f) => ({ ...f, entity_type: e.target.value }))}
            options={AUDIT_ENTITY_TYPES.map((t) => ({ value: t, label: t }))}
          />
          <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
          <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
        </FilterPanel>

        <div className="flex-1">
          <ResponsiveTable
            columns={columns}
            rows={logs}
            isLoading={isLoading}
            rowActions={(row) => (
              <button onClick={() => setPendingRevert(row)} className="flex items-center gap-1 text-xs text-secondary hover:underline">
                <RotateCcw className="h-3.5 w-3.5" /> Revert
              </button>
            )}
          />
        </div>
      </div>

      <ConfirmDialog
        isOpen={Boolean(pendingRevert)}
        onClose={() => { setPendingRevert(null); setRevertReason(""); }}
        onConfirm={handleRevert}
        title="Revert this action?"
        description="The entity will be restored to its state before this audit entry."
        isLoading={isReverting}
      >
        <Textarea label="Reason" value={revertReason} onChange={(e) => setRevertReason(e.target.value)} rows={3} required className="mt-3" />
      </ConfirmDialog>
    </div>
  );
}
