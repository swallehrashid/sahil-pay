import { useState } from "react";
import { Scale, Wallet, FileText, AlertCircle } from "lucide-react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Spinner from "@/components/ui/Spinner";
import Tabs from "@/components/ui/Tabs";
import SummaryCard from "@/components/ui/SummaryCard";
import ExportButtons from "@/components/ui/ExportButtons";
import Pagination from "@/components/ui/Pagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import {
  useGetChargeCategoriesQuery,
  useGetPaymentsReportQuery,
} from "../chargeCategoryApiSlice";

/**
 * The Payments Report — billed, collected and still owed, by category, by the
 * MONTH each charge is for, by tenant, and every allocation line by line.
 *
 * Computed live on the server on every load (and marked stale after every
 * change anywhere in the app), so a payment allocated a moment ago is here.
 * "Download Excel" gives one sheet per table with real numbers and filters.
 */
const MONEY = [
  { key: "invoiced", label: "Invoiced" },
  { key: "current_collected", label: "Current collected" },
  { key: "balance_collected", label: "Arrears collected" },
  { key: "total_collected", label: "Total collected", strong: true },
  { key: "outstanding", label: "Still owed", warn: true },
  { key: "deposit_paid", label: "Deposit paid" },
  { key: "deposit_balance", label: "Deposit owed" },
  { key: "deposit_held", label: "Deposit held" },
];

function Money({ value, strong, warn }) {
  const cls = strong ? "font-semibold text-white" : warn && value > 0 ? "text-amber-300" : "";
  return <span className={"whitespace-nowrap " + cls}>{formatCurrency(value || 0)}</span>;
}

