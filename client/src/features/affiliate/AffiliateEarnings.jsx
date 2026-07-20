import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Pagination from "@/components/ui/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { useGetAffiliateCommissionsQuery } from "./affiliateApiSlice";

export default function AffiliateEarnings() {
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);
  const { data, isLoading } = useGetAffiliateCommissionsQuery(params);

  const columns = [
    { key: "created_at", header: "Date", render: (r) => formatDate(r.created_at) },
    { key: "landlord_company_name", header: "Landlord", render: (r) => r.landlord_company_name ?? "—" },
    { key: "rate_applied", header: "Rate", render: (r) => `${r.rate_applied}%` },
    { key: "months_commissioned", header: "Months", render: (r) => r.months_commissioned },
    {
      key: "amount",
      header: "Amount",
      render: (r) => (
        <span className={r.status === "reversed" ? "text-secondary-300" : "text-emerald-300"}>
          {r.status === "reversed" ? "-" : "+"}
          {formatCurrency(r.amount)}
        </span>
      ),
    },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Earnings ledger" subtitle="Every commission you've earned — and any that were reversed" />
      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.commissions ?? []}
          isLoading={isLoading}
          emptyState={<div className="py-10 text-center text-sm text-white/50">No commissions yet.</div>}
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>
    </div>
  );
}
