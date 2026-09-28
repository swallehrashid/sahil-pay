import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Building2, DoorOpen, Users, Wallet, AlertCircle, FileText, Eye } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import Tabs from "@/components/ui/Tabs";
import SearchInput from "@/components/ui/SearchInput";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Pagination from "@/components/ui/Pagination";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import { useGetPropertyQuery } from "./propertyApiSlice";
import { useGetUnitsQuery } from "@/features/landlord/units/unitApiSlice";
import { useGetTenantsQuery } from "@/features/landlord/tenants/tenantApiSlice";
import { usePagination } from "@/hooks/usePagination";
import { usePortalRoutes } from "@/hooks/usePortalRoutes";
import { usePermissions } from "@/hooks/usePermissions";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";

/**
 * One property: its units and its tenants, each on its own sub-page
 * (/properties/:id/units, /properties/:id/tenants), with a banner that always
 * says which property you are looking at — at 100 properties, a unit list
 * without that line is a list of "A1"s from nowhere.
 */
function ScopeBanner({ what, property }) {
  return (
    <div className="mb-4 flex items-center gap-2 rounded-xl border border-secondary/30 bg-secondary/10 px-4 py-3 text-sm text-white"
         data-testid="property-scope-banner">
      <Eye className="h-4 w-4 text-secondary" />
      <span>
        You are viewing <strong className="font-semibold">{what}</strong> for property{" "}
        <strong className="font-semibold">{property?.name ?? "…"}</strong>
      </span>
    </div>
  );
}

function UnitsTab({ property }) {
  const pg = usePagination();
  const [search, setSearch] = useState("");
  const { data, isLoading } = useGetUnitsQuery({ ...pg.params, search, property_id: property.id });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);
  const columns = [
    { key: "name", header: "Unit" },
    { key: "pay_code", header: "Pay code", render: (r) => r.pay_code ?? "—" },
    { key: "rent", header: "Rent", render: (r) => formatCurrency(r.rent_amount) },
    {
      key: "status", header: "Status",
      render: (r) => (r.is_occupied ? <Badge color="emerald">Occupied</Badge> : <Badge color="secondary">Vacant</Badge>),
    },
    { key: "tenant", header: "Tenant", render: (r) => r.tenant_name ?? r.current_tenant_name ?? "—" },
  ];
  return (
    <>
      <ScopeBanner what="units" property={property} />
      <SearchInput value={search} onSearch={(t) => { setSearch(t); pg.reset(); }}
                   placeholder={`Search units in ${property.name}…`} aria-label="Search units" resultCount={meta.total} />
      <div className="mt-4">
        <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
        <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
      </div>
    </>
  );
}

function TenantsTab({ property }) {
  const ROUTES = usePortalRoutes();
  const navigate = useNavigate();
  const pg = usePagination();
  const [search, setSearch] = useState("");
  const { data, isLoading } = useGetTenantsQuery({ ...pg.params, search, property_id: property.id });
  const rows = toRows(data);
  const meta = toPaginationMeta(data);
  const columns = [
    { key: "name", header: "Tenant", render: (r) => `${r.first_name} ${r.last_name}` },
    { key: "unit", header: "Unit", render: (r) => r.unit_name ?? "—" },
    { key: "phone", header: "Phone", render: (r) => r.phone },
    {
      key: "balance", header: "Balance",
      render: (r) => (Number(r.balance) < 0
        ? <span className="text-amber-300">{formatCurrency(-Number(r.balance))} owed</span>
        : <span className="text-emerald-300">{formatCurrency(Number(r.credit_balance || 0))} credit</span>),
    },
    { key: "nok", header: "Next of kin", render: (r) => (r.next_of_kin_name ? `${r.next_of_kin_name}${r.next_of_kin_phone ? ` · ${r.next_of_kin_phone}` : ""}` : "—") },
  ];
  return (
    <>
      <ScopeBanner what="tenants" property={property} />
      <SearchInput value={search} onSearch={(t) => { setSearch(t); pg.reset(); }}
                   placeholder={`Search tenants in ${property.name}…`} aria-label="Search tenants" resultCount={meta.total} />
      <div className="mt-4">
        <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading}
                         onRowClick={(r) => navigate(ROUTES.tenantTransactionsPath(r.id))} />
        <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
      </div>
    </>
  );
}

export default function PropertyDetailPage() {
  const ROUTES = usePortalRoutes();
  const navigate = useNavigate();
  const { can } = usePermissions();
  const { id, tab = "units" } = useParams();
  const { data: property, isLoading } = useGetPropertyQuery(id);
  const s = property?.summary ?? {};
  const active = tab === "tenants" ? "tenants" : "units";

  return (
    <div>
      <PageHeader
        title={property?.name ?? "Property"}
        subtitle={property ? [property.street_name, property.city].filter(Boolean).join(", ") : ""}
        breadcrumbs={[{ label: "Properties", to: ROUTES.properties }, { label: property?.name ?? "…" }]}
        actions={
          <>
            {can("invoices", "edit") && property && (
              <Link to={`${ROUTES.invoicesByProperty}?property=${property.id}`}>
                <Button variant="ghost" leftIcon={<FileText className="h-4 w-4" />}>Generate this month's invoices</Button>
              </Link>
            )}
            <Link to={ROUTES.properties}>
              <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>All properties</Button>
            </Link>
          </>
        }
      />

      {isLoading || !property ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <SummaryCard label="Units" value={s.units ?? 0} icon={<Building2 className="h-5 w-5" />} />
          <SummaryCard label="Occupied / vacant" value={`${s.occupied ?? 0} / ${s.vacant ?? 0}`} icon={<DoorOpen className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Tenants" value={s.tenants ?? 0} icon={<Users className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Monthly rent roll" value={formatCurrency(s.rent_roll ?? 0)} icon={<Wallet className="h-5 w-5" />} />
          <SummaryCard label="Arrears" value={formatCurrency(s.arrears ?? 0)} icon={<AlertCircle className="h-5 w-5" />} />
        </div>
      )}

      <div data-testid="property-tabs">
      <Tabs
        tabs={[
          { key: "units", label: "Units", count: s.units || undefined },
          { key: "tenants", label: "Tenants", count: s.tenants || undefined },
        ]}
        activeKey={active}
        onChange={(key) => navigate(ROUTES.propertyDetailPath(id, key))}
        className="my-6"
      />
      </div>

      {property && (active === "units" ? <UnitsTab property={property} /> : <TenantsTab property={property} />)}
    </div>
  );
}
