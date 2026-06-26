import { useState } from "react";
import { CreditCard, MessageSquarePlus, FileText } from "lucide-react";
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
  usePaySubscriptionMutation,
  useBuySmsMutation,
  useGetBillingTransactionsQuery,
  useGenerateTaxInvoiceMutation,
} from "./billingApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { SUBSCRIPTION_PLANS } from "@/utils/constants";

const PLAN_DISCOUNTS = { monthly: "0%", quarterly: "10%", annual: "15%" };

// §4.21 — plan, SMS balance, pay subscription / buy SMS, transactions + tax invoices.
export default function BillingSettings() {
  const { data, isLoading } = useGetBillingQuery();
  const { data: transactionsData, isLoading: isTransactionsLoading } = useGetBillingTransactionsQuery();
  const [paySubscription, { isLoading: isPaying }] = usePaySubscriptionMutation();
  const [buySms, { isLoading: isBuying }] = useBuySmsMutation();
  const [generateTaxInvoice] = useGenerateTaxInvoiceMutation();

  const [isPayOpen, setIsPayOpen] = useState(false);
  const [isSmsOpen, setIsSmsOpen] = useState(false);
  const [plan, setPlan] = useState("monthly");
  const [smsCount, setSmsCount] = useState("100");

  const transactions = toRows(transactionsData);

  const handlePay = async (e) => {
    e.preventDefault();
    try {
      await paySubscription({ plan }).unwrap();
      toast("Subscription payment initiated.", { type: "success" });
      setIsPayOpen(false);
    } catch {
      toast("Could not process the payment.", { type: "error" });
    }
  };

  const handleBuySms = async (e) => {
    e.preventDefault();
    if (Number(smsCount) < 100) {
      toast("Minimum SMS purchase is 100.", { type: "error" });
      return;
    }
    try {
      await buySms({ sms_count: Number(smsCount) }).unwrap();
      toast("SMS purchase initiated.", { type: "success" });
      setIsSmsOpen(false);
    } catch {
      toast("Could not process the SMS purchase.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.created_at) },
    { key: "type", header: "Type" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    {
      key: "invoice",
      header: "Tax invoice",
      render: (row) =>
        row.status === "paid" && (
          <button
            onClick={() =>
              generateTaxInvoice({ id: row.id }).then(() =>
                downloadFile(row.tax_invoice_url ?? "/billing/tax-invoice", { filename: `tax-invoice-${row.id}.pdf` })
              )
            }
            className="flex items-center gap-1 text-xs text-secondary hover:underline"
          >
            <FileText className="h-3.5 w-3.5" /> Download
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
            <Button variant="ghost" leftIcon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => setIsSmsOpen(true)}>
              Buy SMS
            </Button>
            <Button leftIcon={<CreditCard className="h-4 w-4" />} onClick={() => setIsPayOpen(true)}>
              Pay subscription
            </Button>
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Plan" value={data?.plan ?? "—"} icon={<CreditCard className="h-5 w-5" />} />
          <SummaryCard label="Amount due" value={formatCurrency(data?.amount_due)} icon={<CreditCard className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Next billing date" value={data?.next_billing_date ? formatDate(data.next_billing_date) : "—"} icon={<CreditCard className="h-5 w-5" />} />
          <SummaryCard label="SMS balance" value={data?.sms_balance ?? 0} icon={<MessageSquarePlus className="h-5 w-5" />} accent="third" />
        </div>
      )}

      <div className="mt-6">
        <h3 className="mb-3 text-base font-medium text-white">Transactions</h3>
        <ResponsiveTable columns={columns} rows={transactions} isLoading={isTransactionsLoading} />
      </div>

      <Modal isOpen={isPayOpen} onClose={() => setIsPayOpen(false)} title="Pay subscription">
        <form onSubmit={handlePay} className="space-y-4">
          <Select
            label="Billing cycle"
            value={plan}
            onChange={(e) => setPlan(e.target.value)}
            options={SUBSCRIPTION_PLANS.map((p) => ({ value: p, label: `${p} (${PLAN_DISCOUNTS[p]} off)` }))}
            required
          />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsPayOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isPaying}>
              Pay now
            </Button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={isSmsOpen} onClose={() => setIsSmsOpen(false)} title="Buy SMS">
        <form onSubmit={handleBuySms} className="space-y-4">
          <Input label="Number of SMS" type="number" min="100" value={smsCount} onChange={(e) => setSmsCount(e.target.value)} hint="Minimum 100" required />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsSmsOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isBuying}>
              Buy now
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
