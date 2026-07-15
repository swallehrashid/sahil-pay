import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import Modal from "@/components/ui/Modal";
import { useGetAuditLogsQuery } from "./auditApiSlice";
import { useGetTeamMembersQuery } from "./teamApiSlice";
import { AUDIT_ENTITY_TYPES } from "@/utils/constants";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";

// §4.23 — filterable audit trail with an expandable before/after detail view.
export default function AuditTrail() {
  const [filters, setFilters] = useState({ start_date: "", end_date: "", actor_user_id: "", entity_type: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [activeEntry, setActiveEntry] = useState(null);
  const pg = usePagination();

  const { data, isLoading } = useGetAuditLogsQuery({ ...appliedFilters, ...pg.params });
  const { data: teamData } = useGetTeamMembersQuery();

  const logs = toRows(data);
  const meta = toPaginationMeta(data);
  const teamMembers = toRows(teamData);

  const columns = [
    { key: "date", header: "Date & time", render: (row) => formatDateTime(row.created_at) },
    { key: "actor", header: "User", render: (row) => row.actor_username },
    { key: "action", header: "Action" },
    { key: "entity_type", header: "Entity" },
    { key: "description", header: "Description" },
  ];

  return (
    <div>
      <PageHeader title="Audit Trail" subtitle="Every create, update and delete action on your account" />

      <div className="flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => { setAppliedFilters(filters); pg.reset(); }}
          onReset={() => {
            setFilters({ start_date: "", end_date: "", actor_user_id: "", entity_type: "" });
            setAppliedFilters({});
            pg.reset();
          }}
        >
          <DatePicker label="From" value={filters.start_date} onChange={(e) => setFilters((f) => ({ ...f, start_date: e.target.value }))} />
          <DatePicker label="To" value={filters.end_date} onChange={(e) => setFilters((f) => ({ ...f, end_date: e.target.value }))} />
          <Select
            label="User"
            value={filters.actor_user_id}
            onChange={(e) => setFilters((f) => ({ ...f, actor_user_id: e.target.value }))}
            placeholder="All users"
            options={teamMembers.map((m) => ({ value: m.user_id, label: m.username }))}
          />
          <Select
            label="Entity"
            value={filters.entity_type}
            onChange={(e) => setFilters((f) => ({ ...f, entity_type: e.target.value }))}
            options={AUDIT_ENTITY_TYPES.map((t) => ({ value: t, label: t }))}
          />
        </FilterPanel>

        <div className="min-w-0 flex-1">
          <ResponsiveTable columns={columns} rows={logs} isLoading={isLoading} onRowClick={(row) => setActiveEntry(row)} />
          <Pagination
            page={pg.page}
            perPage={pg.perPage}
            total={meta.total}
            onPageChange={pg.setPage}
            onPerPageChange={pg.setPerPage}
          />
        </div>
      </div>

      <Modal isOpen={Boolean(activeEntry)} onClose={() => setActiveEntry(null)} title="Audit entry detail" size="lg">
        {activeEntry && (
          <div className="space-y-3 text-sm text-white/70">
            <p>
              <span className="text-white/40">Actor:</span> {activeEntry.actor_full_name} ({activeEntry.actor_username})
            </p>
            <p>
              <span className="text-white/40">Action:</span> {activeEntry.action}
            </p>
            <p>
              <span className="text-white/40">Description:</span> {activeEntry.description}
            </p>
            {activeEntry.ip_address && (
              <p>
                <span className="text-white/40">IP address:</span> {activeEntry.ip_address}
              </p>
            )}
            {activeEntry.before_data && (
              <div>
                <p className="mb-1 text-white/40">Before</p>
                <pre className="overflow-x-auto rounded-lg bg-white/5 p-3 text-xs">{JSON.stringify(activeEntry.before_data, null, 2)}</pre>
              </div>
            )}
            {activeEntry.after_data && (
              <div>
                <p className="mb-1 text-white/40">After</p>
                <pre className="overflow-x-auto rounded-lg bg-white/5 p-3 text-xs">{JSON.stringify(activeEntry.after_data, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
