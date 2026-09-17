import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import {
  CreditCard, MessageSquarePlus, FileText, Smartphone, Copy, Lock, Unlock, ShieldCheck,
  CheckCircle2, XCircle, Clock, Loader2, Receipt, Hash, CalendarClock,
} from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import {
  useGetBillingQuery,
  usePayStkMutation,
  useConfirmPaybillPaymentMutation,
  useSimulateConfirmationMutation,
  useLazyGetTransactionStatusQuery,
  useGetBillingTransactionsQuery,
} from "./billingApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";

// Billing — subscription and SMS, paid in whatever amounts suit the landlord.
//
// HOW MONEY IS COUNTED
//   The subscription is a running balance. Each billing date adds that period's
//   price; every CONFIRMED payment, of any size, comes off it. Pay 6,000 of
//   10,000 and 4,000 carries into next month's charge.
//
// WHEN IS IT PAID?
//   Only when M-Pesa confirms the money reached the Sahil Pay paybill. A prompt
//   that was sent is "Waiting for M-Pesa" — never "Paid" — until then.
//
// LOCK
//   A balance older than the grace period locks the portal (this page stays
//   open). It opens the moment the balance is cleared, or when Sahil Pay grants
//   an exemption.

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 120000;

const receiptPath = (id) => `/billing/transactions/${id}/receipt`;
const downloadReceipt = (txn) =>
  downloadFile(receiptPath(txn.id), { filename: `sahilpay-receipt-SP-RCPT-${String(txn.id).padStart(6, "0")}.pdf` })
    .then(() => toast("Receipt downloaded.", { type: "success" }))
    .catch((e) => toast(e.message || "Could not download the receipt.", { type: "error" }));

function copyToClipboard(value) {
  if (!value) return;
  navigator.clipboard?.writeText(String(value));
  toast("Copied.", { type: "success" });
}

function txnState(t) {
  if (t.is_verified && t.status === "paid") return { key: "paid", label: "Confirmed", icon: CheckCircle2, cls: "text-emerald-300" };
  if (t.status === "failed") return { key: "failed", label: "Failed / cancelled", icon: XCircle, cls: "text-red-300" };
  if (t.context_json?.mode === "claim") return { key: "review", label: "Under review", icon: Clock, cls: "text-amber-300" };
  return { key: "pending", label: "Waiting for M-Pesa", icon: Clock, cls: "text-amber-300" };
}

export default function BillingSettings() {
  const { data, isLoading } = useGetBillingQuery();
  const { data: transactionsData, isLoading: isTransactionsLoading } = useGetBillingTransactionsQuery();
  const [payOpen, setPayOpen] = useState(null); // "subscription" | "sms" | null

  const access = data?.access;
  const transactions = transactionsData?.transactions ?? [];

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.created_at) },
    {
      key: "type", header: "For",
      render: (row) => (row.type === "sms_purchase" ? `SMS credits${row.sms_count ? ` (${row.sms_count})` : ""}` : "Subscription"),
    },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "ref", header: "M-Pesa ref", render: (row) => <span className="font-mono text-xs">{row.is_verified ? row.payment_reference : "—"}</span> },
    {
      key: "status", header: "Status",
      render: (row) => {
        const s = txnState(row);
        return <span className={clsx("inline-flex items-center gap-1.5 text-sm", s.cls)}><s.icon className="h-4 w-4" />{s.label}</span>;
      },
    },
    {
      key: "receipt", header: "Receipt",
      render: (row) =>
        txnState(row).key === "paid" ? (
          <button onClick={() => downloadReceipt(row)} className="inline-flex items-center gap-1.5 text-sm text-secondary-200 hover:underline"
                  data-testid={`receipt-${row.id}`}>
            <FileText className="h-4 w-4" /> Download
          </button>
        ) : <span className="text-xs text-white/35">After confirmation</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Billing"
        subtitle="Your Sahil Pay subscription, SMS credits and receipts"
        actions={
          <>
            <Button variant="ghost" leftIcon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => setPayOpen("sms")}>
              Buy SMS
            </Button>
            <Button leftIcon={<CreditCard className="h-4 w-4" />} onClick={() => setPayOpen("subscription")} data-testid="pay-subscription">
              Pay subscription
            </Button>
          </>
        }
      />

      {isLoading ? <SkeletonStatCards count={4} /> : (
        <>
          <AccountCard access={access} onPay={() => setPayOpen("subscription")} />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard label="Plan" value={data?.package?.name ?? "—"}
                         trend={{ label: data?.is_on_trial ? "On trial" : (data?.subscription?.billing_cycle ?? "monthly"), positive: true }}
                         icon={<CreditCard className="h-5 w-5" />} />
            <SummaryCard label="Price per month" value={formatCurrency(data?.subscription?.subscription_cost)} icon={<Receipt className="h-5 w-5" />} accent="third" />
            <SummaryCard label="Next billing date" value={access?.next_billing_date ? formatDate(access.next_billing_date) : "—"}
                         trend={data?.is_on_trial && data?.trial_ends_at ? { label: `Trial ends ${formatDate(data.trial_ends_at)}`, positive: true } : undefined}
                         icon={<CalendarClock className="h-5 w-5" />} />
            <SummaryCard label="SMS balance" value={data?.sms_balance ?? 0} icon={<MessageSquarePlus className="h-5 w-5" />} accent="third" />
          </div>
          <PaybillPanel data={data} />
        </>
      )}

      <div>
        <h3 className="mb-3 text-base font-medium text-white">Payments</h3>
        <ResponsiveTable columns={columns} rows={transactions} isLoading={isTransactionsLoading}
                         emptyState={<p className="glass p-6 text-sm text-white/50">No payments yet.</p>} />
      </div>

      {payOpen && <PayModal purpose={payOpen} data={data} onClose={() => setPayOpen(null)} />}
    </div>
  );
}

