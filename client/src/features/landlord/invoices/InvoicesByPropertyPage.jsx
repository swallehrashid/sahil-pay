import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, ChevronRight, Building2, FileText, AlertTriangle } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Spinner from "@/components/ui/Spinner";
import SummaryCard from "@/components/ui/SummaryCard";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { matchesAllWords } from "@/utils/search";
import { usePortalRoutes } from "@/hooks/usePortalRoutes";
import {
  useGetMonthlyByPropertyQuery,
  useGetMonthlyPropertyPreviewQuery,
  useRunMonthlyInvoicingMutation,
} from "./invoiceQueueApiSlice";

/**
 * Monthly invoices, ONE PROPERTY AT A TIME.
 *
 * The whole-portfolio run is one click and a thousand invoices; a wrong rent on
 * one block goes out to everyone before anybody sees it. Here a manager works
 * down the list: open a property, see exactly what each tenant will be billed
 * (rent, queued meter readings, arrears carried forward), generate, confirm,
 * and move to the next — with the list showing which properties are done.
 *
 * Generating calls the same engine as the 1st-of-month run, scoped to one
 * property, so it is idempotent: a property can be run twice without billing
 * anyone twice.
 */
const STATUS = {
  done: { label: "Invoiced", cls: "bg-emerald-400/15 text-emerald-300" },
  partial: { label: "Partly invoiced", cls: "bg-amber-400/15 text-amber-300" },
  pending: { label: "Not yet", cls: "bg-white/10 text-white/60" },
  empty: { label: "No tenants", cls: "bg-white/5 text-white/30" },
};
const ROW_STATUS = {
  new: "Will be invoiced",
  already_invoiced: "Already invoiced",
  nothing_to_bill: "Nothing to bill",
  no_unit: "No unit",
};

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function InvoicesByPropertyPage() {
  const ROUTES = usePortalRoutes();
  const [params] = useSearchParams();
  const [month, setMonth] = useState(thisMonth());
  const [picked, setSelected] = useState(params.get("property") ? Number(params.get("property")) : null);
  const [filter, setFilter] = useState("");
  const [includeRent, setIncludeRent] = useState(true);
  const [includeQueued, setIncludeQueued] = useState(true);
  const [confirming, setConfirming] = useState(false);

  const { data: overview, isFetching: loadingList, refetch: refetchList } = useGetMonthlyByPropertyQuery({ month });
  const properties = useMemo(() => overview?.properties ?? [], [overview]);
  // Until one is picked, open the first property that still needs invoicing.
  const selected = picked ?? (
    properties.find((p) => p.status === "pending" || p.status === "partial") ?? properties[0]
  )?.property_id ?? null;
  const { data: preview, isFetching: loadingPreview, refetch: refetchPreview } = useGetMonthlyPropertyPreviewQuery(
    { propertyId: selected, month, include_rent: includeRent, include_queued: includeQueued },
    { skip: !selected },
  );
  const [runMonthly, { isLoading: generating }] = useRunMonthlyInvoicingMutation();

  const visible = useMemo(
    () => properties.filter((p) => matchesAllWords([p.property_name, p.city], filter)),
    [properties, filter],
  );
  const currentIndex = properties.findIndex((p) => p.property_id === selected);
  const nextPending = properties.find((p, i) => i > currentIndex && (p.status === "pending" || p.status === "partial"))
    ?? properties.find((p) => p.property_id !== selected && (p.status === "pending" || p.status === "partial"));

  const monthLabel = new Date(`${month}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  const summary = preview?.summary;

  const generate = async () => {
    setConfirming(false);
    try {
      const issue = month === thisMonth() ? undefined : `${month}-01`;
      const res = await runMonthly({
        include_rent: includeRent, include_queued: includeQueued,
        property_ids: [selected], ...(issue ? { issue_date: issue } : {}),
      }).unwrap();
      const r = res?.result ?? {};
      toast(`${preview?.property_name}: ${r.created ?? 0} invoice(s) created, ${r.updated ?? 0} updated, `
            + `${r.skipped ?? 0} already invoiced.`, { type: "success", duration: 7000 });
      refetchList();
      refetchPreview();
    } catch (err) {
      toast(err?.data?.error || err?.data?.message || "Could not generate the invoices.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader
        title="Invoice by property"
        subtitle={`Generate ${monthLabel}'s invoices one property at a time — check, confirm, next.`}
        breadcrumbs={[{ label: "Invoices", to: ROUTES.invoices }, { label: "By property" }]}
        actions={
          <Link to={ROUTES.invoices}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back to invoices</Button>
          </Link>
        }
      />

      <div className="glass mb-6 flex flex-wrap items-end gap-4 p-4">
        <div className="w-48">
          <Input label="Month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
        </div>
        <Checkbox label="Rent & fixed monthly charges" checked={includeRent} onChange={(e) => setIncludeRent(e.target.checked)} />
        <Checkbox label="Approved queued charges" checked={includeQueued} onChange={(e) => setIncludeQueued(e.target.checked)} />
        {overview?.summary && (
          <span className="ml-auto text-sm text-white/60" data-testid="by-property-progress">
            <strong className="text-white">{overview.summary.done}</strong> of {overview.summary.properties} properties invoiced for {monthLabel}
          </span>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* The list — which properties are done */}
        <div className="glass flex max-h-[70vh] flex-col p-3">
          <Input placeholder="Find a property…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className="mt-3 flex-1 space-y-1 overflow-y-auto" data-testid="by-property-list">
            {loadingList && !properties.length ? <Spinner className="mx-auto my-8" /> : visible.map((p) => (
              <button
                key={p.property_id}
                type="button"
                onClick={() => setSelected(p.property_id)}
                className={"flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors "
                  + (p.property_id === selected ? "bg-secondary/20 ring-1 ring-secondary/50" : "hover:bg-white/5")}
              >
                <Building2 className="h-4 w-4 flex-shrink-0 text-white/40" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-white">{p.property_name}</span>
                  <span className="block text-xs text-white/40">{p.invoiced}/{p.tenants} tenants invoiced</span>
                </span>
                <span className={"rounded-full px-2 py-0.5 text-[10px] " + (STATUS[p.status]?.cls ?? "")}>{STATUS[p.status]?.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* The selected property — what will be billed */}
        <div className="glass p-5" data-testid="by-property-preview">
          {!selected ? (
            <p className="text-sm text-white/50">Pick a property.</p>
          ) : loadingPreview && !preview ? (
            <Spinner className="mx-auto my-12" />
          ) : preview ? (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <h3 className="text-lg font-medium text-white">{preview.property_name}</h3>
                <span className="text-sm text-white/50">— {monthLabel}</span>
              </div>
              <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <SummaryCard label="To invoice" value={`${summary.to_invoice} / ${summary.tenants}`} icon={<FileText className="h-5 w-5" />} />
                <SummaryCard label="Rent" value={formatCurrency(summary.rent)} accent="third" />
                <SummaryCard label="Queued charges" value={formatCurrency(summary.queued)} accent="third" />
                <SummaryCard label="Arrears b/f" value={formatCurrency(summary.balance_bf)} />
              </div>
              <div className="table-scroll max-h-[46vh] overflow-auto">
                <table className="w-full min-w-[720px] text-sm">
                  <thead>
                    <tr className="text-xs text-white/40">
                      <th className="pb-2 text-left font-medium">Unit</th>
                      <th className="pb-2 text-left font-medium">Tenant</th>
                      <th className="pb-2 text-right font-medium">Rent</th>
                      <th className="pb-2 text-right font-medium">Queued</th>
                      <th className="pb-2 text-right font-medium">Arrears b/f</th>
                      <th className="pb-2 text-right font-medium">Invoice total</th>
                      <th className="pb-2 pl-3 text-left font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="text-white/80">
                    {preview.tenants.map((t) => (
                      <tr key={t.tenant_id} className="border-t border-white/5">
                        <td className="py-2">{t.unit_name}</td>
                        <td className="py-2">{t.tenant_name}</td>
                        <td className="py-2 text-right">{formatCurrency(t.rent + t.other_fixed)}</td>
                        <td className="py-2 text-right">{formatCurrency(t.queued)}</td>
                        <td className="py-2 text-right">{formatCurrency(t.balance_bf)}</td>
                        <td className="py-2 text-right font-medium text-white">{formatCurrency(t.total)}</td>
                        <td className="py-2 pl-3">
                          <span className={t.status === "new" ? "text-secondary-300" : "text-white/45"}>{ROW_STATUS[t.status] ?? t.status}</span>
                          {t.note && <span className="block text-xs text-white/40">{t.note}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
                {summary.to_invoice === 0 ? (
                  <span className="inline-flex items-center gap-2 text-sm text-emerald-300">
                    <CheckCircle2 className="h-4 w-4" /> Every tenant here is invoiced for {monthLabel}.
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2 text-sm text-white/60">
                    <AlertTriangle className="h-4 w-4 text-amber-300" />
                    {summary.to_invoice} invoice(s) will be raised for {preview.property_name}.
                  </span>
                )}
                <div className="flex gap-3">
                  <Button data-testid="by-property-generate" disabled={summary.to_invoice === 0 && !summary.queued}
                          isLoading={generating} onClick={() => setConfirming(true)}>
                    Generate for this property
                  </Button>
                  {nextPending && (
                    <Button variant="ghost" data-testid="by-property-next" rightIcon={<ChevronRight className="h-4 w-4" />}
                            onClick={() => setSelected(nextPending.property_id)}>
                      Next: {nextPending.property_name}
                    </Button>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirming}
        onClose={() => setConfirming(false)}
        onConfirm={generate}
        title={`Generate ${monthLabel} invoices for ${preview?.property_name ?? "this property"}?`}
        description={summary
          ? `${summary.to_invoice} tenant(s) will be invoiced — rent ${formatCurrency(summary.rent)}, queued charges ${formatCurrency(summary.queued)}, arrears carried forward ${formatCurrency(summary.balance_bf)}. Tenants already invoiced this month are not billed again.`
          : ""}
        confirmLabel="Confirm & generate"
      />
    </div>
  );
}
