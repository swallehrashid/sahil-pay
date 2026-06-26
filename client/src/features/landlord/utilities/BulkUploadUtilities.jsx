import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useBulkUploadUtilitiesMutation, useGenerateUtilityInvoicesMutation } from "./utilityApiSlice";
import { UTILITY_ITEMS } from "@/utils/constants";
import { currentMonth } from "@/utils/dateFormatter";

// Select a property + utility item, feed readings to every tenant's unit, then optionally
// generate utility invoices for the batch once readings are confirmed (§4.8).
export default function BulkUploadUtilities({ isOpen, onClose, properties = [], units = [] }) {
  const [bulkUpload, { isLoading: isUploading }] = useBulkUploadUtilitiesMutation();
  const [generateInvoices, { isLoading: isGenerating }] = useGenerateUtilityInvoicesMutation();

  const [step, setStep] = useState(1);
  const [scope, setScope] = useState({ property_id: "", utility_item: "water", reading_month: currentMonth() });
  const [readings, setReadings] = useState({});
  const [batchId, setBatchId] = useState(null);

  const scopedUnits = units.filter((u) => !scope.property_id || String(u.property_id) === String(scope.property_id));

  const handleClose = () => {
    setStep(1);
    setReadings({});
    setBatchId(null);
    onClose();
  };

  const handleNext = (e) => {
    e.preventDefault();
    setStep(2);
  };

  const handleUpload = async () => {
    try {
      const entries = Object.entries(readings).filter(([, v]) => v !== "" && v !== undefined);
      const result = await bulkUpload({
        ...scope,
        readings: entries.map(([unit_id, current_reading]) => ({ unit_id, current_reading })),
      }).unwrap();
      setBatchId(result?.batch_id);
      toast("Readings recorded.", { type: "success" });
      setStep(3);
    } catch {
      toast("Could not save the readings.", { type: "error" });
    }
  };

  const handleGenerate = async () => {
    try {
      await generateInvoices({ batch_id: batchId, ...scope }).unwrap();
      toast("Utility invoices generated.", { type: "success" });
      handleClose();
    } catch {
      toast("Could not generate invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Bulk upload utilities" size="lg">
      {step === 1 && (
        <form onSubmit={handleNext} className="space-y-4">
          <Select
            label="Property"
            value={scope.property_id}
            onChange={(e) => setScope((s) => ({ ...s, property_id: e.target.value }))}
            options={properties.map((p) => ({ value: p.id, label: p.name }))}
            required
          />
          <Select
            label="Utility item"
            value={scope.utility_item}
            onChange={(e) => setScope((s) => ({ ...s, utility_item: e.target.value }))}
            options={UTILITY_ITEMS.map((u) => ({ value: u, label: u }))}
            required
          />
          <Input label="Reading month" type="month" value={scope.reading_month} onChange={(e) => setScope((s) => ({ ...s, reading_month: e.target.value }))} required />
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit">Next: enter readings</Button>
          </div>
        </form>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <p className="text-sm text-white/50">Enter the current reading for each tenant's unit.</p>
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {scopedUnits.map((unit) => (
              <div key={unit.id} className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2">
                <span className="text-sm text-white/70">{unit.name}</span>
                <input
                  type="number"
                  step="0.01"
                  placeholder="Reading"
                  value={readings[unit.id] ?? ""}
                  onChange={(e) => setReadings((prev) => ({ ...prev, [unit.id]: e.target.value }))}
                  className="glass-input w-32 text-right"
                />
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button type="button" isLoading={isUploading} onClick={handleUpload}>
              Save readings
            </Button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4 text-center">
          <p className="text-sm text-white/70">Readings saved. Generate utility invoices for this batch now?</p>
          <div className="flex justify-center gap-3 pt-2">
            <Button variant="ghost" onClick={handleClose}>
              Not yet
            </Button>
            <Button isLoading={isGenerating} onClick={handleGenerate}>
              Generate invoices
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
