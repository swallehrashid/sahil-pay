import { useState } from "react";
import { Plus, Upload, Pencil, Trash2, ReceiptText, Settings2, Layers, Send } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Badge from "@/components/ui/Badge";
import Pagination from "@/components/ui/Pagination";
import { toast } from "@/components/ui/Toast";
import { usePagination } from "@/hooks/usePagination";
import { usePermissions } from "@/hooks/usePermissions";
import RecordUtilityForm from "./RecordUtilityForm";
import ChargeCategoryManager from "../ChargeCategoryManager";
import BulkUploadUtilities from "./BulkUploadUtilities";
import GenerateUtilityCategoryInvoices from "./GenerateUtilityCategoryInvoices";
import { useGetUtilityReadingsQuery, useCreateUtilityReadingMutation, useUpdateUtilityReadingMutation, useDeleteUtilityReadingMutation, useAddReadingToInvoiceMutation, useQueueUtilityReadingsMutation } from "./utilityApiSlice";
import { useGetChargeCategoriesQuery } from "../chargeCategoryApiSlice";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";
import { useGetPropertyOptionsQuery, useGetUnitOptionsQuery } from "@/store/lookupApiSlice";

// A reading has a resolvable rate if its category carries a default_rate, or it's
// water/electricity (billed at the property's own rate columns) — everything else
// (garbage, security, or any other non-rated category) needs an explicit amount.
const hasResolvableRate = (reading) =>
  reading.default_rate != null || ["water", "electricity"].includes((reading.utility_item || "").toLowerCase());

// Where a reading stands between the meter and the tenant's invoice.
function readingStatus(row) {
  if (row.invoice_id) return { label: row.invoice_number ? `Invoiced · ${row.invoice_number}` : "Invoiced", color: "emerald" };
  switch (row.queue_status) {
    case "pending": return { label: "Waiting for review", color: "third" };
    case "queued": return { label: "Approved · next invoice", color: "secondary" };
    case "rejected": return { label: "Rejected", color: "white" };
    default: return { label: "Not billed", color: "white" };
  }
}

