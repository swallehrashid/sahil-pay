import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import { useDebounce } from "@/hooks/useDebounce";
import { usePagination } from "@/hooks/usePagination";
import { useGetAdminPropertiesQuery } from "./adminApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { formatCurrency } from "@/utils/currencyFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — every property/company on the platform, with occupancy, the plan
// funding it and trial state.
export default function AdminProperties() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search);
  const pg = usePagination();

  const { data, isLoading } = useGetAdminPropertiesQuery({ search: debouncedSearch, ...pg.params });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);

  const columns = [
    { key: "name", header: "Property" },
    { key: "company_name", header: "Landlord", render: (r) => r.company_name ?? "—" },
    { key: "city", header: "City", render: (r) => r.city ?? "—" },
    { key: "unit_count", header: "Units", render: (r) => r.unit_count ?? 0 },
    { key: "vacant_units", header: "Occ / Vac", render: (r) => `${r.occupied_units ?? 0} / ${r.vacant_units ?? 0}` },
    { key: "package", header: "Package", render: (r) => r.package?.name ?? "—" },
    { key: "subscription_cost", header: "Sub. cost", render: (r) => (r.subscription_cost != null ? formatCurrency(r.subscription_cost) : "—") },
    {
      key: "is_on_trial",
      header: "Trial",
      render: (r) => (r.is_on_trial ? <Badge color="amber">On trial</Badge> : <Badge color="emerald">Paid</Badge>),
    },
  ];

  return (
    <div>
      <PageHeader title="Properties" subtitle="Every property across all landlords, with occupancy and plan" />
      <Input className="mb-6 max-w-sm" placeholder="Search property or company…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={(row) => navigate(ADMIN_ROUTES.propertyDetailPath(row.id))}
      />
      <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
    </div>
  );
}
