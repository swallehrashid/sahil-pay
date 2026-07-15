import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Pagination from "@/components/ui/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetAffiliateReferralsQuery } from "./affiliateApiSlice";

export default function AffiliateReferrals() {
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);
  const { data, isLoading } = useGetAffiliateReferralsQuery(params);

  const columns = [
    { key: "landlord_company_name", header: "Landlord", render: (r) => r.landlord_company_name ?? "—" },
    { key: "package_name", header: "Package", render: (r) => r.package_name ?? "—" },
    { key: "subscription_status", header: "Subscription", render: (r) => <StatusBadge status={r.subscription_status} /> },
    { key: "monthly_value", header: "Monthly value", render: (r) => (r.monthly_value ? formatCurrency(r.monthly_value) : "—") },
    { key: "rate", header: "Your rate", render: (r) => `${r.rate}%` },
    { key: "months", header: "Months", render: (r) => `${r.months_used} / ${r.months_total}` },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "earned_so_far", header: "Earned so far", render: (r) => formatCurrency(r.earned_so_far) },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your referrals"
        subtitle="Landlords you've referred, their subscription status, and what they've earned you"
      />
      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.referrals ?? []}
          isLoading={isLoading}
          emptyState={
            <div className="py-10 text-center text-sm text-white/50">
              No referrals yet — share your referral link to get started.
            </div>
          }
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>
    </div>
  );
}
