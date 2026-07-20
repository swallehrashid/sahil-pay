import { useState } from "react";
import { Search } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { useCheckMpesaStatusMutation, useGetMpesaTransactionsQuery } from "./mpesaApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// §4.22 — select a shortcode, enter a reference, confirm whether the payment was recorded.
export default function MpesaStatus() {
  const [form, setForm] = useState({ shortcode: "", reference_number: "" });
  const [checkStatus, { isLoading: isChecking }] = useCheckMpesaStatusMutation();
  const { data, isLoading } = useGetMpesaTransactionsQuery();

  const rows = toRows(data);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await checkStatus(form).unwrap();
      toast(result?.status === "recorded" ? "Payment confirmed as recorded." : "No matching payment found.", {
        type: result?.status === "recorded" ? "success" : "error",
      });
    } catch {
      toast("Could not check the transaction status.", { type: "error" });
    }
  };

  const columns = [
    { key: "reference", header: "Reference", render: (row) => row.reference_number },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "description", header: "Description" },
    { key: "till", header: "Till", render: (row) => row.till_number ?? "—" },
    { key: "created_date", header: "Date", render: (row) => formatDateTime(row.created_date) },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "tenant", header: "Tenant", render: (row) => row.tenant_name ?? "—" },
  ];

  return (
    <div>
      <PageHeader title="M-Pesa Transaction Status" subtitle="Confirm whether a payment reference was recorded" />

      <form onSubmit={handleSubmit} className="glass mb-6 grid grid-cols-1 gap-4 p-6 sm:grid-cols-3">
        <Input label="Shortcode" value={form.shortcode} onChange={(e) => setForm((f) => ({ ...f, shortcode: e.target.value }))} required />
        <Input
          label="Reference number"
          value={form.reference_number}
          onChange={(e) => setForm((f) => ({ ...f, reference_number: e.target.value }))}
          required
        />
        <Button type="submit" className="self-end" leftIcon={<Search className="h-4 w-4" />} isLoading={isChecking}>
          Check status
        </Button>
      </form>

      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
    </div>
  );
}
