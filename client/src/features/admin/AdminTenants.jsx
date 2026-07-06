import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import { useDebounce } from "@/hooks/useDebounce";
import { usePagination } from "@/hooks/usePagination";
import { useGetAdminTenantsQuery } from "./adminApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { formatCurrency } from "@/utils/currencyFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — every active tenant on the platform, with unit, property, landlord and balance.
export default function AdminTenants() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search);
  const pg = usePagination();

  const { data, isLoading } = useGetAdminTenantsQuery({ search: debouncedSearch, ...pg.params });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);

  const columns = [
    { key: "name", header: "Tenant" },
    { key: "phone", header: "Phone", render: (r) => r.phone ?? "—" },
    { key: "unit_name", header: "Unit", render: (r) => r.unit_name ?? "—" },
    { key: "property_name", header: "Property", render: (r) => r.property_name ?? "—" },
    { key: "company_name", header: "Landlord", render: (r) => r.company_name ?? "—" },
    { key: "balance", header: "Balance", render: (r) => formatCurrency(r.balance) },
  ];

  return (
    <div>
      <PageHeader title="Tenants" subtitle="Every active tenant across all landlords" />
      <Input className="mb-6 max-w-sm" placeholder="Search name, phone or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={(row) => navigate(ADMIN_ROUTES.tenantDetailPath(row.id))}
      />
      <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
    </div>
  );
}
