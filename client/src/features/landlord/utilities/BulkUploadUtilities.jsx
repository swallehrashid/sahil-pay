import { useMemo, useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useBulkUploadUtilitiesMutation, useGenerateUtilityInvoicesMutation } from "./utilityApiSlice";
import { useGetChargeCategoriesQuery } from "../chargeCategoryApiSlice";
import { currentMonth } from "@/utils/dateFormatter";

const STEP_TITLES = {
  1: "Step 1 of 3 · Set filters",
  2: "Step 2 of 3 · Record readings",
  3: "Step 3 of 3 · Create invoices",
};

// Three-page bulk utilities flow:
//   1) Filters    — who you're recording for (property + month).
//   2) Record     — pick the utility, then enter each unit's previous (past month)
//                   and current (this month) readings.
//   3) Invoices   — bill the batch: add to each tenant's current invoice, or raise new ones.
export default function BulkUploadUtilities({ isOpen, onClose, properties = [], units = [] }) {
  const [bulkUpload, { isLoading: isUploading }] = useBulkUploadUtilitiesMutation();
  const [generateInvoices, { isLoading: isGenerating }] = useGenerateUtilityInvoicesMutation();
  const { data: catData } = useGetChargeCategoriesQuery({ kind: "utility", include_inactive: 0 });
  const categories = catData?.categories ?? [];

  const [step, setStep] = useState(1);
  const [scope, setScope] = useState({ property_id: "", category_id: "", reading_month: currentMonth() });
  const [readings, setReadings] = useState({}); // { [unit_id]: { previous, current, amount } }
  const [savedCount, setSavedCount] = useState(0);

  const scopedUnits = useMemo(
    () => units.filter((u) => !scope.property_id || String(u.property_id) === String(scope.property_id)),
    [units, scope.property_id]
  );
  const selectedCategory = useMemo(
    () => categories.find((c) => String(c.id) === String(scope.category_id)),
    [categories, scope.category_id]
  );
  const isMetered = selectedCategory?.is_metered ?? false;

  const reset = () => {
    setStep(1);
    setReadings({});
    setSavedCount(0);
  };
  const handleClose = () => {
    reset();
    onClose();
  };

  const setReading = (unitId, key, value) =>
    setReadings((prev) => ({ ...prev, [unitId]: { ...prev[unitId], [key]: value } }));

  const handleUpload = async () => {
    const entries = isMetered
      ? Object.entries(readings).filter(([, v]) => v?.current !== "" && v?.current !== undefined)
      : Object.entries(readings).filter(([, v]) => v?.amount !== "" && v?.amount !== undefined);
    if (!entries.length) {
      toast(isMetered ? "Enter at least one current reading." : "Enter at least one amount.", { type: "info" });
      return;
    }
    try {
      const result = await bulkUpload({
        property_id: scope.property_id,
        category_id: scope.category_id,
        reading_month: scope.reading_month,
        readings: entries.map(([unit_id, v]) =>
          isMetered
            ? {
                unit_id,
                current_reading: v.current,
                ...(v.previous !== "" && v.previous !== undefined ? { previous_reading: v.previous } : {}),
              }
            : { unit_id, amount: v.amount }
        ),
      }).unwrap();
      const skipped = result?.errors?.length ?? 0;
      setSavedCount(result?.created ?? 0);
      toast(`${result?.created ?? 0} reading(s) recorded${skipped ? `, ${skipped} skipped` : ""}.`, {
        type: skipped ? "info" : "success",
      });
      setStep(3);
    } catch {
      toast("Could not save the readings.", { type: "error" });
    }
  };

  const handleGenerate = async (combine) => {
    try {
      const res = await generateInvoices({ ...scope, combine }).unwrap();
      toast(res?.message || "Utility invoices created.", { type: "success" });
      handleClose();
    } catch {
      toast("Could not create the invoices.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title={STEP_TITLES[step]} size="lg">
      {/* ── Step 1 — filters ───────────────────────────────────────────── */}
      {step === 1 && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!scope.property_id) return toast("Choose a property.", { type: "info" });
            if (!scope.category_id) return toast("Choose a utility.", { type: "info" });
            setStep(2);
          }}
          className="space-y-4"
        >
          <p className="text-sm text-white/50">Choose who you're recording utilities for.</p>
          <Select
            label="Property"
            value={scope.property_id}
            onChange={(e) => setScope((s) => ({ ...s, property_id: e.target.value }))}
            options={properties.map((p) => ({ value: p.id, label: p.name }))}
            required
          />
          <Select
            label="Utility"
            value={scope.category_id}
            onChange={(e) => setScope((s) => ({ ...s, category_id: e.target.value }))}
            options={categories.map((c) => ({ value: c.id, label: `${c.name}${c.is_metered ? " (metered)" : ""}` }))}
            hint="Manage the list under Utilities → Utility categories"
            required
          />
          <Input
            label="Reading month"
            type="month"
            value={scope.reading_month}
            onChange={(e) => setScope((s) => ({ ...s, reading_month: e.target.value }))}
            required
          />
          <p className="text-xs text-white/40">{scopedUnits.length} unit(s) in this property.</p>
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={handleClose}>Cancel</Button>
            <Button type="submit">Next: record readings</Button>
          </div>
        </form>
      )}

      {/* ── Step 2 — record readings ───────────────────────────────────── */}
      {step === 2 && (
        <div className="space-y-4">
          <p className="text-sm text-white/50">
            Recording <span className="text-white/80">{selectedCategory?.name}</span> for {scope.reading_month}.
          </p>
          {isMetered ? (
            <>
              <div className="grid grid-cols-12 px-3 text-[11px] uppercase tracking-wide text-white/40">
                <span className="col-span-4">Unit</span>
                <span className="col-span-4 text-right">Previous (last month)</span>
                <span className="col-span-4 text-right">Current (this month)</span>
              </div>
              <div className="max-h-72 space-y-2 overflow-y-auto">
                {scopedUnits.map((unit) => (
                  <div key={unit.id} className="grid grid-cols-12 items-center gap-2 rounded-lg bg-white/5 px-3 py-2">
                    <span className="col-span-4 truncate text-sm text-white/70">{unit.name}</span>
                    <input
                      type="number"
                      step="0.01"
                      placeholder="0.00"
                      value={readings[unit.id]?.previous ?? ""}
                      onChange={(e) => setReading(unit.id, "previous", e.target.value)}
                      className="glass-input col-span-4 text-right"
                    />
                    <input
                      type="number"
                      step="0.01"
                      placeholder="0.00"
                      value={readings[unit.id]?.current ?? ""}
                      onChange={(e) => setReading(unit.id, "current", e.target.value)}
                      className="glass-input col-span-4 text-right"
                    />
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-12 px-3 text-[11px] uppercase tracking-wide text-white/40">
                <span className="col-span-8">Unit</span>
                <span className="col-span-4 text-right">Amount</span>
              </div>
              <div className="max-h-72 space-y-2 overflow-y-auto">
                {scopedUnits.map((unit) => (
                  <div key={unit.id} className="grid grid-cols-12 items-center gap-2 rounded-lg bg-white/5 px-3 py-2">
                    <span className="col-span-8 truncate text-sm text-white/70">{unit.name}</span>
                    <input
                      type="number"
                      step="0.01"
                      placeholder="0.00"
                      value={readings[unit.id]?.amount ?? ""}
                      onChange={(e) => setReading(unit.id, "amount", e.target.value)}
                      className="glass-input col-span-4 text-right"
                    />
                  </div>
                ))}
              </div>
            </>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setStep(1)}>Back</Button>
            <Button type="button" isLoading={isUploading} onClick={handleUpload}>Save readings</Button>
          </div>
        </div>
      )}

      {/* ── Step 3 — create invoices ───────────────────────────────────── */}
      {step === 3 && (
        <div className="space-y-5">
          <p className="text-sm text-white/70">
            {savedCount} {selectedCategory?.name} reading(s) saved for {scope.reading_month}. How do you want to bill them?
          </p>
          <div className="space-y-3">
            <button
              type="button"
              disabled={isGenerating}
              onClick={() => handleGenerate(true)}
              className="glass w-full rounded-xl p-4 text-left transition-colors hover:bg-white/10 disabled:opacity-50"
            >
              <p className="font-medium text-white">Add to this month's invoice</p>
              <p className="text-sm text-white/50">Append each charge to the tenant's open invoice for the month (creates one if none is open).</p>
            </button>
            <button
              type="button"
              disabled={isGenerating}
              onClick={() => handleGenerate(false)}
              className="glass w-full rounded-xl p-4 text-left transition-colors hover:bg-white/10 disabled:opacity-50"
            >
              <p className="font-medium text-white">Create new invoices</p>
              <p className="text-sm text-white/50">Raise a separate utility invoice for each reading.</p>
            </button>
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={handleClose}>Not now</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
