import { useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { TENANT_ROUTES } from "@/config/routePaths";
import { ArrowRight, ArrowLeft, Wallet, Clock, CheckCircle2, XCircle, ReceiptText, Building2 } from "lucide-react";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import FileUpload from "@/components/ui/FileUpload";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import {
  useGetPaymentDetailsQuery,
  useGetPortalPaymentsQuery,
  useSubmitPortalPaymentMutation,
} from "./tenantPortalApiSlice";
import TenantReceiptModal from "./TenantReceiptModal";

// §6.4 — tenants can only SUBMIT a payment for the landlord to confirm; they
// cannot record a confirmed payment themselves. Flow: choose amount → see the
// landlord's pay directives → attach proof → submit. Confirmed payments (and
// their receipts) only appear once the landlord confirms.
export default function TenantPayments() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const startStep = searchParams.get("start") === "1" ? "amount" : "history";

  const { data: details, isLoading: detailsLoading } = useGetPaymentDetailsQuery();
  const { data: history, isLoading: historyLoading } = useGetPortalPaymentsQuery();
  const [submitPayment, { isLoading: isSubmitting }] = useSubmitPortalPaymentMutation();

  const [step, setStep] = useState(startStep); // history | amount | howto
  const [amount, setAmount] = useState("");
  const [mpesaRef, setMpesaRef] = useState("");
  const [note, setNote] = useState("");
  const [proof, setProof] = useState(null);
  const [receiptId, setReceiptId] = useState(null);

  const totalDue = details?.total_due ?? 0;

  const goToAmount = () => {
    setAmount(totalDue ? String(totalDue) : "");
    setStep("amount");
  };

  const handleContinue = (e) => {
    e.preventDefault();
    if (!(Number(amount) > 0)) {
      toast("Enter a valid amount to pay.", { type: "error" });
      return;
    }
    setStep("howto");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const form = new FormData();
    form.append("amount", amount);
    form.append("payment_method", "mpesa");
    if (mpesaRef) form.append("mpesa_reference", mpesaRef);
    if (note) form.append("note", note);
    if (proof) form.append("proof", proof);
    try {
      await submitPayment(form).unwrap();
      toast("Payment submitted! Your landlord will confirm it shortly.", { type: "success" });
      setAmount(""); setMpesaRef(""); setNote(""); setProof(null);
      // Land on the payments page (history view), clearing any ?start=1 deep-link
      // so a refresh doesn't reopen the form. The just-submitted payment shows
      // under "Awaiting confirmation" (the history query is invalidated on submit).
      navigate(TENANT_ROUTES.pay, { replace: true });
      setStep("history");
    } catch (err) {
      toast(err?.data?.error || "Could not submit your payment.", { type: "error" });
    }
  };

  const mpesaLabel = details?.mpesa_type === "till" ? "Buy Goods (Till)" : "Paybill";

  // ---- STEP: choose amount ----------------------------------------------------
  if (step === "amount") {
    return (
      <div className="animate-fade-in-up mx-auto max-w-2xl space-y-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep("history")}>Back</Button>
          <h1 className="text-2xl font-light tracking-wide text-white">Make a payment</h1>
        </div>

        <div className="glass rounded-2xl p-5">
          <h3 className="mb-3 text-sm font-medium text-white/70">What you owe</h3>
          {detailsLoading ? (
            <div className="flex justify-center py-6"><Spinner /></div>
          ) : (details?.outstanding_invoices?.length ?? 0) === 0 ? (
            <p className="text-sm text-white/50">You have no outstanding charges. You can still pay in advance.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-white/40">
                  <th className="py-1 font-medium">Charge</th>
                  <th className="py-1 font-medium">Due date</th>
                  <th className="py-1 text-right font-medium">Balance</th>
                </tr>
              </thead>
              <tbody>
                {details.outstanding_invoices.map((inv) => (
                  <tr key={inv.id} className="border-t border-white/5 text-white/80">
                    <td className="py-1.5 capitalize">{inv.title}</td>
                    <td className="py-1.5">{inv.due_date ? formatDate(inv.due_date) : "—"}</td>
                    <td className="py-1.5 text-right">{formatCurrency(inv.balance)}</td>
                  </tr>
                ))}
                <tr className="border-t border-white/10 font-semibold text-white">
                  <td className="py-2" colSpan={2}>Total due</td>
                  <td className="py-2 text-right">{formatCurrency(totalDue)}</td>
                </tr>
              </tbody>
            </table>
          )}
        </div>

        <form onSubmit={handleContinue} className="glass space-y-4 rounded-2xl p-5">
          <Input
            label="Amount to pay (KES)"
            type="number"
            min="1"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            hint={totalDue ? `Total due is ${formatCurrency(totalDue)} — you can pay part or all.` : "You can pay any amount in advance."}
            required
          />
          <div className="flex justify-end">
            <Button type="submit" rightIcon={<ArrowRight className="h-4 w-4" />}>Continue</Button>
          </div>
        </form>
      </div>
    );
  }

  // ---- STEP: how to pay + proof ----------------------------------------------
  if (step === "howto") {
    return (
      <div className="animate-fade-in-up mx-auto max-w-2xl space-y-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />} onClick={() => setStep("amount")}>Back</Button>
          <h1 className="text-2xl font-light tracking-wide text-white">How to pay</h1>
        </div>

        <div className="glass rounded-2xl p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white/70">
            <Building2 className="h-4 w-4" /> Pay {formatCurrency(amount)} to your landlord
          </div>
          <dl className="space-y-2 text-sm">
            {details?.mpesa_number && (
              <div className="flex justify-between"><dt className="text-white/50">{mpesaLabel} number</dt><dd className="font-medium text-white">{details.mpesa_number}</dd></div>
            )}
            {details?.account_number && (
              <div className="flex justify-between"><dt className="text-white/50">Account number</dt><dd className="font-medium text-white">{details.account_number}</dd></div>
            )}
            {details?.expected_name && (
              <div className="flex justify-between"><dt className="text-white/50">Expected name</dt><dd className="font-medium text-white">{details.expected_name}</dd></div>
            )}
            <div className="flex justify-between"><dt className="text-white/50">Amount</dt><dd className="font-semibold text-secondary">{formatCurrency(amount)}</dd></div>
          </dl>
          {details?.payment_instructions && (
            <div className="mt-4 rounded-xl bg-white/5 p-3 text-sm text-white/70">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-white/40">Instructions from your landlord</p>
              <p className="whitespace-pre-wrap">{details.payment_instructions}</p>
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="glass space-y-4 rounded-2xl p-5">
          <p className="text-sm text-white/60">
            After paying, submit the details below. Your landlord will verify and confirm it — it will
            then appear in your history with a downloadable receipt.
          </p>
          <Input label="M-Pesa / transaction code" value={mpesaRef} onChange={(e) => setMpesaRef(e.target.value)} placeholder="e.g. QGH7XY12ZZ" hint="The code from your payment confirmation SMS" />
          <FileUpload label="Proof of payment" accept="image/*,application/pdf" value={proof} onChange={setProof} hint="Screenshot or PDF of your M-Pesa / bank confirmation" />
          <Textarea label="Note to landlord" value={note} onChange={(e) => setNote(e.target.value)} hint="Optional" />
          <div className="flex justify-end gap-3">
            <Button type="button" variant="ghost" onClick={() => setStep("amount")}>Back</Button>
            <Button type="submit" isLoading={isSubmitting}>Submit for confirmation</Button>
          </div>
        </form>
      </div>
    );
  }

  // ---- STEP: history (default) -----------------------------------------------
  const pending = history?.pending ?? [];
  const confirmed = history?.confirmed ?? [];
  const declined = history?.declined ?? [];

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-light tracking-wide text-white">Payments</h1>
        <Button leftIcon={<Wallet className="h-4 w-4" />} onClick={goToAmount}>Make a payment</Button>
      </div>

      {historyLoading ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <>
          {pending.length > 0 && (
            <div className="glass rounded-2xl p-5">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-amber-300/90"><Clock className="h-4 w-4" /> Awaiting confirmation</h3>
              <div className="space-y-2">
                {pending.map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3 text-sm">
                    <div>
                      <p className="font-medium text-white">{formatCurrency(p.amount)}</p>
                      <p className="text-xs text-white/50">Submitted {formatDate(p.submitted_at || p.payment_date)}{p.mpesa_reference ? ` · ${p.mpesa_reference}` : ""}</p>
                    </div>
                    <StatusBadge status="pending" />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="glass rounded-2xl p-5">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-white/70"><CheckCircle2 className="h-4 w-4 text-secondary" /> Confirmed payments</h3>
            {confirmed.length === 0 ? (
              <p className="text-sm text-white/50">No confirmed payments yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-white/40">
                    <th className="py-1 font-medium">Date</th>
                    <th className="py-1 font-medium">Amount</th>
                    <th className="py-1 font-medium">Reference</th>
                    <th className="py-1 text-right font-medium">Receipt</th>
                  </tr>
                </thead>
                <tbody>
                  {confirmed.map((p) => (
                    <tr key={p.id} className="border-t border-white/5 text-white/80">
                      <td className="py-2">{formatDate(p.payment_date)}</td>
                      <td className="py-2">{formatCurrency(p.amount)}</td>
                      <td className="py-2 text-white/50">{p.mpesa_reference || p.payment_ref}</td>
                      <td className="py-2 text-right">
                        <Button size="sm" variant="ghost" leftIcon={<ReceiptText className="h-3.5 w-3.5" />} onClick={() => setReceiptId(p.id)}>
                          View receipt
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {declined.length > 0 && (
            <div className="glass rounded-2xl p-5">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-white/50"><XCircle className="h-4 w-4" /> Not confirmed</h3>
              <div className="space-y-2">
                {declined.map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3 text-sm">
                    <div>
                      <p className="text-white/70">{formatCurrency(p.amount)}</p>
                      <p className="text-xs text-white/40">{formatDate(p.submitted_at || p.payment_date)}</p>
                    </div>
                    <StatusBadge status="declined" />
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <TenantReceiptModal paymentId={receiptId} onClose={() => setReceiptId(null)} />
    </div>
  );
}
