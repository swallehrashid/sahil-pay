import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useGenerateUtilityInvoicesMutation } from "./utilityApiSlice";
import { currentMonth } from "@/utils/dateFormatter";

// E3 — bills all uninvoiced readings of one utility category/month/property, either
// combined into each tenant's open invoice or as fresh utility invoices. Distinct from
// BulkUploadUtilities' step 3, which only offers this right after a bulk-record batch —
// this is the standalone path for readings recorded earlier (e.g. one at a time via
// "Record reading").
export default function GenerateUtilityCategoryInvoices({ isOpen, onClose, category, properties = [] }) {
  const [generate, { isLoading }] = useGenerateUtilityInvoicesMutation();
  const [propertyId, setPropertyId] = useState("");
  const [readingMonth, setReadingMonth] = useState(currentMonth());

  if (!category) return null;

  const handleGenerate = async (combine) => {
    try {
      const res = await generate({
        property_id: propertyId || undefined,
        category_id: category.id,
        reading_month: readingMonth,
        combine,
      }).unwrap();
      toast(res?.message || `${category.name} invoices generated.`, { type: "success" });
      onClose();
    } catch {
      toast(`Could not generate ${category.name} invoices.`, { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={`Generate ${category.name} invoices`}>
      <div className="space-y-4">
        <p className="text-sm text-white/50">
          Bills every uninvoiced {category.name} reading in scope. If there are none for this month, nothing is created.
        </p>
        <Select
          label="Property"
          placeholder="All properties"
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Input label="Reading month" type="month" value={readingMonth} onChange={(e) => setReadingMonth(e.target.value)} required />
        <div className="space-y-3 pt-1">
          <button
            type="button"
            disabled={isLoading}
            onClick={() => handleGenerate(true)}
            className="glass w-full rounded-xl p-4 text-left transition-colors hover:bg-white/10 disabled:opacity-50"
          >
            <p className="font-medium text-white">Add to this month's invoice</p>
            <p className="text-sm text-white/50">Append each charge to the tenant's open invoice for the month (creates one if none is open).</p>
          </button>
          <button
            type="button"
            disabled={isLoading}
            onClick={() => handleGenerate(false)}
            className="glass w-full rounded-xl p-4 text-left transition-colors hover:bg-white/10 disabled:opacity-50"
          >
            <p className="font-medium text-white">Create new invoices</p>
            <p className="text-sm text-white/50">Raise a separate {category.name} invoice for each reading.</p>
          </button>
        </div>
        <div className="flex justify-end pt-2">
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </Modal>
  );
}
