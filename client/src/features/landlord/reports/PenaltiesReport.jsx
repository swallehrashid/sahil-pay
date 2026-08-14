import { useMemo, useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import EmptyState from "@/components/ui/EmptyState";
import Badge from "@/components/ui/Badge";
import { toRows } from "@/utils/tableAdapters";
import { formatDate } from "@/utils/dateFormatter";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetPropertiesQuery } from "@/features/landlord/properties/propertyApiSlice";
import { useGetPenaltyReportQuery } from "@/features/landlord/penalties/penaltyApiSlice";

// The penalties report — the same shape as the other money reports, because a
// manager reconciling a month should not have to learn a new layout for this
// one. Server-side it is property-scoped, so a team member restricted to one
// block sees only their own rows even when they ask for everything.

const SOURCES = [
  { value: "",       label: "All sources" },
  { value: "auto",   label: "Automatic" },
  { value: "manual", label: "Raised by hand" },
];

export default function PenaltiesReport() {
  const [filters, setFilters] = useState({
    start_date: "", end_date: "", property_id: "",
    source: "", min_amount: "", max_amount: "",
  });

  const { data: propertiesData } = useGetPropertiesQuery({ per_page: 200 });
  const properties = useMemo(() => toRows(propertiesData), [propertiesData]);

  // Drop empty filters so the API sees "unset" rather than an empty string it
  // would have to interpret.
  const params = useMemo(
    () => Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "")),
    [filters],
  );

  const { data, isLoading, isFetching } = useGetPenaltyReportQuery(params);
  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }));

  const rows = data?.items ?? [];

  const columns = [
    {
      key: "created_at", header: "Date",
      render: (r) => formatDate(r.created_at),
    },
    { key: "tenant_name", header: "Tenant" },
    { key: "account_number", header: "Account" },
    { key: "property_name", header: "Property" },
    { key: "unit_name", header: "Unit" },
    {
      key: "basis_balance", header: "Owed at the time",
      render: (r) => formatCurrency(r.basis_balance),
    },
    {
      key: "amount", header: "Penalty",
      render: (r) => formatCurrency(r.amount),
    },
    {
      key: "source", header: "Source",
      render: (r) => (
        <Badge tone={r.source === "auto" ? "info" : "muted"}>
          {r.source === "auto" ? "Automatic" : "By hand"}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Penalties"
        subtitle="Late-payment charges raised across your properties"
      />

      <div className="glass grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Input label="From" type="date" value={filters.start_date} onChange={set("start_date")} />
        <Input label="To" type="date" value={filters.end_date} onChange={set("end_date")} />
        <Select
          label="Property"
          value={filters.property_id}
          onChange={set("property_id")}
          options={[{ value: "", label: "All properties" },
                    ...properties.map((p) => ({ value: p.id, label: p.name }))]}
        />
        <Select label="Source" value={filters.source} onChange={set("source")} options={SOURCES} />
        <Input label="Minimum amount" type="number" min="0"
               value={filters.min_amount} onChange={set("min_amount")} />
        <Input label="Maximum amount" type="number" min="0"
               value={filters.max_amount} onChange={set("max_amount")} />
      </div>

      {!isLoading && rows.length === 0 ? (
        <EmptyState
          title="No penalties in this period"
          description="Nothing has been charged for the filters you've chosen."
        />
      ) : (
        <>
          <div className="glass flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-sm text-white/60">
              {data?.count ?? 0} charge{(data?.count ?? 0) === 1 ? "" : "s"}
            </p>
            <p className="text-lg font-light text-white">
              {formatCurrency(data?.total ?? 0)}
            </p>
          </div>

          <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading || isFetching} />
        </>
      )}

      <p className="text-xs text-white/40">
        {data?.note ||
          "Penalties are not commissionable and are excluded from the commission base."}
      </p>
    </div>
  );
}
