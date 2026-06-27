import { useState } from "react";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Checkbox from "@/components/ui/Checkbox";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetGlobalTrialConfigQuery, useUpdateGlobalTrialConfigMutation, useUpdateLandlordTrialMutation } from "./adminTrialApiSlice";
import { useGetAdminLandlordsQuery } from "./adminApiSlice";
import { toRows } from "@/utils/tableAdapters";

const OVERRIDE_ACTIONS = [
  { value: "extend", label: "Extend" },
  { value: "reduce", label: "Reduce" },
  { value: "revoke", label: "Revoke" },
  { value: "activate", label: "Activate" },
];

// §7.5 — global default trial + extend/reduce/revoke/activate per landlord.
export default function TrialConfig() {
  const { data, isLoading } = useGetGlobalTrialConfigQuery();
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [updateGlobal, { isLoading: isSaving }] = useUpdateGlobalTrialConfigMutation();
  const [updateLandlordTrial, { isLoading: isUpdatingLandlord }] = useUpdateLandlordTrialMutation();

  const [prevData, setPrevData] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    setForm(data);
  }

  const [override, setOverride] = useState({ landlord_id: "", duration_days: "", action: "extend", reason: "" });

  const landlords = toRows(landlordsData);

  if (isLoading || !form) return <SkeletonForm fields={3} />;

  const handleGlobalSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateGlobal(form).unwrap();
      toast("Global trial config saved.", { type: "success" });
    } catch {
      toast("Could not save the trial config.", { type: "error" });
    }
  };

  const handleOverrideSubmit = async (e) => {
    e.preventDefault();
    if (!override.reason.trim()) {
      toast("A reason is required.", { type: "error" });
      return;
    }
    try {
      await updateLandlordTrial({
        id: override.landlord_id, action: override.action,
        duration_days: override.duration_days, reason: override.reason,
      }).unwrap();
      toast("Landlord trial updated.", { type: "success" });
      setOverride((o) => ({ ...o, reason: "" }));
    } catch {
      toast("Could not update the landlord's trial.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <form onSubmit={handleGlobalSubmit} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Global default trial</h3>
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Duration (days)"
            type="number"
            value={form.duration_days ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, duration_days: e.target.value }))}
            required
          />
          <div className="flex items-end">
            <Checkbox label="Active" checked={Boolean(form.is_active)} onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))} />
          </div>
        </div>
        <div className="flex justify-end">
          <Button type="submit" isLoading={isSaving}>
            Save global config
          </Button>
        </div>
      </form>

      <form onSubmit={handleOverrideSubmit} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Per-landlord override</h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Select
            label="Landlord"
            value={override.landlord_id}
            onChange={(e) => setOverride((o) => ({ ...o, landlord_id: e.target.value }))}
            options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
            required
          />
          <Select
            label="Action"
            value={override.action}
            onChange={(e) => setOverride((o) => ({ ...o, action: e.target.value }))}
            options={OVERRIDE_ACTIONS}
          />
          <Input
            label="Duration (days)"
            type="number"
            value={override.duration_days}
            onChange={(e) => setOverride((o) => ({ ...o, duration_days: e.target.value }))}
          />
        </div>
        <Textarea
          label="Reason"
          value={override.reason}
          onChange={(e) => setOverride((o) => ({ ...o, reason: e.target.value }))}
          rows={2}
          required
        />
        <div className="flex justify-end">
          <Button type="submit" isLoading={isUpdatingLandlord}>
            Apply
          </Button>
        </div>
      </form>
    </div>
  );
}
