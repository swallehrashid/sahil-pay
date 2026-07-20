import { useEffect, useRef, useState } from "react";
import { CreditCard, MessageSquarePlus, FileText, Smartphone, Copy } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import {
  useGetBillingQuery,
  usePaySubscriptionStkMutation,
  useBuySmsStkMutation,
  useLazyGetTransactionStatusQuery,
  useGetBillingTransactionsQuery,
  useGenerateTaxInvoiceMutation,
} from "./billingApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { SUBSCRIPTION_PLANS } from "@/utils/constants";

const PLAN_DISCOUNTS = { monthly: "0%", quarterly: "10%", annual: "15%" };
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 120000;

function copyToClipboard(value) {
  if (!value) return;
  navigator.clipboard?.writeText(String(value));
  toast("Copied to clipboard.", { type: "success" });
}

function PaybillCard({ shortcode, accountRef }) {
  if (!shortcode) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm">
      <p className="mb-2 font-medium text-white">Or pay directly via M-Pesa Paybill</p>
      <div className="flex items-center justify-between py-1">
        <span className="text-white/50">Business number</span>
        <button type="button" onClick={() => copyToClipboard(shortcode)} className="flex items-center gap-1 font-mono text-white hover:underline">
          {shortcode} <Copy className="h-3 w-3" />
        </button>
      </div>
      <div className="flex items-center justify-between py-1">
        <span className="text-white/50">Account number</span>
        <button type="button" onClick={() => copyToClipboard(accountRef)} className="flex items-center gap-1 font-mono text-white hover:underline">
          {accountRef} <Copy className="h-3 w-3" />
        </button>
      </div>
      <p className="mt-2 text-xs text-white/40">Activates automatically within about a minute of payment.</p>
    </div>
  );
}

// Waits for a pending BillingTransaction to verify, polling every 3s for up
// to 2 minutes (MPESA_INTEGRATION_SPEC.md §6.1). Terminal states: verified,
// failed, or a timeout that leaves the door open — the reconciliation sweep
// picks up late callbacks even if the user closes this modal.
function useAwaitVerification({ onVerified, onFailed }) {
  const [fetchStatus] = useLazyGetTransactionStatusQuery();
  const [state, setState] = useState("idle"); // idle | waiting | verified | failed | timeout
  const timerRef = useRef(null);
  const deadlineRef = useRef(0);

  const stop = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
  };

  const start = (txnId) => {
    stop();
    setState("waiting");
    deadlineRef.current = Date.now() + POLL_TIMEOUT_MS;

    const tick = async () => {
      try {
        const res = await fetchStatus(txnId).unwrap();
        const txn = res?.transaction;
        if (txn?.is_verified) {
          setState("verified");
          stop();
          onVerified?.(txn);
          return;
        }
        if (txn?.status === "failed") {
          setState("failed");
          stop();
          onFailed?.(txn);
          return;
        }
      } catch {
        // transient — keep polling until the deadline
      }
      if (Date.now() >= deadlineRef.current) {
        setState("timeout");
        stop();
        return;
      }
      timerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
    };

    timerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
  };

  useEffect(() => stop, []);

  return { state, start, stop, reset: () => setState("idle") };
}

