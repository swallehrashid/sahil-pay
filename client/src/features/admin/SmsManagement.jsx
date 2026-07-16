import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Wallet, TrendingUp, Coins, Percent, Gauge, Plus, RefreshCw, MessageSquare, Link2, Unlink } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import Tabs from "@/components/ui/Tabs";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import Spinner from "@/components/ui/Spinner";
import Modal from "@/components/ui/Modal";
import Badge from "@/components/ui/Badge";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import SmsRevenueCostChart from "@/components/charts/SmsRevenueCostChart";
import ReportView from "@/features/landlord/reports/ReportView";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetSmsPricingQuery,
  useUpdateSmsPricingMutation,
  useGetSmsOverviewQuery,
  useGetSmsPoolHistoryQuery,
  useTopUpSmsPoolMutation,
  useSyncSmsPoolMutation,
  useGetLandlordSmsProviderQuery,
  useUpdateLandlordSmsProviderMutation,
  useGetSmsReportQuery,
} from "./adminSmsApiSlice";

const TABS = [
  { key: "monitoring", label: "Monitoring" },
  { key: "pricing", label: "Pricing" },
  { key: "pool", label: "SMS pool" },
  { key: "report", label: "Report" },
];

// §9.3 — the admin cockpit for Sahil Pay's SMS reselling business: set the price
// per SMS for default (shared sender) and custom (own sender) users, top up and
// monitor the shared pool, watch revenue vs cost and margin, and download the
// SMS analytics report through the shared report engine.
export default function SmsManagement() {
  const [tab, setTab] = useState("monitoring");

  return (
    <div className="space-y-6">
      <PageHeader
        title="SMS management"
        subtitle="Pricing, shared pool, monitoring and reselling analytics"
        breadcrumbs={[{ label: "Admin", to: ADMIN_ROUTES.dashboard }, { label: "SMS" }]}
      />
      <Tabs tabs={TABS} activeKey={tab} onChange={setTab} />
      {tab === "monitoring" && <MonitoringTab />}
      {tab === "pricing" && <PricingTab />}
      {tab === "pool" && <PoolTab />}
      {tab === "report" && <ReportTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------
function MonitoringTab() {
  const navigate = useNavigate();
  const { data, isLoading } = useGetSmsOverviewQuery();
  const [providerLandlord, setProviderLandlord] = useState(null); // { landlord_id, landlord }

  const t = data?.totals ?? {};

  const columns = [
    { key: "landlord", header: "Landlord" },
    { key: "bought", header: "Bought", render: (r) => (r.bought ?? 0).toLocaleString() },
    { key: "revenue", header: "Revenue", render: (r) => formatCurrency(r.revenue) },
    { key: "spent", header: "Spent", render: (r) => (r.spent ?? 0).toLocaleString() },
    { key: "spent_shared", header: "Shared", render: (r) => (r.spent_shared ?? 0).toLocaleString() },
    { key: "spent_own", header: "Own", render: (r) => (r.spent_own ?? 0).toLocaleString() },
    { key: "cost", header: "Cost", render: (r) => formatCurrency(r.cost) },
    { key: "balance", header: "Balance", render: (r) => (r.balance ?? 0).toLocaleString() },
  ];

  return (
    <div className="space-y-6">
      {isLoading ? (
        <SkeletonStatCards count={6} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <SummaryCard label="Pool balance" value={(data?.pool_balance ?? 0).toLocaleString()} icon={<Wallet className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Resale revenue" value={formatCurrency(t.revenue)} icon={<TrendingUp className="h-5 w-5" />} />
          <SummaryCard label="Platform cost" value={formatCurrency(t.platform_cost)} icon={<Coins className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Gross margin" value={formatCurrency(t.gross_margin)} icon={<TrendingUp className="h-5 w-5" />} />
          <SummaryCard label="Margin" value={`${t.margin_pct ?? 0}%`} icon={<Percent className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Pool usage" value={`${data?.pool_usage_pct ?? 0}%`} icon={<Gauge className="h-5 w-5" />} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">SMS sold (all-time)</p>
          <p className="mt-2 text-2xl font-light text-white">{(t.sms_sold ?? 0).toLocaleString()}</p>
          <p className="mt-1 text-xs text-white/40">Avg rate {formatCurrency(t.avg_rate)} / SMS</p>
        </div>
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">SMS spent by landlords</p>
          <p className="mt-2 text-2xl font-light text-white">{(t.sms_spent ?? 0).toLocaleString()}</p>
          <p className="mt-1 text-xs text-white/40">{(t.spent_shared ?? 0).toLocaleString()} shared · {(t.spent_own ?? 0).toLocaleString()} own sender</p>
        </div>
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">Shared sending</p>
          <p className="mt-2 text-2xl font-light text-white">{data?.shared_enabled ? "Enabled" : "Disabled"}</p>
          <p className="mt-1 text-xs text-white/40">{(data?.pool_added_total ?? 0).toLocaleString()} credits topped up to date</p>
        </div>
      </div>

      <SmsRevenueCostChart data={data?.monthly ?? []} />

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Per-landlord SMS activity</h3>
        <ResponsiveTable
          columns={columns}
          rows={data?.landlords ?? []}
          keyField="landlord_id"
          onRowClick={(r) => navigate(ADMIN_ROUTES.landlordDetailPath(r.landlord_id))}
          rowActions={(r) => (
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<MessageSquare className="h-4 w-4" />}
              onClick={(e) => {
                e.stopPropagation();
                setProviderLandlord(r);
              }}
            >
              SMS provider
            </Button>
          )}
        />
      </div>

      {providerLandlord && (
        <LandlordProviderModal
          landlordId={providerLandlord.landlord_id}
          landlordName={providerLandlord.landlord}
          onClose={() => setProviderLandlord(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Admin — connect/edit a landlord's custom SMS sender on their behalf
// ---------------------------------------------------------------------------
function LandlordProviderModal({ landlordId, landlordName, onClose }) {
  const { data, isLoading } = useGetLandlordSmsProviderQuery(landlordId);
  const [update, { isLoading: isSaving }] = useUpdateLandlordSmsProviderMutation();
  const [form, setForm] = useState({ sms_api_key: "", sms_sender_id: "" });
  const [prev, setPrev] = useState();

  if (data && data !== prev) {
    setPrev(data);
    setForm({ sms_api_key: "", sms_sender_id: data.sms_sender_id ?? "" });
  }

  const connected = Boolean(data?.sms_connected);

  const save = async (connectFlag) => {
    const body = { landlordId, sms_sender_id: form.sms_sender_id };
    if (form.sms_api_key.trim()) body.sms_api_key = form.sms_api_key.trim();
    if (connectFlag !== undefined) body.connected = connectFlag;
    try {
      await update(body).unwrap();
      toast(connectFlag ? "Sender ID connected." : "Details saved.", { type: "success" });
      if (connectFlag !== undefined) onClose();
      else setForm((f) => ({ ...f, sms_api_key: "" }));
    } catch (err) {
      toast(err?.data?.error ?? "Could not save.", { type: "error" });
    }
  };

  return (
    <Modal isOpen title={`SMS provider — ${landlordName ?? `Landlord #${landlordId}`}`} onClose={onClose} size="md">
      {isLoading ? (
        <Spinner className="mx-auto my-8" />
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            {connected ? <Badge color="emerald">Connected</Badge> : <Badge color="secondary">Not connected</Badge>}
            {connected && <span className="text-sm text-white/60">Sender ID: {data?.sms_sender_id}</span>}
          </div>
          <Input
            label="API key"
            type="password"
            placeholder={data?.sms_api_key_set ? `Saved (${data.sms_api_key_masked})` : "Paste the landlord's SMS provider API key"}
            value={form.sms_api_key}
            onChange={(e) => setForm((f) => ({ ...f, sms_api_key: e.target.value }))}
            hint={data?.sms_api_key_set ? "Leave blank to keep the saved key." : undefined}
          />
          <Input
            label="Sender ID"
            placeholder="e.g. THEIRBRAND"
            value={form.sms_sender_id}
            onChange={(e) => setForm((f) => ({ ...f, sms_sender_id: e.target.value }))}
          />
          <div className="flex flex-wrap justify-end gap-3">
            <Button variant="ghost" isLoading={isSaving} onClick={() => save(undefined)}>Save details</Button>
            {connected ? (
              <Button variant="danger" leftIcon={<Unlink className="h-4 w-4" />} isLoading={isSaving} onClick={() => save(false)}>
                Disconnect
              </Button>
            ) : (
              <Button leftIcon={<Link2 className="h-4 w-4" />} isLoading={isSaving} onClick={() => save(true)}>
                Connect
              </Button>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Pricing
// ---------------------------------------------------------------------------
function PricingTab() {
  const { data, isLoading } = useGetSmsPricingQuery();
  const [update, { isLoading: isSaving }] = useUpdateSmsPricingMutation();

  const [prev, setPrev] = useState();
  const [form, setForm] = useState(null);
  if (data && data !== prev) {
    setPrev(data);
    setForm(data);
  }

  if (isLoading || !form) return <Spinner className="mx-auto my-10" />;

  const submit = async (e) => {
    e.preventDefault();
    try {
      await update({
        default_price_per_sms: form.default_price_per_sms,
        custom_price_per_sms: form.custom_price_per_sms,
        platform_cost_per_sms: form.platform_cost_per_sms,
        shared_sending_enabled: Boolean(form.shared_sending_enabled),
      }).unwrap();
      toast("SMS pricing saved.", { type: "success" });
    } catch {
      toast("Could not save SMS pricing.", { type: "error" });
    }
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <form onSubmit={submit} className="glass max-w-2xl space-y-5 p-6">
      <div>
        <h3 className="text-base font-medium text-white">Price per SMS</h3>
        <p className="mt-1 text-sm text-white/50">
          Applies to every landlord. Default users send through Sahil Pay&apos;s shared sender ID (out
          of the pool); custom users have connected their own SMS sender ID and pay a
          per-SMS service fee.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Input
          label="Default price (KES/SMS)"
          type="number"
          step="0.0001"
          min="0"
          value={form.default_price_per_sms ?? ""}
          onChange={set("default_price_per_sms")}
          required
        />
        <Input
          label="Custom price (KES/SMS)"
          type="number"
          step="0.0001"
          min="0"
          value={form.custom_price_per_sms ?? ""}
          onChange={set("custom_price_per_sms")}
          required
        />
        <Input
          label="Platform cost (KES/SMS)"
          type="number"
          step="0.0001"
          min="0"
          value={form.platform_cost_per_sms ?? ""}
          onChange={set("platform_cost_per_sms")}
          required
        />
      </div>
      <p className="text-xs text-white/40">
        Platform cost is what Sahil Pay pays the provider — used only to compute your margin, it is
        never billed to landlords.
      </p>
      <Checkbox
        label="Allow default users to send via the shared Sahil Pay sender ID"
        checked={Boolean(form.shared_sending_enabled)}
        onChange={(e) => setForm((f) => ({ ...f, shared_sending_enabled: e.target.checked }))}
      />
      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>Save pricing</Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Pool
// ---------------------------------------------------------------------------
function PoolTab() {
  const { data: pricing } = useGetSmsPricingQuery();
  const { data: history, isLoading } = useGetSmsPoolHistoryQuery();
  const [topUp, { isLoading: isToppingUp }] = useTopUpSmsPoolMutation();
  const [sync, { isLoading: isSyncing }] = useSyncSmsPoolMutation();
  const [form, setForm] = useState({ credits: "", note: "" });

  const submit = async (e) => {
    e.preventDefault();
    const credits = parseInt(form.credits, 10);
    if (!credits || credits <= 0) {
      toast("Enter a number of credits greater than zero.", { type: "error" });
      return;
    }
    try {
      const res = await topUp({ credits, note: form.note }).unwrap();
      toast(`Pool topped up — balance ${res.pool_balance.toLocaleString()} SMS.`, { type: "success" });
      setForm({ credits: "", note: "" });
    } catch {
      toast("Could not top up the pool.", { type: "error" });
    }
  };

  const handleSync = async () => {
    try {
      const res = await sync().unwrap();
      toast(`Pool synced from provider — balance ${res.pool_balance.toLocaleString()} SMS.`, { type: "success" });
    } catch (err) {
      toast(err?.data?.error ?? "Could not reach the SMS provider.", { type: "error" });
    }
  };

  const columns = [
    { key: "created_at", header: "Date", render: (r) => formatDate(r.created_at) },
    { key: "credits_added", header: "Credits added", render: (r) => `+${(r.credits_added ?? 0).toLocaleString()}` },
    { key: "balance_after", header: "Balance after", render: (r) => (r.balance_after ?? 0).toLocaleString() },
    { key: "note", header: "Note", render: (r) => r.note ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-3">
          <SummaryCard label="Current pool balance" value={(pricing?.pool_balance ?? 0).toLocaleString()} icon={<Wallet className="h-5 w-5" />} accent="third" />
          <Button variant="ghost" className="w-full" isLoading={isSyncing} leftIcon={<RefreshCw className="h-4 w-4" />} onClick={handleSync}>
            Sync from provider
          </Button>
        </div>
        <form onSubmit={submit} className="glass space-y-4 p-6 lg:col-span-2">
          <h3 className="text-base font-medium text-white">Top up the shared pool</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Input
              label="Credits to add"
              type="number"
              min="1"
              value={form.credits}
              onChange={(e) => setForm((f) => ({ ...f, credits: e.target.value }))}
              required
            />
            <div className="sm:col-span-2">
              <Input
                label="Note (optional)"
                value={form.note}
                onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                placeholder="e.g. provider top-up, ref #123"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button type="submit" isLoading={isToppingUp} leftIcon={<Plus className="h-4 w-4" />}>Add credits</Button>
          </div>
        </form>
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Top-up history</h3>
        <ResponsiveTable columns={columns} rows={history?.topups ?? []} isLoading={isLoading} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
function ReportTab() {
  const [submitted, setSubmitted] = useState(null);
  const { data, isFetching } = useGetSmsReportQuery(submitted ?? undefined, { skip: !submitted });

  return (
    <div className="glass space-y-6 p-6">
      <div className="flex flex-wrap items-end gap-4">
        <p className="text-sm text-white/50">
          Generate the SMS reselling analytics report, edit its columns, then download as PDF or Excel.
        </p>
        <Button className="ml-auto" onClick={() => setSubmitted({ months: 12 })}>Generate</Button>
      </div>

      {isFetching && <Spinner className="mx-auto my-8" />}
      {!isFetching && submitted && data && (
        <ReportView document={data} endpoint="/admin/sms/report" params={submitted} filenameBase="sms-analytics" />
      )}
    </div>
  );
}