function AccountCard({ access, onPay }) {
  if (!access) return null;
  const balance = access.balance ?? 0;
  const tone = access.locked ? "locked" : access.override_until ? "exempt" : balance > 0 ? "owing" : "clear";
  const styles = {
    locked: "border-red-400/60 bg-red-500/10",
    exempt: "border-amber-400/50 bg-amber-500/10",
    owing: "border-amber-400/40",
    clear: "border-emerald-400/40",
  };
  const Icon = access.locked ? Lock : access.override_until ? ShieldCheck : Unlock;
  return (
    <section className={clsx("glass flex flex-col gap-5 border-l-4 p-5 sm:p-6 lg:flex-row lg:items-center lg:justify-between", styles[tone])}
             data-testid="account-card" aria-live="polite">
      <div className="flex items-start gap-4">
        <span className={clsx("rounded-2xl p-3", access.locked ? "bg-red-500/25 text-red-100" : "bg-white/10 text-white")}>
          <Icon className="h-6 w-6" />
        </span>
        <div>
          <p className="text-sm text-white/60">
            {access.locked ? "Account locked — unpaid balance"
              : access.override_until ? `Open by arrangement until ${formatDate(access.override_until)}`
              : access.on_trial ? "Free trial" : balance > 0 ? "Balance to pay" : "All paid up"}
          </p>
          <p className="mt-1 text-3xl font-light text-white">
            {balance < 0 ? `${formatCurrency(-balance)} credit` : formatCurrency(balance)}
          </p>
          <p className="mt-1 text-sm text-white/55">
            {access.locked && "Pay any amount now — your account opens as soon as the balance is cleared."}
            {!access.locked && balance > 0 && access.grace_until && `Please clear by ${formatDate(access.grace_until)} to keep your account open.`}
            {!access.locked && balance <= 0 && access.next_billing_date && `Next charge on ${formatDate(access.next_billing_date)}.`}
          </p>
        </div>
      </div>
      <Button onClick={onPay} className="w-full lg:w-auto" leftIcon={<Smartphone className="h-4 w-4" />}>
        {balance > 0 ? "Pay now" : "Pay ahead"}
      </Button>
    </section>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-4 py-3">
      <span className="text-sm text-white/55">{label}</span>
      <button type="button" onClick={() => copyToClipboard(value)} className="flex items-center gap-2 font-mono text-base text-white hover:underline">
        {value} <Copy className="h-3.5 w-3.5 text-white/50" />
      </button>
    </div>
  );
}

