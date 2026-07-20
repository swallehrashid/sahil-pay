import { useState, useMemo, useEffect } from "react";
import { ExternalLink, CheckCircle2, XCircle } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Spinner from "@/components/ui/Spinner";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { toRows } from "@/utils/tableAdapters";
import {
  useGetAllocationPreviewQuery,
  useConfirmPaymentMutation,
  useDeclinePaymentMutation,
} from "./paymentApiSlice";

// Landlord/team reviews a submitted payment (tenant-submitted, co-pilot, or an
// unmatched bank-statement import): check the proof, match/re-match it to a
// tenant if needed, then confirm — allocating either automatically (the
// landlord's configured priority order) or manually across the outstanding
// invoices — or decline it.
export default function ConfirmPaymentModal({ payment, onClose }) {
  const paymentId = payment?.id;
  const [tenantId, setTenantId] = useState(payment?.tenant_id ? String(payment.tenant_id) : "");
  const { data: tenantsData } = useGetTenantsQuery();
  const tenants = toRows(tenantsData);

  useEffect(() => {
    setTenantId(payment?.tenant_id ? String(payment.tenant_id) : "");
  }, [payment?.id, payment?.tenant_id]);

  const { data: preview, isLoading } = useGetAllocationPreviewQuery(
    paymentId ? { id: paymentId, tenant_id: tenantId || undefined } : undefined,
    { skip: !paymentId }
  );
  const [confirmPayment, { isLoading: isConfirming }] = useConfirmPaymentMutation();
  const [declinePayment, { isLoading: isDeclining }] = useDeclinePaymentMutation();

  const [mode, setMode] = useState("auto");
  const [manual, setManual] = useState({}); // invoice_id -> amount string
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");

  // Seed the manual editor (keyed by line item) from the auto proposal.
  useEffect(() => {
    if (preview?.outstanding) {
      const seed = {};
      preview.outstanding.forEach((inv) =>
        (inv.lines || []).forEach((l) => { seed[l.line_item_id] = String(l.proposed_amount || 0); })
      );
      setManual(seed);
    }
  }, [preview]);

  const manualTotal = useMemo(
    () => Object.values(manual).reduce((s, v) => s + (Number(v) || 0), 0),
    [manual]
  );
  const amount = preview?.amount ?? Number(payment?.amount ?? 0);
  const overAllocated = manualTotal > amount + 0.001;
  const needsTenant = !tenantId;

  const handleConfirm = async () => {
    if (needsTenant) return;
    const body = mode === "manual"
      ? {
          tenant_id: Number(tenantId),
          mode: "manual",
          allocations: Object.entries(manual)
            .map(([line_item_id, v]) => ({ line_item_id: Number(line_item_id), amount: Number(v) || 0 }))
            .filter((a) => a.amount > 0),
        }
      : { tenant_id: Number(tenantId), mode: "auto" };
    try {
      await confirmPayment({ id: paymentId, ...body }).unwrap();
      toast("Payment confirmed.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not confirm payment.", { type: "error" });
    }
  };

  const handleDecline = async () => {
    try {
      await declinePayment({ id: paymentId, reason }).unwrap();
      toast("Payment declined.", { type: "success" });
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not decline payment.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={!!payment} onClose={onClose} title="Review submitted payment">
      {isLoading || !preview ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-xl bg-white/5 p-4 text-sm">
            <span className="text-white/50">Amount</span>
            <span className="text-right font-semibold text-white">{formatCurrency(amount)}</span>
            <span className="text-white/50">Reference</span>
            <span className="text-right text-white/80">{payment?.mpesa_reference || payment?.payment_ref}</span>
            <span className="text-white/50">Proof</span>
            <span className="text-right">
              {payment?.proof_url ? (
                <a href={payment.proof_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-secondary hover:underline">
                  View proof <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : (
                <span className="text-white/40">No attachment</span>
              )}
            </span>
          </div>

          <Select
            label="Tenant"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            options={tenants.map((t) => ({ value: String(t.id), label: `${t.first_name} ${t.last_name}${t.account_number ? ` (${t.account_number})` : ""}` }))}
            placeholder="Match this payment to a tenant first…"
            hint={needsTenant ? "This payment isn't matched to a tenant yet — select one to allocate it." : "Change this to re-match the payment before confirming."}
            required
          />

          {!declining && (
            <>
              <div className="flex gap-2">
                <button
                  disabled={needsTenant}
                  onClick={() => setMode("auto")}
                  className={`flex-1 rounded-xl px-3 py-2 text-sm transition-colors ${mode === "auto" ? "bg-secondary/20 text-white" : "bg-white/5 text-white/60 hover:text-white"}`}
                >
                  Auto-allocate
                </button>
                <button
                  disabled={needsTenant}
                  onClick={() => setMode("manual")}
                  className={`flex-1 rounded-xl px-3 py-2 text-sm transition-colors ${mode === "manual" ? "bg-secondary/20 text-white" : "bg-white/5 text-white/60 hover:text-white"}`}
                >
                  Allocate manually
                </button>
              </div>

              <div>
                <p className="mb-2 text-xs text-white/50">
                  {needsTenant
                    ? "Select a tenant above to see and adjust the allocation."
                    : mode === "auto"
                    ? "Already auto-allocated in your configured priority order (Settings → Payments) — review and confirm, or switch to manual to adjust."
                    : "Set how much of this payment goes to each charge."}
                </p>
                {needsTenant ? null : preview.outstanding.length === 0 ? (
                  <p className="text-sm text-white/50">No outstanding charges — the full amount will be credited as advance balance.</p>
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
                      {preview.outstanding.map((inv) =>
                        (inv.lines || []).map((line) => (
                          <tr key={line.line_item_id} className="border-t border-white/5 text-white/80">
                            <td className="py-1.5">{line.label}</td>
                            <td className="py-1.5 text-xs text-white/40">{inv.invoice_number}</td>
                            <td className="py-1.5 text-right">{formatCurrency(line.remaining)}</td>
                            <td className="py-1.5 text-right">
                              {mode === "auto" ? (
                                <span className={line.proposed_amount > 0 ? "text-secondary" : "text-white/30"}>
                                  {formatCurrency(line.proposed_amount)}
                                </span>
                              ) : (
                                <input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={manual[line.line_item_id] ?? ""}
                                  onChange={(e) => setManual((m) => ({ ...m, [line.line_item_id]: e.target.value }))}
                                  className="w-24 rounded-lg bg-white/10 px-2 py-1 text-right text-white outline-none focus:ring-1 focus:ring-secondary"
                                />
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                )}
                {!needsTenant && (
                  <div className="mt-2 flex justify-between border-t border-white/10 pt-2 text-sm">
                    <span className="text-white/50">
                      {mode === "auto" ? "Advance credit" : overAllocated ? "Over-allocated!" : "Unallocated (advance)"}
                    </span>
                    <span className={overAllocated ? "font-semibold text-red-400" : "text-white/80"}>
                      {formatCurrency(mode === "auto" ? preview.advance_credit : Math.max(0, amount - manualTotal))}
                    </span>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between gap-3 pt-2">
                <Button variant="ghost" leftIcon={<XCircle className="h-4 w-4" />} onClick={() => setDeclining(true)}>
                  Decline
                </Button>
                <Button leftIcon={<CheckCircle2 className="h-4 w-4" />} isLoading={isConfirming} disabled={needsTenant || overAllocated} onClick={handleConfirm}>
                  Confirm payment
                </Button>
              </div>
            </>
          )}

          {declining && (
            <div className="space-y-3">
              <Input label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Proof doesn't match the amount" />
              <div className="flex justify-between gap-3">
                <Button variant="ghost" onClick={() => setDeclining(false)}>Back</Button>
                <Button variant="danger" isLoading={isDeclining} onClick={handleDecline}>Decline payment</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