function Table({ head, children, minWidth = 900 }) {
  return (
    <div className="table-scroll overflow-x-auto">
      <table className="w-full text-sm" style={{ minWidth }}>
        <thead>
          <tr className="text-xs text-white/40">
            {head.map((h, i) => (
              <th key={h} className={"pb-2 font-medium " + (i === 0 ? "pr-3 text-left" : "pl-3 text-right")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-white/80">{children}</tbody>
      </table>
    </div>
  );
}

function SummaryTable({ rows, grand }) {
  return (
    <div className="glass p-5" data-testid="report-summary">
      <h3 className="mb-3 text-base font-medium text-white">Summary by category</h3>
      <Table head={["Category", ...MONEY.map((c) => c.label)]}>
        {rows.map((r) => (
          <tr key={r.category_id} className="border-t border-white/5">
            <td className="py-2 pr-3">{r.category_name} <span className="text-xs text-white/35">{r.kind}</span></td>
            {MONEY.map((c) => <td key={c.key} className="py-2 pl-3 text-right"><Money value={r[c.key]} strong={c.strong} warn={c.warn} /></td>)}
          </tr>
        ))}
        {grand && (
          <tr className="border-t-2 border-white/15 font-semibold text-white">
            <td className="py-2 pr-3">All categories</td>
            {MONEY.map((c) => <td key={c.key} className="whitespace-nowrap py-2 pl-3 text-right">{formatCurrency(grand[c.key] || 0)}</td>)}
          </tr>
        )}
      </Table>
      <p className="mt-2 text-xs text-white/40">
        Total collected = current + arrears. Deposits are held (refundable) money and are shown apart.
        Invoiced counts new charges only — a balance carried forward is not billed twice.
      </p>
    </div>
  );
}

function ByMonth({ rows }) {
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  const shown = rows.slice((page - 1) * perPage, page * perPage);
  return (
    <div className="glass p-5" data-testid="report-by-month">
      <h3 className="mb-1 text-base font-medium text-white">By month the charge is for</h3>
      <p className="mb-3 text-xs text-white/40">"Rent — August" is August's rent, whenever it was paid.</p>
      <Table head={["Month", "Category", "Invoiced", "Collected", "Still owed"]} minWidth={640}>
        {shown.map((r) => (
          <tr key={`${r.month}-${r.category_name}`} className="border-t border-white/5">
            <td className="py-2 pr-3">{r.month_label}</td>
            <td className="py-2 pl-3 text-right">{r.category_name}</td>
            <td className="py-2 pl-3 text-right"><Money value={r.invoiced} /></td>
            <td className="py-2 pl-3 text-right"><Money value={r.collected} strong /></td>
            <td className="py-2 pl-3 text-right"><Money value={r.outstanding} warn /></td>
          </tr>
        ))}
      </Table>
      {rows.length > perPage && (
        <Pagination page={page} perPage={perPage} total={rows.length} onPageChange={setPage}
          onPerPageChange={(n) => { setPerPage(n); setPage(1); }} />
      )}
    </div>
  );
}

function CategorySection({ section }) {
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(25);
  if (!section.rows.length) return null;
  const pageRows = section.rows.slice((page - 1) * perPage, page * perPage);
  return (
    <div className="glass overflow-hidden p-5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-base font-medium text-white">{section.category_name}</h3>
        <span className="rounded bg-white/5 px-1.5 py-0.5 text-xs uppercase tracking-wide text-white/40">{section.kind}</span>
        <span className="ml-auto text-xs text-white/40">{section.rows.length} tenant(s)</span>
      </div>
      <Table head={["Tenant", "Property · Unit", ...MONEY.map((c) => c.label)]} minWidth={1100}>
        {pageRows.map((r) => (
          <tr key={r.tenant_id} className="border-t border-white/5">
            <td className="py-2 pr-3">{r.tenant_name}</td>
            <td className="py-2 pl-3 text-right text-white/60">{r.property_name} · {r.unit_name}</td>
            {MONEY.map((c) => <td key={c.key} className="py-2 pl-3 text-right"><Money value={r[c.key]} strong={c.strong} warn={c.warn} /></td>)}
          </tr>
        ))}
        <tr className="border-t-2 border-white/15 font-semibold text-white">
          <td className="py-2 pr-3" colSpan={2}>Total (all {section.rows.length})</td>
          {MONEY.map((c) => <td key={c.key} className="whitespace-nowrap py-2 pl-3 text-right">{formatCurrency(section.totals[c.key] || 0)}</td>)}
        </tr>
      </Table>
      {section.rows.length > perPage && (
        <Pagination page={page} perPage={perPage} total={section.rows.length} onPageChange={setPage}
          onPerPageChange={(n) => { setPerPage(n); setPage(1); }} />
      )}
    </div>
  );
}

function Ledger({ data, page, perPage, setPage, setPerPage }) {
  const rows = data?.ledger ?? [];
  return (
    <div className="glass p-5" data-testid="report-ledger">
      <h3 className="mb-1 text-base font-medium text-white">Allocation ledger</h3>
      <p className="mb-3 text-xs text-white/40">
        Every amount collected, the invoice line it cleared and the month it was for — the same lines as the receipts.
        {" "}{data?.ledger_total ?? 0} line(s) · {formatCurrency(data?.ledger_sum ?? 0)}.
      </p>
      <Table head={["Paid on", "Receipt", "M-Pesa / ref", "Tenant", "Property · Unit", "Invoice", "Charge", "For month", "Amount"]} minWidth={1200}>
        {rows.map((r, i) => (
          <tr key={`${r.receipt_no}-${r.invoice_number}-${r.month_for}-${i}`} className="border-t border-white/5">
            <td className="py-2 pr-3">{formatDate(r.payment_date)}</td>
            <td className="py-2 pl-3 text-right">{r.receipt_no}</td>
            <td className="py-2 pl-3 text-right text-white/60">{r.mpesa_ref || r.source}</td>
            <td className="py-2 pl-3 text-right">{r.tenant_name}</td>
            <td className="py-2 pl-3 text-right text-white/60">{r.property_name} · {r.unit_name}</td>
            <td className="py-2 pl-3 text-right text-white/60">{r.invoice_number}</td>
            <td className="py-2 pl-3 text-right">{r.category} <span className="text-xs text-white/40">{r.type}</span></td>
            <td className="py-2 pl-3 text-right">{r.month_label}</td>
            <td className="py-2 pl-3 text-right font-medium text-white">{formatCurrency(r.amount)}</td>
          </tr>
        ))}
      </Table>
      <Pagination page={page} perPage={perPage} total={data?.ledger_total ?? 0} onPageChange={setPage}
        onPerPageChange={(n) => { setPerPage(n); setPage(1); }} />
    </div>
  );
}

export default function PaymentsReport({ properties = [] }) {
  const [categoryId, setCategoryId] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [view, setView] = useState("summary");
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerPerPage, setLedgerPerPage] = useState(50);

  const { data: catData } = useGetChargeCategoriesQuery({ include_inactive: 0 });
  const categories = catData?.categories ?? [];

  const params = {
    category_id: categoryId,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(propertyId ? { property_id: propertyId } : {}),
  };
  const { data, isFetching } = useGetPaymentsReportQuery(
    { ...params, ledger_page: ledgerPage, ledger_per_page: ledgerPerPage },
    // Payments also arrive from outside this browser — Co-pilot, M-Pesa
    // callbacks, a colleague. Refetch when the tab regains focus and every
    // 30 s while the report is open, so it never shows yesterday's figures.
    { refetchOnMountOrArgChange: true, refetchOnFocus: true, pollingInterval: 30000 },
  );
  const sections = data?.categories ?? [];
  const grand = data?.grand_total;
  const recon = data?.reconciliation;
  const reset = (fn) => (e) => { fn(e.target.value); setLedgerPage(1); };

  return (
    <div className="space-y-6">
      <div className="glass grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
        <Select
          label="Category"
          value={categoryId}
          onChange={reset(setCategoryId)}
          options={[
            { value: "all", label: "All categories" },
            ...categories.map((c) => ({ value: String(c.id), label: `${c.name} (${c.kind})` })),
          ]}
        />
        <DatePicker label="Paid from" value={dateFrom} onChange={reset(setDateFrom)} />
        <DatePicker label="Paid to" value={dateTo} onChange={reset(setDateTo)} />
        <Select
          label="Property"
          value={propertyId}
          onChange={reset(setPropertyId)}
          options={[
            { value: "", label: "All properties" },
            ...properties.map((p) => ({ value: String(p.id), label: p.name })),
          ]}
        />
        <div className="flex flex-wrap items-center justify-between gap-3 sm:col-span-2 lg:col-span-4">
          <ExportButtons endpoint="/reports/payments" filenameBase="payments-report" params={params} />
          {data?.generated_at && (
            <span className="text-xs text-white/40">Live figures · {isFetching ? "refreshing…" : "up to date"}</span>
          )}
        </div>
      </div>

      {!data && isFetching ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : sections.length === 0 ? (
        <div className="glass p-8 text-center text-sm text-white/40">
          No categories or payments to report on for this selection.
        </div>
      ) : (
        <>
          {recon && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="report-reconciliation">
              <SummaryCard label={`Cash received (${recon.payments} payments)`} value={formatCurrency(recon.cash_received)} icon={<Wallet className="h-5 w-5" />} />
              <SummaryCard label="Allocated to charges" value={formatCurrency(recon.allocated_to_charges)} icon={<FileText className="h-5 w-5" />} accent="third" />
              <SummaryCard label="Held as advance credit" value={formatCurrency(recon.advance_to_credit)} icon={<Scale className="h-5 w-5" />} accent="third" />
              <SummaryCard
                label={recon.difference === 0 ? "Balances — nothing unexplained" : "Unexplained difference"}
                value={formatCurrency(recon.difference)}
                icon={<AlertCircle className="h-5 w-5" />}
                accent={recon.difference === 0 ? "third" : undefined}
              />
            </div>
          )}

          <Tabs
            tabs={[
              { key: "summary", label: "Summary" },
              { key: "month", label: "By month" },
              { key: "tenants", label: "Per tenant" },
              { key: "ledger", label: "Allocation ledger", count: data?.ledger_total || undefined },
            ]}
            activeKey={view}
            onChange={setView}
          />

          {view === "summary" && <SummaryTable rows={data?.summary ?? []} grand={categoryId === "all" ? grand : null} />}
          {view === "month" && <ByMonth rows={data?.by_month ?? []} />}
          {view === "tenants" && sections.map((s) => <CategorySection key={s.category_id} section={s} />)}
          {view === "ledger" && (
            <Ledger data={data} page={ledgerPage} perPage={ledgerPerPage} setPage={setLedgerPage} setPerPage={setLedgerPerPage} />
          )}
        </>
      )}
    </div>
  );
}
