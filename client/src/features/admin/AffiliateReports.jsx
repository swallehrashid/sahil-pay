import { useState } from "react";
import { FileText, FileSpreadsheet, FileDown } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from "recharts";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import SummaryCard from "@/components/ui/SummaryCard";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { formatCurrency, formatCompactCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { ADMIN_ROUTES } from "@/config/routePaths";
import { useGetAffiliateAnalyticsQuery } from "./adminAffiliateApiSlice";

const REPORTS = [
  { key: "payouts", label: "Payouts report", description: "Gross paid out, WHT withheld, platform fee collected, net paid — per affiliate. Your KRA remittance working paper." },
  { key: "earnings", label: "Earnings report", description: "Commissions confirmed and reversed in the period, current balance, lifetime earned — per affiliate." },
  { key: "referral-performance", label: "Referral performance", description: "Referrals attributed, conversion rate, and commission cost — per affiliate." },
  { key: "summary", label: "Program summary", description: "One-pager: total liability, total paid out, WHT/fees collected to date, top 10 affiliates." },
];

export default function AffiliateReports() {
  const [range, setRange] = useState({ start_date: "", end_date: "" });
  const [loadingKey, setLoadingKey] = useState(null);
  const { data: analytics, isLoading: isLoadingAnalytics } = useGetAffiliateAnalyticsQuery();

  const handleDownload = async (reportKey, fmt) => {
    setLoadingKey(`${reportKey}-${fmt}`);
    try {
      const params = new URLSearchParams({ fmt });
      if (range.start_date) params.set("start_date", range.start_date);
      if (range.end_date) params.set("end_date", range.end_date);
      await downloadFile(`/admin/affiliates/reports/${reportKey}?${params}`, {
        filename: `affiliate-${reportKey}.${fmt === "xlsx" ? "xlsx" : fmt}`,
        format: fmt,
      });
    } catch {
      toast("Download failed. Please try again.", { type: "error" });
    } finally {
      setLoadingKey(null);
    }
  };

  const chartData = mergeMonthly(analytics?.monthly_accrued, analytics?.monthly_payouts);

  const leaderboardColumns = [
    { key: "full_name", header: "Affiliate" },
    { key: "total_earned", header: "Lifetime earned", render: (r) => formatCurrency(r.total_earned) },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Affiliate reports & analytics"
        subtitle="Downloadable KRA-ready reports and program-wide analytics"
        breadcrumbs={[
          { label: "Admin", to: ADMIN_ROUTES.dashboard },
          { label: "Affiliates", to: ADMIN_ROUTES.affiliates },
          { label: "Reports" },
        ]}
      />

      <div className="glass flex flex-wrap items-end gap-4 p-6">
        <Input label="From" type="date" value={range.start_date} onChange={(e) => setRange((r) => ({ ...r, start_date: e.target.value }))} />
        <Input label="To" type="date" value={range.end_date} onChange={(e) => setRange((r) => ({ ...r, end_date: e.target.value }))} />
        <p className="text-xs text-white/40">Leave blank for all-time. The program summary report ignores the date range.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {REPORTS.map((report) => (
          <div key={report.key} className="glass p-6">
            <h3 className="text-base font-medium text-white">{report.label}</h3>
            <p className="mt-1 text-sm text-white/50">{report.description}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="ghost" size="sm" leftIcon={<FileText className="h-4 w-4" />}
                isLoading={loadingKey === `${report.key}-pdf`}
                onClick={() => handleDownload(report.key, "pdf")}
              >
                PDF
              </Button>
              <Button
                variant="ghost" size="sm" leftIcon={<FileSpreadsheet className="h-4 w-4" />}
                isLoading={loadingKey === `${report.key}-xlsx`}
                onClick={() => handleDownload(report.key, "xlsx")}
              >
                Excel
              </Button>
              <Button
                variant="ghost" size="sm" leftIcon={<FileDown className="h-4 w-4" />}
                isLoading={loadingKey === `${report.key}-csv`}
                onClick={() => handleDownload(report.key, "csv")}
              >
                CSV
              </Button>
            </div>
          </div>
        ))}
      </div>

      <h2 className="pt-4 text-lg font-light text-white">Analytics</h2>

      {isLoadingAnalytics ? (
        <Spinner className="mx-auto my-10" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <SummaryCard label="Signed up" value={analytics?.funnel?.signed_up ?? 0} />
            <SummaryCard label="Approved" value={analytics?.funnel?.approved ?? 0} />
            <SummaryCard label="Has ≥1 referral" value={analytics?.funnel?.has_referral ?? 0} />
            <SummaryCard label="Has ≥1 conversion" value={analytics?.funnel?.has_conversion ?? 0} accent="secondary" />
          </div>

          <div className="glass p-6">
            <h3 className="mb-4 text-base font-medium text-white">Commissions accrued vs payouts — by month</h3>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
                <XAxis dataKey="month" stroke="rgba(255,255,255,0.4)" fontSize={12} />
                <YAxis stroke="rgba(255,255,255,0.4)" fontSize={12} tickFormatter={(v) => formatCompactCurrency(v)} />
                <Tooltip
                  contentStyle={{ background: "#160653", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 12 }}
                  labelStyle={{ color: "#fff" }}
                  formatter={(value, name) => [formatCompactCurrency(value), name]}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "rgba(255,255,255,0.6)" }} />
                <Line type="monotone" dataKey="accrued" name="Accrued" stroke="#B95F7B" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="net" name="Paid out (net)" stroke="#34d399" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="fee" name="Platform fees" stroke="#6366f1" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="wht" name="WHT withheld" stroke="#f59e0b" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="glass p-6">
            <h3 className="mb-4 text-sm font-medium text-white/70">Top 10 affiliates by lifetime earnings</h3>
            <ResponsiveTable
              columns={leaderboardColumns}
              rows={analytics?.leaderboard ?? []}
              keyField="affiliate_id"
              emptyState={<div className="py-8 text-center text-sm text-white/50">No earnings yet.</div>}
            />
          </div>
        </>
      )}
    </div>
  );
}

function mergeMonthly(accrued = [], payouts = []) {
  const map = new Map();
  for (const row of accrued) map.set(row.month, { month: row.month, accrued: Number(row.amount) });
  for (const row of payouts) {
    const existing = map.get(row.month) ?? { month: row.month };
    map.set(row.month, { ...existing, net: Number(row.net), fee: Number(row.fee), wht: Number(row.wht) });
  }
  return Array.from(map.values()).sort((a, b) => a.month.localeCompare(b.month));
}
