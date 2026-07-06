import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import { useDebounce } from "@/hooks/useDebounce";
import { usePagination } from "@/hooks/usePagination";
import { useGetAdminTeamMembersQuery } from "./adminApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — every team member (sub-account) on the platform, with the landlord
// they belong to, their role and how many modules they can touch.
export default function AdminTeamMembers() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search);
  const pg = usePagination();

  const { data, isLoading } = useGetAdminTeamMembersQuery({ search: debouncedSearch, ...pg.params });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);

  const displayName = (r) => [r.first_name, r.last_name].filter(Boolean).join(" ") || r.username;

  const columns = [
    { key: "username", header: "Member", render: displayName },
    { key: "email", header: "Email", render: (r) => r.email ?? "—" },
    { key: "company_name", header: "Belongs to", render: (r) => r.company_name ?? "—" },
    { key: "role", header: "Role", render: (r) => r.role ?? "—" },
    { key: "permission_count", header: "Permissions", render: (r) => `${r.permission_count ?? 0} module(s)` },
    {
      key: "is_active",
      header: "Status",
      render: (r) => <Badge color={r.is_active ? "emerald" : "secondary"}>{r.is_active ? "Active" : "Pending"}</Badge>,
    },
  ];

  return (
    <div>
      <PageHeader title="Team members" subtitle="Every sub-account, who they belong to and what they can do" />
      <Input className="mb-6 max-w-sm" placeholder="Search name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={(row) => navigate(ADMIN_ROUTES.teamMemberDetailPath(row.id))}
      />
      <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
    </div>
  );
}
