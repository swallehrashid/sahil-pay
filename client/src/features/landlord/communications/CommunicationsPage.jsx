import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Send, RotateCw } from "lucide-react";
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
import { useGetCommunicationsQuery, useSendCommunicationMutation, useResendCommunicationMutation } from "./communicationApiSlice";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { MESSAGE_CHANNELS, COMMUNICATION_STATUSES } from "@/utils/constants";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

export default function CommunicationsPage() {
  const [searchParams] = useSearchParams();
  const tenantIdFromQuery = searchParams.get("tenant_id");

  const [tab, setTab] = useState("log");
  const [filters, setFilters] = useState({ status: "", message_type: "", date_from: "", date_to: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const [isComposeOpen, setIsComposeOpen] = useState(() => Boolean(tenantIdFromQuery));
  const [compose, setCompose] = useState({ tenant_id: tenantIdFromQuery ?? "", message_type: "sms", content: "" });

  const { data, isLoading } = useGetCommunicationsQuery(appliedFilters);
  const { data: tenantsData } = useGetTenantsQuery();
  const [sendCommunication, { isLoading: isSending }] = useSendCommunicationMutation();
  const [resend] = useResendCommunicationMutation();

  const logs = toRows(data);
  const tenants = toRows(tenantsData);

  const totals = {
    sent: data?.total_sent ?? logs.length,
    delivered: data?.total_delivered ?? logs.filter((l) => l.status === "delivered").length,
    failed: data?.total_failed ?? logs.filter((l) => l.status === "failed").length,
  };

  const handleSend = async (e) => {
    e.preventDefault();
    try {
      await sendCommunication(compose).unwrap();
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
        subtitle="Every message sent through SahilPay"
        actions={
          tab === "log" && (
            <Button leftIcon={<Send className="h-4 w-4" />} onClick={() => setIsComposeOpen(true)}>
              Send message
            </Button>
          )
        }
      />

      <Tabs
        tabs={[
          { key: "log", label: "Log" },
          { key: "templates", label: "Templates" },
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
              onApply={() => setAppliedFilters(filters)}
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

            <div className="flex-1">
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
