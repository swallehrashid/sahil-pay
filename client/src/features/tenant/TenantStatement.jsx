import { Download } from "lucide-react";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { useGetPortalStatementQuery } from "./tenantPortalApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";

// §6.5 — full running statement: what was charged, what was paid, current balance.
export default function TenantStatement() {
  const { data, isLoading } = useGetPortalStatementQuery();
  const rows = toRows(data);

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.date) },
    { key: "item", header: "Item" },
    { key: "due", header: "Due", render: (row) => formatCurrency(row.due) },
    { key: "paid", header: "Paid", render: (row) => formatCurrency(row.paid) },
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