// §4.21 — plan, SMS balance, pay subscription / buy SMS, transactions + tax invoices.
export default function BillingSettings() {
  const { data, isLoading } = useGetBillingQuery();
  const { data: transactionsData, isLoading: isTransactionsLoading } = useGetBillingTransactionsQuery();
  const [paySubscriptionStk, { isLoading: isPaying }] = usePaySubscriptionStkMutation();
  const [buySmsStk, { isLoading: isBuying }] = useBuySmsStkMutation();
  const [generateTaxInvoice] = useGenerateTaxInvoiceMutation();

  const [isPayOpen, setIsPayOpen] = useState(false);
  const [isSmsOpen, setIsSmsOpen] = useState(false);
  const [plan, setPlan] = useState("monthly");
  const [phone, setPhone] = useState("");
  const [smsCount, setSmsCount] = useState("100");
  const [smsPhone, setSmsPhone] = useState("");

  const subPoll = useAwaitVerification({
    onVerified: () => {
      toast("Subscription payment confirmed.", { type: "success" });
      setIsPayOpen(false);
    },
    onFailed: () => toast("The M-Pesa payment failed or was cancelled.", { type: "error" }),
  });
  const smsPoll = useAwaitVerification({
    onVerified: () => {
      toast("SMS credits added.", { type: "success" });
      setIsSmsOpen(false);
    },
    onFailed: () => toast("The M-Pesa payment failed or was cancelled.", { type: "error" }),
  });

  // Backend returns { transactions: [...] }, not one of toRows()'s recognized keys.
  const transactions = transactionsData?.transactions ?? [];

  const handlePay = async (e) => {
    e.preventDefault();
    subPoll.reset();
    try {
      const res = await paySubscriptionStk({ billing_cycle: plan, phone: phone.trim() || undefined }).unwrap();
      if (res?.simulated) {
        toast("Subscription payment verified.", { type: "success" });
        setIsPayOpen(false);
        return;
      }
      toast("STK prompt sent — check your phone.", { type: "success" });
      subPoll.start(res.transaction.id);
    } catch (err) {
      toast(err?.data?.error || "Could not process the payment.", { type: "error" });
    }
  };

  const handleBuySms = async (e) => {
    e.preventDefault();
    if (Number(smsCount) < 100) {
      toast("Minimum SMS purchase is 100.", { type: "error" });
      return;
    }
    smsPoll.reset();
    try {
      const res = await buySmsStk({ sms_count: Number(smsCount), phone: smsPhone.trim() || undefined }).unwrap();
      if (res?.simulated) {
        toast("SMS credits added.", { type: "success" });
        setIsSmsOpen(false);
        return;
      }
      toast("STK prompt sent — check your phone.", { type: "success" });
      smsPoll.start(res.transaction.id);
    } catch (err) {
      toast(err?.data?.error || "Could not process the SMS purchase.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.created_at) },
    { key: "type", header: "Type" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    {
      key: "status",
      header: "Status",
      render: (row) => (
        <div className="flex items-center gap-2">
          <StatusBadge status={row.status} />
          {row.is_verified ? (
            <span className="text-xs text-emerald-400">Verified</span>
          ) : row.status === "pending" ? (
            <span className="text-xs text-white/40">Awaiting verification</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "invoice",
      header: "Receipt",
      render: (row) =>
        row.is_verified && (
          <button
            onClick={() =>
              generateTaxInvoice({ transaction_id: row.id }).then((res) =>
                downloadFile(res?.data?.tax_invoice_url ?? row.tax_invoice_url, { filename: `sahilpay-receipt-${row.id}.pdf` })
              )
            }
            className="flex items-center gap-1 text-xs text-secondary hover:underline"
          >
            <FileText className="h-3.5 w-3.5" /> Download receipt
          </button>
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="Billing"
        subtitle="Your subscription plan and SMS balance"
        actions={
          <>
            <Button variant="ghost" leftIcon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => { smsPoll.reset(); setIsSmsOpen(true); }}>
              Buy SMS
            </Button>
            <Button leftIcon={<CreditCard className="h-4 w-4" />} onClick={() => { subPoll.reset(); setIsPayOpen(true); }}>
              Pay subscription
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {/* #15 — show the actual plan/package name, plus the billing cadence / trial state. */}
          <SummaryCard
            label="Plan"
            value={data?.package?.name ?? "—"}
            trend={{ label: data?.is_on_trial ? "On trial" : (data?.subscription?.billing_cycle ?? data?.subscription?.plan ?? "Active"), positive: true }}
            icon={<CreditCard className="h-5 w-5" />}
          />
          <SummaryCard label="Amount due" value={formatCurrency(data?.subscription?.amount_due)} icon={<CreditCard className="h-5 w-5" />} accent="third" />
          <SummaryCard
            label="Next billing date"
            value={data?.subscription?.next_billing_date ? formatDate(data.subscription.next_billing_date) : "—"}
            trend={data?.is_on_trial && data?.trial_ends_at ? { label: `Trial ends ${formatDate(data.trial_ends_at)}`, positive: true } : undefined}
            icon={<CreditCard className="h-5 w-5" />}
          />
          <SummaryCard label="SMS balance" value={data?.sms_balance ?? 0} icon={<MessageSquarePlus className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6">
        <h3 className="mb-3 text-base font-medium text-white">Transactions</h3>
        <ResponsiveTable columns={columns} rows={transactions} isLoading={isTransactionsLoading} />
      </div>

      <Modal isOpen={isPayOpen} onClose={() => { subPoll.stop(); setIsPayOpen(false); }} title="Pay subscription">
        {subPoll.state === "waiting" ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <Smartphone className="h-10 w-10 animate-pulse text-secondary" />
            <p className="text-white">Check your phone for the M-Pesa prompt</p>
            <p className="text-sm text-white/50">This confirms automatically once you enter your PIN.</p>
          </div>
        ) : subPoll.state === "timeout" ? (
          <div className="space-y-4 py-2 text-center">
            <p className="text-white/70">
              We haven't seen your payment yet — if you completed it, it will reflect automatically; otherwise try again.
            </p>
            <Button variant="ghost" onClick={() => subPoll.reset()}>Try again</Button>
          </div>
        ) : (
          <form onSubmit={handlePay} className="space-y-4">
            <Select
              label="Billing cycle"
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
              options={SUBSCRIPTION_PLANS.map((p) => ({ value: p, label: `${p} (${PLAN_DISCOUNTS[p]} off)` }))}
              required
            />
            <Input
              label="M-Pesa phone number"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="07XXXXXXXX"
              hint="We'll send the payment prompt to this number"
            />
            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="ghost" onClick={() => setIsPayOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" isLoading={isPaying}>
                Pay now
              </Button>
            </div>
            <PaybillCard shortcode={data?.paybill?.shortcode} accountRef={data?.paybill?.subscription_account_ref} />
          </form>
        )}
      </Modal>

      <Modal isOpen={isSmsOpen} onClose={() => { smsPoll.stop(); setIsSmsOpen(false); }} title="Buy SMS">
        {smsPoll.state === "waiting" ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <Smartphone className="h-10 w-10 animate-pulse text-secondary" />
            <p className="text-white">Check your phone for the M-Pesa prompt</p>
            <p className="text-sm text-white/50">This confirms automatically once you enter your PIN.</p>
          </div>
        ) : smsPoll.state === "timeout" ? (
          <div className="space-y-4 py-2 text-center">
            <p className="text-white/70">
              We haven't seen your payment yet — if you completed it, it will reflect automatically; otherwise try again.
            </p>
            <Button variant="ghost" onClick={() => smsPoll.reset()}>Try again</Button>
          </div>
        ) : (
          <form onSubmit={handleBuySms} className="space-y-4">
            <Input label="Number of SMS" type="number" min="100" value={smsCount} onChange={(e) => setSmsCount(e.target.value)} hint="Minimum 100" required />
            {data?.sms_unit_price != null && (
              <div className="flex items-center justify-between rounded-xl bg-white/5 px-4 py-3 text-sm">
                <span className="text-white/50">
                  {formatCurrency(data.sms_unit_price)} / SMS
                  {data.sms_uses_own_sender ? " · your sender ID" : " · Sahil Pay sender ID"}
                </span>
                <span className="font-medium text-white">{formatCurrency((Number(smsCount) || 0) * data.sms_unit_price)}</span>
              </div>
            )}
            <Input
              label="M-Pesa phone number"
              value={smsPhone}
              onChange={(e) => setSmsPhone(e.target.value)}
              placeholder="07XXXXXXXX"
              hint="We'll send the payment prompt to this number"
            />
            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="ghost" onClick={() => setIsSmsOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" isLoading={isBuying}>
                Buy now
              </Button>
            </div>
            <PaybillCard shortcode={data?.paybill?.shortcode} accountRef={data?.paybill?.sms_account_ref} />
          </form>
        )}
      </Modal>
    </div>
  );
}
