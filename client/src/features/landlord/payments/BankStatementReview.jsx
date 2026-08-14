import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Wand2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Checkbox from "@/components/ui/Checkbox";
import Select from "@/components/ui/Select";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import {
  useGetBankStatementTransactionsQuery,
  useImportBankStatementTransactionsMutation,
  useLazyGetTenantOutstandingItemsQuery,
} from "./paymentApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

const STEPS = ["Select", "Match", "Allocate"];

// 3-step bank-statement import wizard: (1) select which parsed transactions to
// bring in, (2) match each to a tenant (auto by account number, or manually),
// (3) allocate each matched payment (auto by priority order, or manually per
// line) before saving. Unmatched rows still import — as pending payments that
// show up with the "Review" action on the Payments page for later matching.
export default function BankStatementReview() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, isLoading } = useGetBankStatementTransactionsQuery(id);
  const { data: tenantsData } = useGetTenantsQuery();
  const tenants = toRows(tenantsData);
  const [importTransactions, { isLoading: isSaving }] = useImportBankStatementTransactionsMutation();
  const [fetchOutstanding] = useLazyGetTenantOutstandingItemsQuery();

  const rows = toRows(data);
  const importable = rows.filter((r) => !r.is_imported);

  const [step, setStep] = useState(0);
  const [selectedIds, setSelectedIds] = useState([]);
  const [matches, setMatches] = useState({});       // txn_id -> tenant_id (string)
  const [modes, setModes] = useState({});            // txn_id -> "auto" | "manual"
  const [manualLines, setManualLines] = useState({}); // txn_id -> { line_item_id: amountString }
  const [outstandingByTxn, setOutstandingByTxn] = useState({}); // txn_id -> { invoices: [...] }
  const [loadingOutstanding, setLoadingOutstanding] = useState({});

  const selectedRows = importable.filter((r) => selectedIds.includes(r.id));
  const matchedRows = selectedRows.filter((r) => matches[r.id]);
  const unmatchedRows = selectedRows.filter((r) => !matches[r.id]);

  // ---- Step 1: select ----
  const toggle = (txnId) => setSelectedIds((prev) => (prev.includes(txnId) ? prev.filter((x) => x !== txnId) : [...prev, txnId]));
  const selectAll = () => setSelectedIds(importable.map((r) => r.id));
  const clearAll = () => setSelectedIds([]);

  const selectColumns = [
    { key: "select", header: "", render: (row) => <Checkbox checked={selectedIds.includes(row.id)} onChange={() => toggle(row.id)} /> },
    { key: "txn_date", header: "Date", render: (row) => formatDate(row.txn_date) },
    { key: "description", header: "Description" },
    { key: "reference", header: "Reference" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "imported", header: "Imported", render: (row) => (row.is_imported ? "Yes" : "No") },
  ];

  // ---- Step 2: match ----
  const autoMatch = () => {
    let matchedCount = 0;
    const next = { ...matches };
    selectedRows.forEach((row) => {
      if (next[row.id]) return; // don't clobber an existing manual pick
      const haystack = `${row.reference || ""} ${row.description || ""}`.toLowerCase();
      const found = tenants.filter((t) => t.account_number && haystack.includes(String(t.account_number).toLowerCase()));
      if (found.length === 1) {
        next[row.id] = String(found[0].id);
        matchedCount += 1;
      }
    });
    setMatches(next);
    toast(matchedCount ? `Matched ${matchedCount} transaction(s) by account number.` : "No account-number matches found — match manually.", {
      type: matchedCount ? "success" : "info",
    });
  };

  const setMatch = (txnId, tenantId) => {
    setMatches((m) => ({ ...m, [txnId]: tenantId }));
  };

  // ---- Step 3: allocate ----
  const loadOutstanding = async (txnId, tenantId) => {
    if (!tenantId || outstandingByTxn[txnId]) return;
    setLoadingOutstanding((s) => ({ ...s, [txnId]: true }));
    try {
      const result = await fetchOutstanding(tenantId).unwrap();
      setOutstandingByTxn((s) => ({ ...s, [txnId]: result }));
      // Seed manual amounts at 0 for each line, ready to edit.
      setManualLines((s) => {
        if (s[txnId]) return s;
        const seed = {};
        (result.invoices || []).forEach((inv) => (inv.lines || []).forEach((l) => { seed[l.line_item_id] = ""; }));
        return { ...s, [txnId]: seed };
      });
    } finally {
      setLoadingOutstanding((s) => ({ ...s, [txnId]: false }));
    }
  };

  const goToAllocate = () => {
    matchedRows.forEach((row) => {
      if (!modes[row.id]) setModes((m) => ({ ...m, [row.id]: "auto" }));
    });
    setStep(2);
  };

  const setMode = (txnId, mode) => {
    setModes((m) => ({ ...m, [txnId]: mode }));
    if (mode === "manual") loadOutstanding(txnId, matches[txnId]);
  };

  const autoAllocateAll = () => {
    const next = { ...modes };
    matchedRows.forEach((row) => { next[row.id] = "auto"; });
    setModes(next);
    toast("All matched payments set to auto-allocate.", { type: "success" });
  };

  const manualTotalFor = (txnId) =>
    Object.values(manualLines[txnId] || {}).reduce((s, v) => s + (Number(v) || 0), 0);

  const isOverAllocated = (row) => {
    if (modes[row.id] !== "manual") return false;
    return manualTotalFor(row.id) > Number(row.amount) + 0.001;
  };

  const anyOverAllocated = matchedRows.some(isOverAllocated);

  // ---- Save ----
  const handleSave = async () => {
    if (anyOverAllocated) {
      toast("Fix over-allocated rows before saving.", { type: "error" });
      return;
    }
    const tenant_mappings = {};
    const allocations = {};
    matchedRows.forEach((row) => {
      tenant_mappings[row.id] = matches[row.id];
      if (modes[row.id] === "manual") {
        const lines = Object.entries(manualLines[row.id] || {})
          .map(([line_item_id, v]) => ({ line_item_id: Number(line_item_id), amount: Number(v) || 0 }))
          .filter((l) => l.amount > 0);
        allocations[row.id] = { mode: "manual", lines };
      } else {
        allocations[row.id] = { mode: "auto" };
      }
    });

    try {
      const result = await importTransactions({
        id,
        transaction_ids: selectedIds,
        tenant_mappings,
        allocations,
      }).unwrap();
      toast(`${result?.payments?.length ?? selectedIds.length} payment(s) imported.`, { type: "success" });
      navigate(LANDLORD_ROUTES.payments);
    } catch (err) {
      toast(err?.data?.error || "Could not import the selected transactions.", { type: "error" });
    }
  };

  const tenantLabel = (tid) => {
    const t = tenants.find((x) => String(x.id) === String(tid));
    return t ? `${t.first_name} ${t.last_name}` : "—";
  };

  return (
    <div>
      <PageHeader
        title="Review bank statement"
        subtitle={`Step ${step + 1} of 3 — ${STEPS[step]}`}
        breadcrumbs={[{ label: "Payments", to: LANDLORD_ROUTES.payments }, { label: "Statement review" }]}
        actions={
          <Link to={LANDLORD_ROUTES.payments}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Back to payments
            </Button>
          </Link>
        }
      />

      <div className="mb-6 flex items-center gap-2">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center gap-2">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
                i < step ? "bg-secondary text-white" : i === step ? "bg-secondary/20 text-secondary border border-secondary/40" : "bg-white/5 text-white/40"
              }`}
            >
              {i < step ? <Check className="h-3.5 w-3.5" /> : i + 1}
            </div>
            <span className={`text-sm ${i === step ? "text-white" : "text-white/40"}`}>{label}</span>
            {i < STEPS.length - 1 && <div className="mx-2 h-px w-8 bg-white/10" />}
          </div>
        ))}
      </div>

      {step === 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-white/50">{selectedIds.length} of {importable.length} selected</p>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={selectAll}>Select all</Button>
              <Button variant="ghost" size="sm" onClick={clearAll}>Clear</Button>
            </div>
          </div>
          <ResponsiveTable columns={selectColumns} rows={rows} isLoading={isLoading} />
          <div className="flex justify-end pt-2">
            <Button rightIcon={<ArrowRight className="h-4 w-4" />} disabled={!selectedIds.length} onClick={() => setStep(1)}>
              Next — match tenants
            </Button>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-white/50">
              {matchedRows.length} matched, {unmatchedRows.length} unmatched
            </p>
            <Button variant="subtle" size="sm" leftIcon={<Wand2 className="h-4 w-4" />} onClick={autoMatch}>
              Auto-match by account number
            </Button>
          </div>
          <div className="glass table-scroll max-h-[65vh] w-full min-w-0 max-w-full">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 z-10 bg-primary-800">
                <tr className="border-b border-white/10 text-white/40">
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Date</th>
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Description</th>
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Reference</th>
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Amount</th>
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Tenant</th>
                  <th className="whitespace-nowrap px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {selectedRows.map((row) => (
                  <tr key={row.id} className="border-b border-white/5">
                    <td className="whitespace-nowrap px-4 py-3 text-white/80">{formatDate(row.txn_date)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-white/80">{row.description}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-white/60">{row.reference}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-white/80">{formatCurrency(row.amount)}</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <Select
                        value={matches[row.id] || ""}
                        onChange={(e) => setMatch(row.id, e.target.value)}
                        options={tenants.map((t) => ({ value: String(t.id), label: `${t.first_name} ${t.last_name}${t.account_number ? ` (${t.account_number})` : ""}` }))}
                        placeholder="Unmatched"
                        className="min-w-[220px]"
                      />
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {matches[row.id] ? <Badge color="emerald">Matched</Badge> : <Badge color="amber">Unmatched</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-between pt-2">
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep(0)}>
              Back
            </Button>
            <Button rightIcon={<ArrowRight className="h-4 w-4" />} onClick={goToAllocate}>
              Next — allocate
            </Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-white/50">
              {matchedRows.length} payment(s) will be allocated. {unmatchedRows.length} unmatched row(s) will import as pending — review them later from the Payments page.
            </p>
            <Button variant="subtle" size="sm" leftIcon={<Wand2 className="h-4 w-4" />} onClick={autoAllocateAll}>
              Auto-allocate all checked
            </Button>
          </div>

          {unmatchedRows.length > 0 && (
            <div className="glass border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
              {unmatchedRows.length} transaction(s) have no tenant match and will import as pending payments —
              you can match and allocate them afterwards from the amber "Review" button on the Payments page.
            </div>
          )}

          <div className="space-y-3">
            {matchedRows.map((row) => {
              const mode = modes[row.id] || "auto";
              const outstanding = outstandingByTxn[row.id];
              const overAllocated = isOverAllocated(row);
              return (
                <div key={row.id} className="glass space-y-3 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-white">{tenantLabel(matches[row.id])}</p>
                      <p className="text-xs text-white/40">{row.description} · {formatDate(row.txn_date)}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-semibold text-white">{formatCurrency(row.amount)}</span>
                      <div className="flex gap-1 rounded-lg bg-white/5 p-1">
                        <button
                          onClick={() => setMode(row.id, "auto")}
                          className={`rounded-md px-3 py-1 text-xs transition-colors ${mode === "auto" ? "bg-secondary/20 text-white" : "text-white/50 hover:text-white"}`}
                        >
                          Auto
                        </button>
                        <button
                          onClick={() => setMode(row.id, "manual")}
                          className={`rounded-md px-3 py-1 text-xs transition-colors ${mode === "manual" ? "bg-secondary/20 text-white" : "text-white/50 hover:text-white"}`}
                        >
                          Manual
                        </button>
                      </div>
                    </div>
                  </div>

                  {mode === "auto" && (
                    <p className="text-xs text-white/50">Allocated by your priority order (Settings → Payments) when saved.</p>
                  )}

                  {mode === "manual" && (
                    <div>
                      {loadingOutstanding[row.id] || !outstanding ? (
                        <div className="flex justify-center py-4"><Spinner /></div>
                      ) : outstanding.invoices.length === 0 ? (
                        <p className="text-sm text-white/50">No outstanding charges — full amount becomes advance credit.</p>
                      ) : (
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-xs text-white/40">
                              <th className="py-1 font-medium">Charge</th>
                              <th className="py-1 font-medium">Invoice</th>
                              <th className="py-1 text-right font-medium">Balance</th>
                              <th className="py-1 text-right font-medium">Allocate</th>
                            </tr>
                          </thead>
                          <tbody>
                            {outstanding.invoices.map((inv) =>
                              (inv.lines || []).map((line) => (
                                <tr key={line.line_item_id} className="border-t border-white/5 text-white/80">
                                  <td className="py-1.5">{line.label}</td>
                                  <td className="py-1.5 text-xs text-white/40">{inv.invoice_number}</td>
                                  <td className="py-1.5 text-right">{formatCurrency(line.remaining)}</td>
                                  <td className="py-1.5 text-right">
                                    <input
                                      type="number"
                                      min="0"
                                      step="0.01"
                                      value={manualLines[row.id]?.[line.line_item_id] ?? ""}
                                      onChange={(e) =>
                                        setManualLines((s) => ({
                                          ...s,
                                          [row.id]: { ...s[row.id], [line.line_item_id]: e.target.value },
                                        }))
                                      }
                                      className="w-24 rounded-lg bg-white/10 px-2 py-1 text-right text-white outline-none focus:ring-1 focus:ring-secondary"
                                    />
                                  </td>
                                </tr>
                              ))
                            )}
                          </tbody>
                        </table>
                      )}
                      <div className="mt-2 flex justify-between border-t border-white/10 pt-2 text-sm">
                        <span className="text-white/50">{overAllocated ? "Over-allocated!" : "Unallocated (advance)"}</span>
                        <span className={overAllocated ? "font-semibold text-red-400" : "text-white/80"}>
                          {formatCurrency(Math.max(0, Number(row.amount) - manualTotalFor(row.id)))}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex justify-between pt-2">
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep(1)}>
              Back
            </Button>
            <Button leftIcon={<Check className="h-4 w-4" />} isLoading={isSaving} disabled={anyOverAllocated} onClick={handleSave}>
              Save {selectedIds.length} payment(s)
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
