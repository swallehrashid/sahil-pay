import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useShiftTenantMutation } from "./tenantApiSlice";
import { isRequired } from "@/utils/validators";

// Writes a tenant_unit_history row and flips is_occupied on both units (§5.2).
export default function ShiftTenantModal({ tenant, units = [], onClose }) {
  const [shiftTenant, { isLoading }] = useShiftTenantMutation();
  const [unitId, setUnitId] = useState("");
  const [movedInAt, setMovedInAt] = useState("");
  const [error, setError] = useState("");

  if (!tenant) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isRequired(unitId)) {
      setError("Select the new unit");
      return;
    }
    setError("");
    try {
      await shiftTenant({ id: tenant.id, unit_id: unitId, moved_in_at: movedInAt || undefined }).unwrap();
      toast(`${tenant.first_name} has been shifted.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not shift the tenant.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Shift ${tenant.first_name} ${tenant.last_name}`}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-sm text-white/50">Currently in {tenant.unit_name ?? "—"}. Choose the new unit below.</p>
        <Select
          label="New unit"
          value={unitId}
          onChange={(e) => setUnitId(e.target.value)}
          error={error}
          options={units.map((u) => ({ value: u.id, label: `${u.name} (${u.property_name ?? ""})` }))}
          required
        />
        <DatePicker label="Move-in date" value={movedInAt} onChange={(e) => setMovedInAt(e.target.value)} hint="Optional — defaults to today" />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Shift tenant
          </Button>
        </div>
      </form>
    </Modal>
  );
}
