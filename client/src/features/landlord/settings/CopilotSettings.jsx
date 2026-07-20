import { useState } from "react";
import { Copy, Smartphone, Trash2 } from "lucide-react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import StatusBadge from "@/components/ui/StatusBadge";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatDateTime } from "@/utils/dateFormatter";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows } from "@/utils/tableAdapters";
import {
  useGetCopilotSettingsQuery,
  useUpdateCopilotSettingsMutation,
  useRevokeCopilotDeviceMutation,
  useGetCopilotMessagesQuery,
} from "./copilotApiSlice";
import { useGenerateAgentCodeMutation } from "./settingsApiSlice";

// COPILOT_PLATFORM_SPEC.md §6.1 — consent + master switch, allocation mode,
// agent code, paired devices, recent activity.
export default function CopilotSettings() {
  const { data, isLoading } = useGetCopilotSettingsQuery();
  const [updateSettings, { isLoading: isSaving }] = useUpdateCopilotSettingsMutation();
  const [generateAgentCode, { isLoading: isGeneratingCode }] = useGenerateAgentCodeMutation();
  const [revokeDevice] = useRevokeCopilotDeviceMutation();
  const { data: messagesData, isLoading: isMessagesLoading } = useGetCopilotMessagesQuery({ per_page: 20 });

  const [pendingEnable, setPendingEnable] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState(null);
  const [agentCode, setAgentCode] = useState(null);

  if (isLoading || !data) return <SkeletonForm fields={6} />;

  const code = agentCode ?? data.agent_code;
  const devices = toRows(data.devices);
  const messages = toRows(messagesData);

  const handleToggleEnabled = async (next) => {
    if (next && !data.copilot_enabled) {
      setPendingEnable(true);
      return;
    }
    try {
      await updateSettings({ enabled: next }).unwrap();
      toast(next ? "Co-pilot enabled." : "Co-pilot disabled.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not update Co-pilot settings.", { type: "error" });
    }
  };

  const confirmEnable = async () => {
    try {
      await updateSettings({ enabled: true }).unwrap();
      toast("Co-pilot enabled.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not enable Co-pilot.", { type: "error" });
    } finally {
      setPendingEnable(false);
    }
  };

  const handleAllocationMode = async (autoAllocate) => {
    try {
      await updateSettings({ auto_allocate: autoAllocate }).unwrap();
      toast("Allocation mode updated.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not update allocation mode.", { type: "error" });
    }
  };

  const handleGenerateCode = async () => {
    try {
      const result = await generateAgentCode().unwrap();
      setAgentCode(result?.agent_code ?? code);
      toast("Agent code generated.", { type: "success" });
    } catch {
      toast("Could not generate an agent code.", { type: "error" });
    }
  };

  const copyAgentCode = () => {
    if (code) {
      navigator.clipboard.writeText(code);
      toast("Agent code copied.", { type: "success" });
    }
  };

  const handleRevoke = async () => {
    try {
      await revokeDevice(pendingRevoke.id).unwrap();
      toast("Device revoked.", { type: "success" });
    } catch {
      toast("Could not revoke the device.", { type: "error" });
    } finally {
      setPendingRevoke(null);
    }
  };

  const deviceColumns = [
    { key: "device_name", header: "Device" },
    { key: "device_model", header: "Model", render: (row) => row.device_model ?? "—" },
    { key: "app_version", header: "Version", render: (row) => row.app_version ?? "—" },
    {
      key: "sender_ids",
      header: "Senders",
      render: (row) => (
        <div className="flex flex-wrap gap-1">
          {(row.sender_ids ?? []).length
            ? row.sender_ids.map((s) => (
                <Badge key={s} color="third">
                  {s}
                </Badge>
              ))
            : <span className="text-white/40">—</span>}
        </div>
      ),
    },
    { key: "last_seen_at", header: "Last seen", render: (row) => formatDateTime(row.last_seen_at) },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div className="space-y-6">
      {data.copilot_admin_locked && (
        <div className="glass border border-secondary/40 bg-secondary/10 p-4 text-sm text-secondary-100">
          Co-pilot has been disabled for this account by a Sahil Pay administrator. Contact support for details.
        </div>
      )}

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Enable Co-pilot</h3>
        <p className="text-sm text-white/50">
          By enabling Co-pilot, payment confirmation SMSs forwarded from your phone will be recorded in Sahil
          as payments. You can disable this at any time.
        </p>
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant={data.copilot_enabled ? "primary" : "ghost"}
            size="sm"
            disabled={data.copilot_admin_locked}
            onClick={() => handleToggleEnabled(true)}
          >
            Enabled
          </Button>
          <Button
            type="button"
            variant={!data.copilot_enabled ? "primary" : "ghost"}
            size="sm"
            disabled={data.copilot_admin_locked}
            onClick={() => handleToggleEnabled(false)}
          >
            Disabled
          </Button>
        </div>
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Allocation mode</h3>
        <p className="text-sm text-white/50">How Co-pilot payments are applied once a tenant is matched.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button
            type="button"
            disabled={isSaving || data.copilot_admin_locked}
            onClick={() => handleAllocationMode(false)}
            className={`glass rounded-2xl border p-4 text-left transition-colors ${
              !data.copilot_auto_allocate ? "border-secondary" : "border-white/10 hover:border-white/25"
            }`}
          >
            <p className="text-sm font-medium text-white">Review first (recommended)</p>
            <p className="mt-1 text-xs text-white/50">
              Payments arrive as Pending; you confirm and allocate each one.
            </p>
          </button>
          <button
            type="button"
            disabled={isSaving || data.copilot_admin_locked}
            onClick={() => handleAllocationMode(true)}
            className={`glass rounded-2xl border p-4 text-left transition-colors ${
              data.copilot_auto_allocate ? "border-secondary" : "border-white/10 hover:border-white/25"
            }`}
          >
            <p className="text-sm font-medium text-white">Auto-allocate</p>
            <p className="mt-1 text-xs text-white/50">
              Follows your Settings → Payments auto-allocation priority.
            </p>
          </button>
        </div>
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Agent code</h3>
        <p className="text-sm text-white/50">
          Paste this into the Co-pilot app to pair a phone with this account. Regenerating stops NEW pairings
          with the old code — already-paired devices keep working; revoke them below if needed.
        </p>
        <div className="flex items-center gap-3">
          <Input value={code ?? "Not generated yet"} readOnly className="flex-1" />
          {code && (
            <Button type="button" variant="ghost" size="sm" leftIcon={<Copy className="h-4 w-4" />} onClick={copyAgentCode}>
              Copy
            </Button>
          )}
          <Button type="button" variant="ghost" size="sm" isLoading={isGeneratingCode} onClick={handleGenerateCode}>
            Generate new
          </Button>
        </div>
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Paired devices</h3>
        <ResponsiveTable
          columns={deviceColumns}
          rows={devices}
          rowActions={(row) =>
            row.status === "active" && (
              <Button variant="ghost" size="sm" leftIcon={<Trash2 className="h-4 w-4" />} onClick={() => setPendingRevoke(row)}>
                Revoke
              </Button>
            )
          }
          emptyState={
            <EmptyState
              icon={<Smartphone className="h-6 w-6" />}
              title="No devices paired yet"
              description="Generate an agent code above and paste it into the Co-pilot app."
            />
          }
        />
      </div>

      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Recent activity</h3>
        {isMessagesLoading ? (
          <SkeletonForm fields={3} />
        ) : messages.length === 0 ? (
          <EmptyState title="No Co-pilot activity yet" description="Forwarded SMSs will show up here." />
        ) : (
          <div className="divide-y divide-white/10">
            {messages.map((m) => (
              <div key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
                <div className="flex items-center gap-3">
                  <Badge color="third">{m.sender_id}</Badge>
                  <span className="text-white/50">{formatDateTime(m.created_at)}</span>
                  {m.parsed_amount != null && <span className="text-white/80">{formatCurrency(m.parsed_amount)}</span>}
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={m.parse_status} />
                  {m.parse_status === "parsed" && <StatusBadge status={m.match_status} />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        isOpen={pendingEnable}
        onClose={() => setPendingEnable(false)}
        onConfirm={confirmEnable}
        title="Enable Co-pilot?"
        isDangerous={false}
        confirmLabel="Enable"
        description="Payment confirmation SMSs forwarded from your paired phone(s) will be recorded in Sahil as payments. You can disable this at any time."
        isLoading={isSaving}
      />

      <ConfirmDialog
        isOpen={Boolean(pendingRevoke)}
        onClose={() => setPendingRevoke(null)}
        onConfirm={handleRevoke}
        title="Revoke this device?"
        description={`"${pendingRevoke?.device_name}" will stop forwarding immediately. You can re-pair it later with your agent code.`}
      />
    </div>
  );
}
