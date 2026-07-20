import { Download } from "lucide-react";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetPortalStatementQuery } from "./tenantPortalApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";

// §6.5 — full running statement: what was charged, what was paid, current balance.
// Entries mix two shapes: invoices carry amount_due/amount_paid, payments carry
// a single amount (always a credit) — the columns below render each accordingly.
export default function TenantStatement() {
  const { data, isLoading } = useGetPortalStatementQuery();
  const rows = data?.entries ?? [];

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date) },
    {
      key: "item",
      header: "Item",
      render: (row) => (
        <div>
          <span>{row.description ?? (row.type === "invoice" ? row.invoice_no : row.payment_ref)}</span>
          {row.type === "payment" && row.proof_ref && (
            <span className="block text-xs text-white/45">
              {row.mpesa_reference ? "M-Pesa code" : "Ref"}: {row.proof_ref}
            </span>
          )}
        </div>
      ),
    },
    { key: "due", header: "Due", render: (row) => (row.type === "invoice" ? formatCurrency(row.amount_due) : "—") },
    { key: "paid", header: "Paid", render: (row) => formatCurrency(row.type === "invoice" ? row.amount_paid : row.amount) },
    { key: "balance", header: "Balance", render: (row) => formatCurrency(row.running_balance) },
  ];

  return (
    <div className="animate-fade-in-up space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-light tracking-wide text-white">Statement</h1>
        <Button variant="ghost" leftIcon={<Download className="h-4 w-4" />} onClick={() => downloadFile("/portal/statement/download", { filename: "statement.pdf" })}>
          Download
        </Button>
      </div>
      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
    </div>
  );
}
