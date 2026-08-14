import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, FileText, FileSpreadsheet } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import PackageRevenueChart from "@/components/charts/PackageRevenueChart";
import { toast } from "@/components/ui/Toast";
import { useGetPackageAnalyticsQuery } from "./adminPricingApiSlice";
import AdminLandlordBillingModal from "./AdminLandlordBillingModal";
import { formatCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { buildQueryParams } from "@/utils/tableAdapters";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7.2 — per-package performance drill-down: subscribers, revenue, active/inactive,
// monthly performance chart, subscriber roster, and downloadable reports.
export default function PackageDetail() {
  const { id } = useParams();
  const [range, setRange] = useState({ start_date: "", end_date: "" });
  const [downloading, setDownloading] = useState(false);
  const [billingLandlordId, setBillingLandlordId] = useState(null); // #16/#17

  const { data, isLoading } = useGetPackageAnalyticsQuery({ id, ...range });
  const pkg = data?.package;

  const handleDownload = async (format) => {
    setDownloading(true);
    try {
      const query = buildQueryParams({ format, ...range });
      await downloadFile(`/admin/pricing/packages/${id}/report?${query}`, {
        filename: `package-report-${pkg?.name ?? id}.${format === "excel" ? "xlsx" : "pdf"}`,
        format: format === "excel" ? "xlsx" : "pdf",
      });
    } catch {
      toast("Could not generate the report.", { type: "error" });
    } finally {
      setDownloading(false);
    }
  };

  const priceLabel = pkg
    ? pkg.flat_price
      ? `${formatCurrency(pkg.flat_price)} flat`
      : `${formatCurrency(pkg.price_per_unit)} / unit`
    : "—";

  const rosterColumns = [
    { key: "company_name", header: "Landlord" },
    { key: "email", header: "Email", render: (r) => r.email ?? "—" },
    { key: "unit_count", header: "Units", render: (r) => r.unit_count ?? 0 },
    { key: "subscription_cost", header: "Pays", render: (r) => formatCurrency(r.subscription_cost) },
    { key: "total_paid", header: "Total paid", render: (r) => formatCurrency(r.total_paid) },
    {
      key: "is_active",
      header: "Status",
      render: (r) => (
        <div className="flex gap-1">
          <Badge color={r.is_active ? "emerald" : "secondary"}>{r.is_active ? "Active" : "Inactive"}</Badge>
          {r.is_on_trial && <Badge color="amber">Trial</Badge>}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={pkg?.name ?? "Package detail"}
        subtitle={pkg ? `${priceLabel} · units ${pkg.min_units}–${pkg.max_units ?? "∞"}` : "Package performance"}
        breadcrumbs={[{ label: "Pricing", to: ADMIN_ROUTES.pricing }, { label: "Detail" }]}
        actions={
          <>
            <Link to={ADMIN_ROUTES.pricing}>
              <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
            </Link>
            <Button variant="ghost" leftIcon={<FileText className="h-4 w-4" />} isLoading={downloading} onClick={() => handleDownload("pdf")}>
              PDF
            </Button>
            <Button variant="ghost" leftIcon={<FileSpreadsheet className="h-4 w-4" />} isLoading={downloading} onClick={() => handleDownload("excel")}>
              Excel
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={5} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-5">
          <SummaryCard label="Subscribers" value={data?.subscriber_count ?? 0} accent="third" />
          <SummaryCard label="Active" value={data?.active_count ?? 0} accent="third" />
          <SummaryCard label="Inactive" value={data?.inactive_count ?? 0} accent="third" />
          <SummaryCard label="Total revenue" value={formatCurrency(data?.total_revenue)} accent="third" />
          <SummaryCard label="Est. MRR" value={formatCurrency(data?.mrr_estimate)} accent="third" />
        </div>
      )}

      <div className="glass flex flex-wrap items-end gap-4 p-6">
        <Input type="date" label="From" value={range.start_date} onChange={(e) => setRange((r) => ({ ...r, start_date: e.target.value }))} />
        <Input type="date" label="To" value={range.end_date} onChange={(e) => setRange((r) => ({ ...r, end_date: e.target.value }))} />
        <div className="pb-1">
          <p className="text-xs uppercase tracking-wide text-white/40">Revenue in period</p>
          <p className="text-lg font-light text-white">{formatCurrency(data?.period_revenue)}</p>
        </div>
        {(range.start_date || range.end_date) && (
          <Button variant="ghost" onClick={() => setRange({ start_date: "", end_date: "" })}>Clear</Button>
        )}
      </div>

      <PackageRevenueChart data={data?.monthly ?? []} title={`Monthly revenue — ${pkg?.name ?? ""}`} />

      <div className="glass p-6">
        <h3 className="mb-1 text-sm font-medium text-white/70">Subscribers on this package</h3>
        <p className="mb-4 text-xs text-white/40">Click a landlord to view and edit their billing, trial and next billing date.</p>
        <ResponsiveTable
          columns={rosterColumns}
          rows={data?.landlords ?? []}
          isLoading={isLoading}
          onRowClick={(row) => setBillingLandlordId(row.id)}
        />
      </div>

      <AdminLandlordBillingModal landlordId={billingLandlordId} onClose={() => setBillingLandlordId(null)} />
    </div>
  );
}