export default function UtilitiesPage() {
  const { can } = usePermissions();
  // Billing is the invoices editor's job. Anyone who can edit utilities can
  // submit readings; without Invoices → Edit they go in for review.
  const canBill = can("invoices", "edit");
  const canEdit = can("utilities", "edit");
  const pg = usePagination(50);
  const [filters, setFilters] = useState({ property_id: "", reading_month: "", billing: "" });
  const setFilter = (key) => (e) => { setFilters((f) => ({ ...f, [key]: e.target.value })); pg.reset(); };
  const { data, isLoading } = useGetUtilityReadingsQuery({ ...pg.params, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) });
  const [queueReadings, { isLoading: isQueueing }] = useQueueUtilityReadingsMutation();
  const [queueScope, setQueueScope] = useState(null); // { property_id, reading_month }
  const { data: propertiesData } = useGetPropertyOptionsQuery();
  const { data: unitsData } = useGetUnitOptionsQuery();
  const { data: catData } = useGetChargeCategoriesQuery({ kind: "utility", include_inactive: 0 });
  const [createReading, { isLoading: isCreating }] = useCreateUtilityReadingMutation();
  const [updateReading, { isLoading: isUpdating }] = useUpdateUtilityReadingMutation();
  const [deleteReading] = useDeleteUtilityReadingMutation();
  const [addToInvoice, { isLoading: isBilling }] = useAddReadingToInvoiceMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isTypesOpen, setIsTypesOpen] = useState(false);
  const [isBulkOpen, setIsBulkOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [billReading, setBillReading] = useState(null); // reading being added to an invoice
  const [billAmount, setBillAmount] = useState("");
  const [generateCategory, setGenerateCategory] = useState(null);

  const categories = catData?.categories ?? [];

  const bill = async (mode) => {
    try {
      const body = { id: billReading.id, mode };
      if (billAmount) body.amount = Number(billAmount);
      const res = await addToInvoice(body).unwrap();
      toast(
        mode === "queue"
          ? "Held for this unit's next invoice."
          : res?.combined
          ? "Added to this month's invoice."
          : "New invoice created.",
        { type: "success" }
      );
      setBillReading(null);
      setBillAmount("");
    } catch (err) {
      toast(err?.data?.error || "Could not add this reading to an invoice.", { type: "error" });
    }
  };

  const readings = toRows(data);
  const meta = toPaginationMeta(data);
  const properties = toRows(propertiesData);

  const submitQueue = async (body) => {
    try {
      const res = await queueReadings(body).unwrap();
      toast(res.message, { type: res.queued ? "success" : "info", duration: 7000 });
      setQueueScope(null);
    } catch (err) {
      toast(err?.data?.error || "Could not queue those readings.", { type: "error" });
    }
  };
  const units = toRows(unitsData);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateReading({ id: active.id, ...values }).unwrap();
        toast("Reading updated.", { type: "success" });
      } else {
        await createReading(values).unwrap();
        toast("Reading recorded.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the reading.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteReading(pendingDelete.id).unwrap();
      toast("Reading deleted.", { type: "success" });
    } catch {
      toast("Could not delete the reading.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "month", header: "Month", render: (row) => row.reading_month },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "unit", header: "Unit", render: (row) => row.unit_name },
    { key: "item", header: "Item", render: (row) => row.category_name || row.utility_item },
    { key: "previous", header: "Previous", render: (row) => row.previous_reading ?? "—" },
    { key: "current", header: "Current", render: (row) => row.current_reading ?? "—" },
    { key: "amount", header: "Flat amount", render: (row) => (row.amount != null ? row.amount : "—") },
    {
      key: "status", header: "Status",
      render: (row) => { const st = readingStatus(row); return <Badge color={st.color}>{st.label}</Badge>; },
    },
  ];

  return (
    <div>
      <PageHeader
        title="Utilities"
        subtitle="Meter readings across water, electricity, garbage and security"
        actions={
          <>
            {canEdit && (
              <Button
                variant="ghost"
                leftIcon={<Send className="h-4 w-4" />}
                onClick={() => setQueueScope({ property_id: filters.property_id, reading_month: filters.reading_month || new Date().toISOString().slice(0, 7) })}
                data-testid="queue-readings-open"
                data-tour={ANCHORS.utilities.queueButton}
              >
                {canBill ? "Queue for next invoice" : "Submit for review"}
              </Button>
            )}
            {canBill && (
            <Dropdown
              align="right"
              trigger={
                <Button variant="ghost" leftIcon={<Layers className="h-4 w-4" />}>
                  Generate invoices
                </Button>
              }
              items={
                categories.length
                  ? categories.map((c) => ({
                      label: `Generate ${c.name} invoices`,
                      onClick: () => setGenerateCategory(c),
                    }))
                  : [{ label: "No utility categories yet", onClick: () => setIsTypesOpen(true) }]
              }
            />
            )}
            {canBill && (
            <Button
              variant="ghost"
              data-tour={ANCHORS.utilities.categoriesButton}
              leftIcon={<Settings2 className="h-4 w-4" />}
              onClick={() => setIsTypesOpen(true)}
            >
              Utility categories
            </Button>
            )}
            {canEdit && (
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setIsBulkOpen(true)}
                    data-tour={ANCHORS.utilities.bulkButton}>
              Bulk upload
            </Button>
            )}
            {canEdit && (
            <Button
              data-tour={ANCHORS.utilities.recordButton}
              leftIcon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setActive(null);
                setIsFormOpen(true);
              }}
            >
              Record reading
            </Button>
            )}
          </>
        }
      />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Select label="Property" value={filters.property_id} onChange={setFilter("property_id")}
                options={[{ value: "", label: "All properties" }, ...properties.map((p) => ({ value: p.id, label: p.name }))]} />
        <Input label="Month" type="month" value={filters.reading_month} onChange={setFilter("reading_month")} />
        <Select label="Billing" value={filters.billing} onChange={setFilter("billing")}
                options={[{ value: "", label: "All readings" }, { value: "unbilled", label: "Not invoiced yet" }]} />
      </div>

      <ResponsiveTable
        columns={columns}
        rows={readings}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              ...(!row.invoice_id && canBill
                ? [{
                    label: "Add to invoice",
                    icon: <ReceiptText className="h-4 w-4" />,
                    onClick: () => {
                      setBillReading(row);
                      setBillAmount("");
                    },
                  }]
                : []),
              ...(!row.invoice_id && !row.queue_status && canEdit
                ? [{
                    label: canBill ? "Queue for next invoice" : "Submit for review",
                    icon: <Send className="h-4 w-4" />,
                    onClick: () => submitQueue({ reading_ids: [row.id] }),
                  }]
                : []),
              {
                label: "Edit",
                icon: <Pencil className="h-4 w-4" />,
                onClick: () => {
                  setActive(row);
                  setIsFormOpen(true);
                },
              },
              { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />

      <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />

      <Modal isOpen={Boolean(queueScope)} onClose={() => setQueueScope(null)}
             title={canBill ? "Queue readings for the next invoice" : "Submit readings for review"}>
        {queueScope && (
          <div className="space-y-4">
            <p className="text-sm text-white/60">
              {canBill
                ? "Every reading below that is not billed yet goes onto its unit's next monthly invoice."
                : "Every reading below that is not billed yet is sent to the office. Once it is approved it goes onto the unit's next monthly invoice."}
            </p>
            <Select label="Property" value={queueScope.property_id}
                    onChange={(e) => setQueueScope((q) => ({ ...q, property_id: e.target.value }))}
                    options={[{ value: "", label: "All my properties" }, ...properties.map((p) => ({ value: p.id, label: p.name }))]} />
            <Input label="Reading month" type="month" value={queueScope.reading_month}
                   onChange={(e) => setQueueScope((q) => ({ ...q, reading_month: e.target.value }))} required />
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setQueueScope(null)}>Cancel</Button>
              <Button isLoading={isQueueing} data-testid="queue-readings-submit"
                      onClick={() => submitQueue(Object.fromEntries(Object.entries(queueScope).filter(([, v]) => v)))}>
                {canBill ? "Queue readings" : "Submit for review"}
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal isOpen={Boolean(billReading)} onClose={() => setBillReading(null)} title="Add reading to an invoice">
        {billReading && (
          <div className="space-y-4">
            <p className="text-sm text-white/60">
              {billReading.category_name || billReading.utility_item} · {billReading.unit_name} · {billReading.reading_month}
              {billReading.consumption != null ? ` · consumption ${billReading.consumption}` : ""}
            </p>
            {!hasResolvableRate(billReading) && (
              <Input
                label="Amount to bill"
                type="number"
                step="0.01"
                value={billAmount}
                onChange={(e) => setBillAmount(e.target.value)}
                hint={`${billReading.category_name || billReading.utility_item} has no meter rate — enter the charge.`}
              />
            )}
            {hasResolvableRate(billReading) && (
              <Input
                label="Amount (optional override)"
                type="number"
                step="0.01"
                value={billAmount}
                onChange={(e) => setBillAmount(e.target.value)}
                hint="Leave blank to bill consumption × the property's rate."
              />
            )}
            {/* Three ways to bill a reading, because meters are read at the
                END of a month and the bill goes out at the START of the next
                one. On the 28th there is often no invoice to attach to, and
                raising a one-line utility invoice sends the tenant a second,
                unexpected bill — so "hold it" is a first-class option, not a
                workaround. */}
            <p className="text-xs leading-relaxed text-white/40">
              Read the meter before the month closes? Hold it — the next invoice
              for this unit picks it up automatically.
            </p>
            <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-end">
              <Button variant="ghost" onClick={() => bill("queue")} isLoading={isBilling}>
                Hold for next invoice
              </Button>
              <Button variant="ghost" onClick={() => bill("new")} isLoading={isBilling}>
                Create new invoice
              </Button>
              <Button onClick={() => bill("current")} isLoading={isBilling}>
                Add to this month's invoice
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit reading" : "Record reading"}>
        <RecordUtilityForm
          initialValues={active}
          properties={properties}
          units={units}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <ChargeCategoryManager isOpen={isTypesOpen} onClose={() => setIsTypesOpen(false)} kind="utility" />

      <BulkUploadUtilities isOpen={isBulkOpen} onClose={() => setIsBulkOpen(false)} properties={properties} units={units}
                           canBill={canBill} />

      <GenerateUtilityCategoryInvoices
        isOpen={Boolean(generateCategory)}
        onClose={() => setGenerateCategory(null)}
        category={generateCategory}
        properties={properties}
      />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete reading?"
        description="This utility reading will be permanently removed."
      />
    </div>
  );
}