function PaybillPanel({ data }) {
  const [code, setCode] = useState("");
  const [purpose, setPurpose] = useState("subscription");
  const [confirm, { isLoading }] = useConfirmPaybillPaymentMutation();
  if (!data?.paybill?.shortcode) return null;

  const submit = async (e) => {
    e.preventDefault();
    try {
      const res = await confirm({ mpesa_code: code, purpose }).unwrap();
      toast(res.message, { type: "success" });
      setCode("");
    } catch (err) {
      const msg = err?.data?.message || err?.data?.error;
      toast(msg || "Could not check that code.", { type: err?.status === 202 ? "info" : "error" });
    }
  };

  return (
    <section className="glass grid gap-6 p-5 sm:p-6 lg:grid-cols-2" aria-labelledby="paybill-heading">
      <div className="space-y-3">
        <h3 id="paybill-heading" className="text-base font-medium text-white">Or pay through M-Pesa Paybill</h3>
        <p className="text-sm text-white/55">Lipa na M-Pesa → Pay Bill. Pay any amount; it applies automatically within a minute.</p>
        <Row label="Business number" value={data.paybill.shortcode} />
        <Row label="Account (subscription)" value={data.paybill.subscription_account_ref} />
        <Row label="Account (SMS credits)" value={data.paybill.sms_account_ref} />
      </div>
      <form onSubmit={submit} className="space-y-3 lg:border-l lg:border-white/10 lg:pl-6">
        <h3 className="text-base font-medium text-white">Already paid? Confirm it</h3>
        <p className="text-sm text-white/55">
          Enter the code from your M-Pesa SMS. It is confirmed only once the money shows in the Sahil Pay paybill —
          until then it stays pending for our team to check.
        </p>
        <Input label="M-Pesa code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())}
               placeholder="e.g. SJK4ABC123" leftIcon={<Hash className="h-4 w-4" />} maxLength={12} />
        <div className="flex gap-2" role="radiogroup" aria-label="Payment was for">
          {[["subscription", "Subscription"], ["sms", "SMS credits"]].map(([k, l]) => (
            <button key={k} type="button" role="radio" aria-checked={purpose === k} onClick={() => setPurpose(k)}
                    className={clsx("rounded-full border px-3 py-1.5 text-sm", purpose === k ? "border-secondary bg-secondary/20 text-white" : "border-white/15 text-white/60")}>
              {l}
            </button>
          ))}
        </div>
        <Button type="submit" variant="ghost" isLoading={isLoading} disabled={code.trim().length < 8}>Check payment</Button>
      </form>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pay modal: choose → prompt → wait for M-Pesa → confirmed (receipt)
// ---------------------------------------------------------------------------

function PayModal({ purpose: initialPurpose, data, onClose }) {
  const [purpose, setPurpose] = useState(initialPurpose);
  const options = data?.pay_options ?? [];
  const defaultOption = options[0];
  const [choice, setChoice] = useState(defaultOption?.key ?? "custom");
  const [amount, setAmount] = useState(defaultOption ? String(Math.ceil(defaultOption.amount)) : "");
  const [phone, setPhone] = useState("");
  const [stage, setStage] = useState("form"); // form | waiting | confirmed | failed | timeout
  const [txn, setTxn] = useState(null);

  const [payStk, { isLoading }] = usePayStkMutation();
  const [simulate, { isLoading: simulating }] = useSimulateConfirmationMutation();
  const [fetchStatus] = useLazyGetTransactionStatusQuery();
  const timer = useRef(null);
  const deadline = useRef(0);
  useEffect(() => () => clearTimeout(timer.current), []);

  const balance = data?.access?.balance ?? 0;
  const unitPrice = data?.sms_unit_price ?? 0;
  const numeric = Number(amount) || 0;
  const selectedOption = options.find((o) => o.key === choice);
  const cycle = selectedOption?.cycle;
  const smsCredits = unitPrice ? Math.floor(numeric / unitPrice) : 0;
  const smsMin = data?.sms_min_purchase ?? 100;

  const after = purpose === "subscription"
    ? (cycle ? balance + (selectedOption.amount - Math.max(balance, 0)) - numeric : balance - numeric)
    : null;

  const poll = (id) => {
    const tick = async () => {
      try {
        const res = await fetchStatus(id).unwrap();
        const t = res?.transaction;
        setTxn(t);
        if (t?.is_verified) { setStage("confirmed"); return; }
        if (t?.status === "failed") { setStage("failed"); return; }
      } catch { /* keep polling */ }
      if (Date.now() >= deadline.current) { setStage("timeout"); return; }
      timer.current = setTimeout(tick, POLL_INTERVAL_MS);
    };
    deadline.current = Date.now() + POLL_TIMEOUT_MS;
    timer.current = setTimeout(tick, POLL_INTERVAL_MS);
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const res = await payStk({ purpose, amount: numeric, phone: phone.trim() || undefined, cycle: purpose === "subscription" ? cycle : undefined }).unwrap();
      setTxn(res.transaction);
      setStage("waiting");
      poll(res.transaction.id);
    } catch (err) {
      toast(err?.data?.error || err?.data?.message || "Could not start the payment.", { type: "error" });
    }
  };

  const title = purpose === "sms" ? "Buy SMS credits" : "Pay subscription";

  return (
    <Modal isOpen onClose={() => { clearTimeout(timer.current); onClose(); }} title={title} size="lg">
      {stage === "form" && (
        <form onSubmit={submit} className="space-y-5">
          <div className="grid grid-cols-2 gap-2" role="tablist">
            {[["subscription", "Subscription"], ["sms", "SMS credits"]].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={purpose === k}
                      onClick={() => { setPurpose(k); setAmount(k === "sms" ? String(Math.ceil(unitPrice * smsMin)) : defaultOption ? String(Math.ceil(defaultOption.amount)) : ""); }}
                      className={clsx("rounded-xl border px-4 py-2.5 text-sm font-medium", purpose === k ? "border-secondary bg-secondary/20 text-white" : "border-white/15 text-white/60")}>
                {l}
              </button>
            ))}
          </div>

          {purpose === "subscription" ? (
            <div className="space-y-2">
              <p className="text-sm text-white/70">How much would you like to pay?</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {options.map((o) => (
                  <button key={o.key} type="button" onClick={() => { setChoice(o.key); setAmount(String(Math.ceil(o.amount))); }}
                          className={clsx("rounded-xl border p-3 text-left", choice === o.key ? "border-secondary bg-secondary/15" : "border-white/15 bg-white/5 hover:border-white/30")}>
                    <span className="block text-xs text-white/55">{o.label}</span>
                    <span className="block text-lg text-white">{formatCurrency(o.amount)}</span>
                  </button>
                ))}
                <button type="button" onClick={() => setChoice("custom")}
                        className={clsx("rounded-xl border p-3 text-left", choice === "custom" ? "border-secondary bg-secondary/15" : "border-white/15 bg-white/5 hover:border-white/30")}>
                  <span className="block text-xs text-white/55">Another amount</span>
                  <span className="block text-lg text-white">Part payment</span>
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-white/60">
              {formatCurrency(unitPrice)} per SMS · minimum {smsMin} messages ({formatCurrency(Math.ceil(unitPrice * smsMin))}).
            </p>
          )}

          <Input label="Amount (KES)" type="number" inputMode="numeric" min="1" step="1" value={amount}
                 onChange={(e) => { setAmount(e.target.value); if (purpose === "subscription" && choice !== "custom") setChoice("custom"); }}
                 hint={purpose === "subscription" ? "Pay any amount — it comes off your balance." : `Buys ${smsCredits.toLocaleString()} SMS`}
                 required data-testid="pay-amount" />
          <Input label="M-Pesa phone number" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="07XXXXXXXX"
                 inputMode="tel" hint="The prompt goes to this phone. Leave blank to use your account's M-Pesa number." />

          {purpose === "subscription" && numeric > 0 && (
            <div className={clsx("rounded-xl px-4 py-3 text-sm", after > 0 ? "bg-amber-500/10 text-amber-100" : "bg-emerald-500/10 text-emerald-100")}>
              {after > 0
                ? <>After this payment you will still owe <strong>{formatCurrency(after)}</strong>. {data?.access?.locked && "Your account opens once the balance is fully cleared."}</>
                : <>This clears your balance{after < 0 ? <> and leaves <strong>{formatCurrency(-after)}</strong> credit</> : null}. {data?.access?.locked && "Your account opens as soon as M-Pesa confirms."}</>}
            </div>
          )}

          <div className="flex flex-col-reverse gap-2 border-t border-white/10 pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" isLoading={isLoading} leftIcon={<Smartphone className="h-4 w-4" />}
                    disabled={numeric < 1 || (purpose === "sms" && smsCredits < smsMin)} data-testid="send-prompt">
              Send M-Pesa prompt · {formatCurrency(numeric)}
            </Button>
          </div>
        </form>
      )}

      {stage === "waiting" && txn && (
        <div className="space-y-5 py-2 text-center" data-testid="payment-waiting">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-secondary/20">
            <Smartphone className="h-8 w-8 animate-pulse text-secondary" />
          </div>
          <div>
            <p className="text-lg text-white">Check your phone and enter your M-Pesa PIN</p>
            <p className="mt-1 text-sm text-white/55">{formatCurrency(txn.amount)} to Sahil Pay · Paybill {data?.paybill?.shortcode}</p>
          </div>
          <ol className="mx-auto max-w-sm space-y-2 text-left text-sm">
            <li className="flex items-center gap-2 text-emerald-300"><CheckCircle2 className="h-4 w-4" /> Prompt sent</li>
            <li className="flex items-center gap-2 text-amber-200"><Loader2 className="h-4 w-4 animate-spin" /> Waiting for M-Pesa to confirm the money arrived</li>
            <li className="flex items-center gap-2 text-white/40"><Receipt className="h-4 w-4" /> Receipt</li>
          </ol>
          <p className="text-xs text-white/40">Nothing is marked paid until M-Pesa confirms it.</p>
          {data?.simulation_mode && (
            <div className="rounded-xl border border-dashed border-amber-400/40 p-3 text-left">
              <p className="text-xs text-amber-200">Test mode — no real prompt was sent. Play M-Pesa's reply:</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" isLoading={simulating} data-testid="simulate-success"
                        onClick={() => simulate({ id: txn.id }).unwrap().catch(() => toast("Simulation failed.", { type: "error" }))}>
                  Simulate: customer paid
                </Button>
                <Button size="sm" variant="ghost" onClick={() => simulate({ id: txn.id, result: "cancelled" })}>
                  Simulate: cancelled
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {stage === "confirmed" && txn && (
        <div className="space-y-5 py-2 text-center" data-testid="payment-confirmed">
          <div className="mx-auto flex h-16 w-16 animate-scale-in items-center justify-center rounded-full bg-emerald-500/20">
            <CheckCircle2 className="h-9 w-9 text-emerald-300" />
          </div>
          <div>
            <p className="text-lg text-white">Payment confirmed</p>
            <p className="mt-1 text-sm text-white/60">
              {formatCurrency(txn.amount)} received · M-Pesa {txn.payment_reference}
            </p>
            {txn.context_json?.balance_after != null && (
              <p className="mt-1 text-sm text-white/60">
                {Number(txn.context_json.balance_after) > 0
                  ? `Balance remaining: ${formatCurrency(txn.context_json.balance_after)}`
                  : "Your balance is cleared."}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <Button leftIcon={<FileText className="h-4 w-4" />} onClick={() => downloadReceipt(txn)} data-testid="modal-receipt">Download receipt</Button>
            <Button variant="ghost" onClick={onClose}>Done</Button>
          </div>
        </div>
      )}

      {stage === "failed" && (
        <div className="space-y-4 py-2 text-center">
          <XCircle className="mx-auto h-12 w-12 text-red-300" />
          <p className="text-white">The M-Pesa payment was cancelled or failed. Nothing was charged.</p>
          <Button variant="ghost" onClick={() => setStage("form")}>Try again</Button>
        </div>
      )}

      {stage === "timeout" && (
        <div className="space-y-4 py-2 text-center">
          <Clock className="mx-auto h-12 w-12 text-amber-300" />
          <p className="text-white">Still waiting for M-Pesa.</p>
          <p className="text-sm text-white/60">
            If you entered your PIN, the payment will confirm here automatically as soon as M-Pesa reports it —
            it stays as “Waiting for M-Pesa” in your payments until then.
          </p>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      )}
    </Modal>
  );
}
