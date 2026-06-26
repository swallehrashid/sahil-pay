import { useState } from "react";
import { Wallet, Download } from "lucide-react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { useGetPortalDashboardQuery, useMakePortalPaymentMutation } from "./tenantPortalApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { validateMoneyField } from "@/utils/validators";

// §6.4 — receipts auto-email a copy in addition to the in-portal download.
export default function TenantPayments() {
  const { data, isLoading } = useGetPortalDashboardQuery();
  const [makePayment, { isLoading: isPaying }] = useMakePortalPaymentMutation();

  const [form, setForm] = useState({ amount: "", payment_method: "mpesa" });
  const [error, setError] = useState("");

  const payments = toRows(data?.recent_payments);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const amountError = validateMoneyField(form.amount, { allowZero: false });
    if (amountError) {
      setError(amountError);
      return;
    }
    setError("");
    try {
      await makePayment(form).unwrap();
      toast("Payment submitted.", { type: "success" });
      setForm({ amount: "", payment_method: "mpesa" });
    } catch {
      toast("Could not process your payment.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.payment_date) },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    {
      key: "receipt",
      header: "Receipt",
      render: (row) =>
        row.status === "confirmed" && (
          <button
            onClick={() => downloadFile(`/portal/payments/${row.id}/receipt`, { filename: `receipt-${row.id}.pdf` })}
            className="flex items-center gap-1 text-xs text-secondary hover:underline"
          >
            <Download className="h-3.5 w-3.5" /> Download
          </button>
        ),
    },
  ];

  return (
    <div className="animate-fade-in-up space-y-6">
      <h1 className="text-2xl font-light tracking-wide text-white">Make a payment</h1>

      <form onSubmit={handleSubmit} className="glass grid grid-cols-1 gap-4 p-6 sm:grid-cols-3">
        <Input
          label="Amount"
          type="number"
          step="0.01"
          value={form.amount}
          onChange={(e) => setForm((f) => ({ ...f, amount: e.target.value }))}
          error={error}
          required
        />
        <Select
          label="Payment method"
          value={form.payment_method}
          onChange={(e) => setForm((f) => ({ ...f, payment_method: e.target.value }))}
          options={[{ value: "mpesa", label: "M-Pesa" }]}
        />
        <Button type="submit" className="self-end" leftIcon={<Wallet className="h-4 w-4" />} isLoading={isPaying}>
          Pay now
        </Button>
      </form>

      <div>
        <h3 className="mb-3 text-base font-medium text-white">Payment history</h3>
        <ResponsiveTable columns={columns} rows={payments} isLoading={isLoading} />
      </div>
      <p className="text-xs text-white/40">Downloading a receipt also emails you a copy automatically.</p>
    </div>
  );
}
