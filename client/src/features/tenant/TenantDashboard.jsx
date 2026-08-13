import { Link } from "react-router-dom";
import { Wallet, Receipt, History, Droplets, ShieldCheck } from "lucide-react";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { useGetPortalDashboardQuery, useGetPortalScoreQuery } from "./tenantPortalApiSlice";
import UnitSwitcher from "./components/UnitSwitcher";
import { TenantScoreDial } from "@/components/ui/TenantScoreBadge";
import { formatCurrency, formatBalance } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { TENANT_ROUTES } from "@/config/routePaths";

// §6.2 — full itemised balance breakdown: the tenant sees EXACTLY what makes up
// their outstanding total (rent, utilities, deposits, arrears) and which invoice
// each charge came from. Numbers are the same source used by reminder comms.
export default function TenantDashboard() {
  const { data, isLoading } = useGetPortalDashboardQuery();
  const { data: score } = useGetPortalScoreQuery();
  const openInvoices = data?.open_invoices ?? [];
  const items = data?.breakdown_items ?? [];
  const totalDue = data?.total_due ?? 0;
  const depositsDue = data?.deposits_due ?? 0;
  // "Deposits held" = refundable deposit money the tenant has actually PAID
  // (confirmed) and the landlord is holding — not what was merely invoiced.
  const depositsHeld = data?.deposits_held ?? 0;

  const columns = [
    { key: "invoice_number", header: "Invoice" },
    {
      key: "title",
      header: "Charge",
      render: (row) => (
        <div>
          <p className="text-white">{row.title || row.type}</p>
          {row.lines?.length > 1 && (
            <p className="mt-0.5 text-xs text-white/40">
              {row.lines.map((l) => l.label).join(" · ")}
            </p>
          )}
        </div>
      ),
    },
    { key: "due_date", header: "Due", render: (row) => (row.due_date ? formatDate(row.due_date) : "—") },
    { key: "balance", header: "Balance", render: (row) => formatCurrency(row.balance) },
    {
      key: "status",
      header: "Status",
      render: (row) => <StatusBadge status={row.is_overdue ? "overdue" : row.status} />,
    },
  ];

  return (
    <div className="animate-fade-in-up space-y-6">
      {/* Only renders for someone renting more than one unit. */}
      <UnitSwitcher className="sm:max-w-md" />

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-light tracking-wide text-white">
            Welcome back{data?.tenant_name ? `, ${data.tenant_name}` : ""}
          </h1>
          <p className="mt-1 text-sm text-white/50">
            {data?.unit_name && data?.property_name
              ? `${data.property_name} · Unit ${data.unit_name} — here's your balance breakdown.`
              : "Here's your current balance breakdown."}
          </p>
        </div>
        <Link to={`${TENANT_ROUTES.pay}?start=1`}>
          <Button leftIcon={<Wallet className="h-4 w-4" />}>Pay now</Button>
        </Link>
      </div>

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Total outstanding" value={formatCurrency(totalDue)} icon={<Receipt className="h-5 w-5" />} />
          <SummaryCard label="Rent due" value={formatCurrency(data?.rent_due)} icon={<Receipt className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Utilities due" value={formatCurrency(data?.utility_due)} icon={<Droplets className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Deposits held" value={formatCurrency(depositsHeld)} icon={<ShieldCheck className="h-5 w-5" />} accent="third" />
        </div>
      )}

      {/* Payment score — shown to the tenant deliberately: it is their record,
          and the clearest possible reason to pay in the first five days. */}
      {score && (
        <div className="glass flex flex-col items-center gap-6 p-6 sm:flex-row sm:items-center">
          <TenantScoreDial score={score.score} />
          <div className="min-w-0 flex-1 text-center sm:text-left">
            <h2 className="text-lg font-light tracking-wide text-white">
              Your payment score
            </h2>
            {score.score === null ? (
              <p className="mt-1.5 text-sm leading-relaxed text-white/55">
                You'll get a score once you've been with us a couple of months.
                Paying within the first 5 days of each month starts it at 100.
              </p>
            ) : (
              <>
                <p className="mt-1.5 text-sm leading-relaxed text-white/55">
                  Based on {score.months_counted} month
                  {score.months_counted === 1 ? "" : "s"} of rent payments.
                </p>
                <div className="mt-3 flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm sm:justify-start">
                  <span className="text-white/50">
                    Paid on time:{" "}
                    <strong className="text-white/85">{score.on_time_rate}%</strong>
                  </span>
                  {score.avg_pay_day != null && (
                    <span className="text-white/50">
                      Usually pays on day{" "}
                      <strong className="text-white/85">{score.avg_pay_day}</strong>
                    </span>
                  )}
                </div>
                <p className="mt-3 text-xs text-white/40">{score.guidance}</p>
              </>
            )}
          </div>
        </div>
      )}

      {/* Itemised breakdown — where the balance came from */}
      {!isLoading && items.length > 0 && (
        <div className="glass animate-fade-in-up p-6">
          <h3 className="mb-1 text-base font-medium text-white">What makes up your balance</h3>
          <p className="mb-4 text-xs text-white/40">Every charge that's currently outstanding on your account.</p>
          <ul className="divide-y divide-white/5">
            {items.map((it, i) => (
              <li key={i} className="flex items-center justify-between py-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white/80">{it.label}</span>
                  {it.is_deposit && (
                    <span className="rounded-full bg-third/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-third-100">
                      Refundable deposit
                    </span>
                  )}
                </div>
                <span className="text-sm font-medium text-white">{formatCurrency(it.amount)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-3">
            <span className="text-sm font-medium text-white">Total outstanding</span>
            <span className="text-base font-semibold text-white">{formatCurrency(totalDue)}</span>
          </div>
          {depositsDue > 0 && (
            <p className="mt-3 text-xs text-white/40">
              Deposits are refundable and are held on your account — they are not arrears.
            </p>
          )}
        </div>
      )}

      <div>
        <h3 className="mb-3 text-base font-medium text-white">Open invoices</h3>
        <ResponsiveTable
          columns={columns}
          rows={openInvoices}
          isLoading={isLoading}
          emptyState={<p className="text-sm text-white/50">No open invoices — you're all caught up.</p>}
        />
      </div>
    </div>
  );
}
