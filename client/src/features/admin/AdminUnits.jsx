import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Badge from "@/components/ui/Badge";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Pagination from "@/components/ui/Pagination";
import { useDebounce } from "@/hooks/useDebounce";
import { usePagination } from "@/hooks/usePagination";
import { useGetAdminUnitsQuery } from "./adminApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { formatCurrency } from "@/utils/currencyFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — every unit on the platform, with its property, owning landlord and occupant.
export default function AdminUnits() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search);
  const pg = usePagination();

  const { data, isLoading } = useGetAdminUnitsQuery({ search: debouncedSearch, ...pg.params });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);

  const columns = [
    { key: "name", header: "Unit" },
    { key: "property_name", header: "Property", render: (r) => r.property_name ?? "—" },
    { key: "company_name", header: "Landlord", render: (r) => r.company_name ?? "—" },
    { key: "rent_amount", header: "Rent", render: (r) => formatCurrency(r.rent_amount) },
    {
      key: "is_occupied",
      header: "Occupancy",
      render: (r) => <Badge color={r.is_occupied ? "emerald" : "secondary"}>{r.is_occupied ? "Occupied" : "Vacant"}</Badge>,
    },
    { key: "occupant", header: "Occupant", render: (r) => r.occupant?.name ?? "—" },
  ];

  return (
    <div>
      <PageHeader title="Units" subtitle="Every unit on the platform and who occupies it" />
      <Input className="mb-6 max-w-sm" placeholder="Search unit or property…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={(row) => navigate(ADMIN_ROUTES.unitDetailPath(row.id))}
      />
      <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
    </div>
  );
}
