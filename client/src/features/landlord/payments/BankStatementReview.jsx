import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGetBankStatementTransactionsQuery, useImportBankStatementTransactionsMutation } from "./paymentApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

// Landlord reviews parsed bank_statement_transactions and selects which to import as payments.
export default function BankStatementReview() {
  const { id } = useParams();
  const { data, isLoading } = useGetBankStatementTransactionsQuery(id);
  const [importTransactions, { isLoading: isImporting }] = useImportBankStatementTransactionsMutation();
  const [selectedIds, setSelectedIds] = useState([]);

  const rows = toRows(data);
  const toggle = (txnId) => setSelectedIds((prev) => (prev.includes(txnId) ? prev.filter((x) => x !== txnId) : [...prev, txnId]));

  const handleImport = async () => {
    try {
      await importTransactions({ id, transaction_ids: selectedIds }).unwrap();
      toast(`${selectedIds.length} transaction(s) imported as payments.`, { type: "success" });
      setSelectedIds([]);
    } catch {
      toast("Could not import the selected transactions.", { type: "error" });
    }
  };

  const columns = [
    { key: "select", header: "", render: (row) => <Checkbox checked={selectedIds.includes(row.id)} onChange={() => toggle(row.id)} /> },
    { key: "txn_date", header: "Date", render: (row) => formatDate(row.txn_date) },
    { key: "description", header: "Description" },
    { key: "reference", header: "Reference" },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
    { key: "imported", header: "Imported", render: (row) => (row.is_imported ? "Yes" : "No") },
  ];

  return (
    <div>
      <PageHeader
        title="Review bank statement"
        subtitle="Select which transactions to import as payments"
        breadcrumbs={[{ label: "Payments", to: LANDLORD_ROUTES.payments }, { label: "Statement review" }]}
        actions={
          <>
            <Link to={LANDLORD_ROUTES.payments}>
              <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
                Back
              </Button>
            </Link>
            <Button leftIcon={<Check className="h-4 w-4" />} disabled={!selectedIds.length} isLoading={isImporting} onClick={handleImport}>
              Import selected
            </Button>
          </>
        }
      />
      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} />
    </div>
  );
}
