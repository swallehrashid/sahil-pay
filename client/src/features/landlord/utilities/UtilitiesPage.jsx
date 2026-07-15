import { useState } from "react";
import { Plus, Upload, Pencil, Trash2, ReceiptText, Settings2, Layers } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { toast } from "@/components/ui/Toast";
import RecordUtilityForm from "./RecordUtilityForm";
import ChargeCategoryManager from "../ChargeCategoryManager";
import BulkUploadUtilities from "./BulkUploadUtilities";
import GenerateUtilityCategoryInvoices from "./GenerateUtilityCategoryInvoices";
import { useGetUtilityReadingsQuery, useCreateUtilityReadingMutation, useUpdateUtilityReadingMutation, useDeleteUtilityReadingMutation, useAddReadingToInvoiceMutation } from "./utilityApiSlice";
import { useGetChargeCategoriesQuery } from "../chargeCategoryApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetUnitsQuery } from "../units/unitApiSlice";
import { toRows } from "@/utils/tableAdapters";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

// A reading has a resolvable rate if its category carries a default_rate, or it's
// water/electricity (billed at the property's own rate columns) — everything else
// (garbage, security, or any other non-rated category) needs an explicit amount.
const hasResolvableRate = (reading) =>
  reading.default_rate != null || ["water", "electricity"].includes((reading.utility_item || "").toLowerCase());

export default function UtilitiesPage() {
  const { data, isLoading } = useGetUtilityReadingsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: unitsData } = useGetUnitsQuery();
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
      toast(res?.combined ? "Added to this month's invoice." : "New invoice created.", { type: "success" });
      setBillReading(null);
      setBillAmount("");
    } catch (err) {
      toast(err?.data?.error || "Could not add this reading to an invoice.", { type: "error" });
    }
  };

  const readings = toRows(data);
  const properties = toRows(propertiesData);
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
    { key: "invoice", header: "Invoice #", render: (row) => row.invoice_number ?? "Not invoiced" },
  ];

  return (
    <div>
      <PageHeader
        title="Utilities"
        subtitle="Meter readings across water, electricity, garbage and security"
        actions={
          <>
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
            <Button
              variant="ghost"
              data-tour={ANCHORS.utilities.categoriesButton}
              leftIcon={<Settings2 className="h-4 w-4" />}
              onClick={() => setIsTypesOpen(true)}
            >
              Utility categories
            </Button>
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setIsBulkOpen(true)}>
              Bulk upload
            </Button>
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
          </>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={readings}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              ...(!row.invoice_id
                ? [{
                    label: "Add to invoice",
                    icon: <ReceiptText className="h-4 w-4" />,
                    onClick: () => {
                      setBillReading(row);
                      setBillAmount("");
                    },
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
            <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-end">
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

      <BulkUploadUtilities isOpen={isBulkOpen} onClose={() => setIsBulkOpen(false)} properties={properties} units={units} />

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
