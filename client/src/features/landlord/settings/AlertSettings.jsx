import { useState } from "react";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { useGetAlertSettingsQuery, useUpdateAlertSettingsMutation } from "./settingsApiSlice";
import { ALERT_TYPES, ALERT_CADENCES, ALERT_CHANNELS } from "@/utils/constants";

// §4.16 — which alerts the landlord receives, cadence and channel, per alert type.
export default function AlertSettings() {
  const { data, isLoading } = useGetAlertSettingsQuery();
  const [updateAlerts, { isLoading: isSaving }] = useUpdateAlertSettingsMutation();
  const [prevData, setPrevData] = useState();
  const [alerts, setAlerts] = useState(null);
  if (data && data !== prevData) {
    setPrevData(data);
    // Backend returns { alerts: [...] }, not one of toRows()'s recognized keys.
    const existing = data.alerts ?? [];
    setAlerts(
      ALERT_TYPES.map(
        (type) => existing.find((a) => a.alert_type === type) ?? { alert_type: type, is_enabled: false, cadence: "weekly", channel: "dashboard" }
      )
    );
  }

  if (isLoading || !alerts) return <SkeletonForm fields={5} />;

  const updateAlert = (type, key, value) => setAlerts((prev) => prev.map((a) => (a.alert_type === type ? { ...a, [key]: value } : a)));

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await updateAlerts({ alerts }).unwrap();
      toast("Alert preferences saved.", { type: "success" });
    } catch {
      toast("Could not save alert preferences.", { type: "error" });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="glass space-y-4 p-6">
      {alerts.map((alert) => (
        <div key={alert.alert_type} className="grid grid-cols-1 items-center gap-4 border-b border-white/10 pb-4 last:border-0 sm:grid-cols-4">
          <Checkbox
            label={alert.alert_type.replace("_", " ")}
            checked={Boolean(alert.is_enabled)}
            onChange={(e) => updateAlert(alert.alert_type, "is_enabled", e.target.checked)}
          />
          <Select
            label="Cadence"
            value={alert.cadence}
            onChange={(e) => updateAlert(alert.alert_type, "cadence", e.target.value)}
            options={ALERT_CADENCES.map((c) => ({ value: c, label: c }))}
          />
          <Select
            label="Channel"
            value={alert.channel}
            onChange={(e) => updateAlert(alert.alert_type, "channel", e.target.value)}
            options={ALERT_CHANNELS.map((c) => ({ value: c, label: c }))}
          />
        </div>
      ))}
      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>
          Save alert preferences
        </Button>
      </div>
    </form>
  );
}
