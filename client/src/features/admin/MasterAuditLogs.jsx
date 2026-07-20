import { useState } from "react";
import { RotateCcw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import DatePicker from "@/components/ui/DatePicker";
import Textarea from "@/components/ui/Textarea";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { useGetMasterAuditLogsQuery, useRevertAuditActionMutation, useGetAdminLandlordsQuery } from "./adminApiSlice";
import { AUDIT_ENTITY_TYPES } from "@/utils/constants";

const ACTOR_ROLES = [
  { value: "landlord", label: "Landlord" },
  { value: "property_manager", label: "Property manager" },
  { value: "team_member", label: "Team member" },
  { value: "tenant", label: "Tenant" },
  { value: "system_admin", label: "Admin" },
];
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";

// §7.4 — master audit logs across every landlord account, with full revert authority.
export default function MasterAuditLogs() {
  const [filters, setFilters] = useState({ landlord_id: "", actor_role: "", entity_type: "", impersonated: false, start_date: "", end_date: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [pendingRevert, setPendingRevert] = useState(null);
  const [revertReason, setRevertReason] = useState("");

  const pg = usePagination();
  const { data, isLoading } = useGetMasterAuditLogsQuery({ ...appliedFilters, ...pg.params });
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [revertAction, { isLoading: isReverting }] = useRevertAuditActionMutation();

  const logs = toRows(data);
  const meta = toPaginationMeta(data);
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
    {
      key: "description",
      header: "Description",
      render: (row) => (
        <div className="flex items-center gap-2">
          {typeof row.description === "string" && (row.description.includes("[Client support session") || row.description.includes("[Impersonating")) && (
            <Badge color="amber">Client support</Badge>
          )}
          <span>{row.description}</span>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="Master Audit Logs" subtitle="Every action across every account, with full revert authority" />

      <div className="flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => { setAppliedFilters({ ...filters, impersonated: filters.impersonated ? "true" : "" }); pg.reset(); }}
          onReset={() => {
            setFilters({ landlord_id: "", actor_role: "", entity_type: "", impersonated: false, start_date: "", end_date: "" });
            setAppliedFilters({});
          }}
        >
          <Select
            label="Actor type"
            value={filters.actor_role}
            onChange={(e) => setFilters((f) => ({ ...f, actor_role: e.target.value }))}
            placeholder="All users"
            options={ACTOR_ROLES}
          />
          <Select
            label="Landlord"
            value={filters.landlord_id}
            onChange={(e) => setFilters((f) => ({ ...f, landlord_id: e.target.value }))}
            placeholder="All landlords"
            options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
          />
          <Select
            label="Activity"
            value={filters.entity_type}
            onChange={(e) => setFilters((f) => ({ ...f, entity_type: e.target.value }))}
            placeholder="All activity"
            options={AUDIT_ENTITY_TYPES.map((t) => ({ value: t, label: t }))}
          />
          <DatePicker label="From" value={filters.start_date} onChange={(e) => setFilters((f) => ({ ...f, start_date: e.target.value }))} />
          <DatePicker label="To" value={filters.end_date} onChange={(e) => setFilters((f) => ({ ...f, end_date: e.target.value }))} />
          <Checkbox
            label="Client support actions only"
            checked={filters.impersonated}
            onChange={(e) => setFilters((f) => ({ ...f, impersonated: e.target.checked }))}
          />
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
          <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
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
