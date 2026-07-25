import { Link } from "react-router-dom";
import { Wallet, Receipt, History, Droplets, ShieldCheck } from "lucide-react";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { useGetPortalDashboardQuery } from "./tenantPortalApiSlice";
import { formatCurrency, formatBalance } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { TENANT_ROUTES } from "@/config/routePaths";

// §6.2 — full itemised balance breakdown: the tenant sees EXACTLY what makes up
// their outstanding total (rent, utilities, deposits, arrears) and which invoice
// each charge came from. Numbers are the same source used by reminder comms.
export default function TenantDashboard() {
  const { data, isLoading } = useGetPortalDashboardQuery();
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
