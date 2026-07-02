import { useState } from "react";
import { Plus, Receipt, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Tabs from "@/components/ui/Tabs";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import ExpenseForm from "./ExpenseForm";
import RecurringExpenses from "./RecurringExpenses";
import { useGetExpensesQuery, useCreateExpenseMutation, useUpdateExpenseMutation, useDeleteExpenseMutation } from "./expenseApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetUnitsQuery } from "../units/unitApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { EXPENSE_CATEGORIES, EXPENSE_STATUSES } from "@/utils/constants";

export default function ExpensesPage() {
  const [tab, setTab] = useState("expenses");
  const [filters, setFilters] = useState({ property_id: "", category: "", status: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});

  const pg = usePagination();
  const { data, isLoading } = useGetExpensesQuery({ ...appliedFilters, ...pg.params });
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: unitsData } = useGetUnitsQuery();
  const [createExpense, { isLoading: isCreating }] = useCreateExpenseMutation();
  const [updateExpense, { isLoading: isUpdating }] = useUpdateExpenseMutation();
  const [deleteExpense] = useDeleteExpenseMutation();

  const [activeExpense, setActiveExpense] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const expenses = toRows(data);
  const meta = toPaginationMeta(data);
  const properties = toRows(propertiesData);
  const units = toRows(unitsData);

  const totals = { total: data?.total_amount ?? expenses.reduce((sum, e) => sum + Number(e.amount ?? 0), 0), count: expenses.length };

  const handleSubmit = async (values) => {
    try {
      if (activeExpense?.id) {
        await updateExpense({ id: activeExpense.id, ...values }).unwrap();
        toast("Expense updated.", { type: "success" });
      } else {
        await createExpense(values).unwrap();
        toast("Expense recorded.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the expense.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteExpense(pendingDelete.id).unwrap();
      toast("Expense deleted.", { type: "success" });
    } catch {
      toast("Could not delete the expense.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDate(row.expense_date) },
    { key: "scope", header: "Property / Unit", render: (row) => `${row.property_name ?? ""} ${row.unit_name ?? ""}`.trim() },
    { key: "category", header: "Category" },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "amount", header: "Amount", render: (row) => formatCurrency(row.amount) },
  ];

  return (
    <div>
      <PageHeader
        title="Expenses"
        subtitle="Every cost incurred against your portfolio"
        actions={
          tab === "expenses" && (
            <Button
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setActiveExpense(null);
                setIsFormOpen(true);
              }}
            >
              Record expense
            </Button>
          )
        }
      />

      <Tabs
        tabs={[
          { key: "expenses", label: "Expenses" },
          { key: "recurring", label: "Recurring" },
        ]}
        activeKey={tab}
        onChange={setTab}
        className="mb-6"
      />

      {tab === "expenses" ? (
        <>
          {isLoading ? (
            <SkeletonStatCards count={2} />
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <SummaryCard label="Total expenses" value={totals.count} icon={<Receipt className="h-5 w-5" />} />
              <SummaryCard label="Total spent" value={formatCurrency(totals.total)} icon={<Receipt className="h-5 w-5" />} accent="third" />
            </div>
          )}

          <div className="mt-6 flex flex-col gap-6 lg:flex-row">
            <FilterPanel
              onApply={() => { setAppliedFilters(filters); pg.reset(); }}
              onReset={() => {
                setFilters({ property_id: "", category: "", status: "", date_from: "", date_to: "" });
                setAppliedFilters({});
              }}
            >
              <Select
                label="Property"
                value={filters.property_id}
                onChange={(e) => setFilters((f) => ({ ...f, property_id: e.target.value }))}
                placeholder="All properties"
                options={properties.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Select
                label="Category"
                value={filters.category}
                onChange={(e) => setFilters((f) => ({ ...f, category: e.target.value }))}
                options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
              <Select
                label="Status"
                value={filters.status}
                onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
                options={EXPENSE_STATUSES.map((s) => ({ value: s, label: s }))}
              />
              <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
              <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
            </FilterPanel>

            <div className="flex-1">
              <ResponsiveTable
                columns={columns}
                rows={expenses}
                isLoading={isLoading}
                rowActions={(row) => (
                  <Dropdown
                    items={[
                      {
                        label: "Edit",
                        icon: <Pencil className="h-4 w-4" />,
                        onClick: () => {
                          setActiveExpense(row);
                          setIsFormOpen(true);
                        },
                      },
                      { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
                    ]}
                  />
                )}
              />
              <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
            </div>
          </div>
        </>
      ) : (
        <RecurringExpenses properties={properties} units={units} />
      )}

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeExpense?.id ? "Edit expense" : "Record expense"}>
        <ExpenseForm
          initialValues={activeExpense}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete expense?"
        description="This expense will be soft-deleted."
      />
    </div>
  );
}
