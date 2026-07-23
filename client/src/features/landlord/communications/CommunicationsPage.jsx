import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, RotateCw, Coins } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Tabs from "@/components/ui/Tabs";
import Modal from "@/components/ui/Modal";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import MessageTemplates from "./MessageTemplates";
import { useGetSmsProviderQuery } from "../settings/smsProviderApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetCommunicationsQuery, useSendCommunicationMutation, useResendCommunicationMutation, useQuoteCommunicationMutation } from "./communicationApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { MESSAGE_CHANNELS, COMMUNICATION_STATUSES } from "@/utils/constants";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows, toPaginationMeta } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

export default function CommunicationsPage() {
  const [searchParams] = useSearchParams();
  const tenantIdFromQuery = searchParams.get("tenant_id");
  const composeFromQuery = searchParams.get("compose"); // #2 — pill deep-links "?compose=sms"

  const { data: smsProvider } = useGetSmsProviderQuery();

  const [tab, setTab] = useState("log");
  const [filters, setFilters] = useState({ status: "", message_type: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [isComposeOpen, setIsComposeOpen] = useState(() => Boolean(tenantIdFromQuery || composeFromQuery));
  const [compose, setCompose] = useState({
    tenant_id: tenantIdFromQuery ?? "",
    message_type: composeFromQuery === "sms" ? "sms" : "sms",
    content: "",
  });

  const pg = usePagination();
  const { data, isLoading } = useGetCommunicationsQuery({ ...appliedFilters, ...pg.params });
  const { data: tenantsData } = useGetTenantsQuery();
  const [sendCommunication, { isLoading: isSending }] = useSendCommunicationMutation();
  const [resend] = useResendCommunicationMutation();

  const logs = toRows(data);
  const meta = toPaginationMeta(data);
  const tenants = toRows(tenantsData);

  // The API returns lifetime counters under `summary`; fall back to the current
  // page only if the summary isn't present.
  const totals = {
    sent: data?.summary?.total_sent ?? logs.length,
    delivered: data?.summary?.total_delivered ?? logs.filter((l) => l.status === "delivered").length,
    failed: data?.summary?.total_failed ?? logs.filter((l) => l.status === "failed").length,
  };

  const handleSend = async (e) => {
    e.preventDefault();
    try {
      // The composer holds { tenant_id, message_type, content } but POST /communications/send
      // expects { tenant_ids: [int], channel, content }. Map the shape here, otherwise the
      // API always rejects with "tenant_ids list is required."
      await sendCommunication({
        tenant_ids: compose.tenant_id ? [Number(compose.tenant_id)] : [],
        channel: compose.message_type,
        content: compose.content,
      }).unwrap();
      toast("Message sent.", { type: "success" });
      setIsComposeOpen(false);
      setCompose({ tenant_id: "", message_type: "sms", content: "" });
    } catch {
      toast("Could not send the message.", { type: "error" });
    }
  };

  const columns = [
    { key: "date", header: "Date", render: (row) => formatDateTime(row.sent_at ?? row.created_at) },
    { key: "type", header: "Type", render: (row) => row.message_type },
    { key: "recipient", header: "Recipient", render: (row) => row.tenant_name ?? row.team_member_name ?? "—" },
    { key: "scope", header: "Property / Unit", render: (row) => `${row.property_name ?? ""} ${row.unit_name ?? ""}`.trim() || "—" },
    { key: "charge", header: "SMS charge", render: (row) => row.sms_charge ?? 0 },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div>
      <PageHeader
        title="Communications"
        subtitle="Every message sent through Sahil Pay"
        actions={
          tab === "log" && (
            <Button data-tour={ANCHORS.communications.composeButton} leftIcon={<Send className="h-4 w-4" />} onClick={() => setIsComposeOpen(true)}>
              Send message
            </Button>
          )
        }
      />

      {/* #2 — live SMS balance + the FIXED admin-set price per SMS (never landlord-editable) */}
      {smsProvider && (
        <div className="glass mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl px-4 py-3 text-sm">
          <span className="text-white/80">
            SMS balance: <strong className="text-white">{smsProvider.sms_balance ?? 0}</strong> credits
          </span>
          <span className="text-white/60">
            Sender: <span className="text-white/90">{smsProvider.sender_id}</span>{" "}
            <span className="text-white/40">({smsProvider.sender_mode === "custom" ? "your own sender ID" : "Sahil Pay shared"})</span>
          </span>
          <span className="text-white/60">
            Price per SMS: <span className="text-white/90">{formatCurrency(smsProvider.price_per_sms, smsProvider.currency)}</span>{" "}
            <span className="text-white/40">(fixed)</span>
          </span>
        </div>
      )}

      <Tabs
        tabs={[
          { key: "log", label: "Log" },
          { key: "templates", label: "Templates", dataTour: ANCHORS.communications.templatesTab },
        ]}
        activeKey={tab}
        onChange={setTab}
        className="mb-6"
      />

      {tab === "log" ? (
        <>
          {isLoading ? (
            <SkeletonStatCards count={3} />
          ) : (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <SummaryCard label="Total sent" value={totals.sent} icon={<Send className="h-5 w-5" />} />
              <SummaryCard label="Delivered" value={totals.delivered} icon={<Send className="h-5 w-5" />} accent="third" />
              <SummaryCard label="Failed" value={totals.failed} icon={<Send className="h-5 w-5" />} />
            </div>
          )}

          <div className="mt-6 flex flex-col gap-6 lg:flex-row">
            <FilterPanel
              onApply={() => { setAppliedFilters(filters); pg.reset(); }}
              onReset={() => {
                setFilters({ status: "", message_type: "", date_from: "", date_to: "" });
                setAppliedFilters({});
              }}
            >
              <Select
                label="Channel"
                value={filters.message_type}
                onChange={(e) => setFilters((f) => ({ ...f, message_type: e.target.value }))}
                options={MESSAGE_CHANNELS.map((c) => ({ value: c, label: c }))}
              />
              <Select
                label="Status"
                value={filters.status}
                onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
                options={COMMUNICATION_STATUSES.map((s) => ({ value: s, label: s }))}
              />
              <DatePicker label="From" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
              <DatePicker label="To" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
            </FilterPanel>

            <div className="min-w-0 flex-1" data-tour={ANCHORS.communications.log}>
              <ResponsiveTable
                columns={columns}
                rows={logs}
                isLoading={isLoading}
                rowActions={(row) =>
                  row.status === "failed" && (
                    <button
                      onClick={() => resend(row.id).then(() => toast("Message resent.", { type: "success" }))}
                      className="rounded-lg p-1.5 text-white/50 transition-colors hover:bg-white/10 hover:text-white"
                    >
                      <RotateCw className="h-4 w-4" />
                    </button>
                  )
                }
              />
              <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
            </div>
          </div>
        </>
      ) : (
        <MessageTemplates />
      )}

      <Modal isOpen={isComposeOpen} onClose={() => setIsComposeOpen(false)} title="Send message">
        <form onSubmit={handleSend} className="space-y-4">
          <Select
            label="Tenant"
            value={compose.tenant_id}
            onChange={(e) => setCompose((c) => ({ ...c, tenant_id: e.target.value }))}
            options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))}
            required
          />
          <Select
            label="Channel"
            value={compose.message_type}
            onChange={(e) => setCompose((c) => ({ ...c, message_type: e.target.value }))}
            options={MESSAGE_CHANNELS.map((c) => ({ value: c, label: c }))}
            required
          />
          <Textarea label="Message" rows={4} value={compose.content} onChange={(e) => setCompose((c) => ({ ...c, content: e.target.value }))} required />
          {compose.message_type === "sms" && (
            <SmsCostEstimate
              content={compose.content}
              tenantIds={compose.tenant_id ? [Number(compose.tenant_id)] : []}
            />
          )}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsComposeOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isSending}>
              Send
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// Pre-send SMS credit calculator — shows exactly how many credits the message
// will cost (by word count, per the admin tiers) before the landlord sends.
// Email/in-app are free, so this only renders for the SMS channel.
function SmsCostEstimate({ content, tenantIds }) {
  const [quote, { data, isLoading }] = useQuoteCommunicationMutation();

  useEffect(() => {
    if (!content?.trim()) return;
    const t = setTimeout(() => {
      quote({ content, tenant_ids: tenantIds });
    }, 400); // debounce as the landlord types
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, JSON.stringify(tenantIds)]);

  if (!content?.trim()) return null;

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm">
      <div className="flex items-center gap-2 text-white/70">
        <Coins className="h-4 w-4 text-secondary-200" />
        <span className="font-medium text-white">SMS cost</span>
      </div>
      {isLoading || !data ? (
        <p className="mt-1 text-xs text-white/40">Calculating…</p>
      ) : (
        <div className="mt-1 space-y-1 text-xs text-white/60">
          <p>
            <span className="text-white">{data.total_credits}</span> credit
            {data.total_credits === 1 ? "" : "s"} for{" "}
            <span className="text-white">{data.recipients}</span> message
            {data.recipients === 1 ? "" : "s"}
            {data.per_recipient?.[0]?.words != null && (
              <span className="text-white/40"> · {data.per_recipient[0].words} words each</span>
            )}
          </p>
          <p className={data.sufficient ? "text-white/40" : "text-rose-300"}>
            Balance: {data.sms_balance} credit{data.sms_balance === 1 ? "" : "s"}
            {!data.sufficient && " — not enough to send"}
          </p>
        </div>
      )}
    </div>
  );
}
