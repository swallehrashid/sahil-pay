import { useState } from "react";
import { Smartphone } from "lucide-react";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import FilterPanel from "@/components/tables/FilterPanel";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import EmptyState from "@/components/ui/EmptyState";
import Pagination from "@/components/ui/Pagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import {
  useGetCopilotInboxMessagesQuery,
  useGetCopilotInboxMessageQuery,
} from "./copilotInboxApiSlice";
import { useGetPaymentQuery } from "./paymentApiSlice";
import ConfirmPaymentModal from "./ConfirmPaymentModal";

// COPILOT_LANDLORD_INBOX_SPEC.md §4 — the landlord's own Co-Pilot inbox,
// nested as a tab on the Payments page. Read-only: mutation (retry/edit)
// stays admin-only per §3.4; a pending payment is actioned through the
// existing payment review flow (ConfirmPaymentModal), not duplicated here.

// §4.2 status-chip mapping table.
function statusChip(row) {
  if (row.parse_status === "parsed" && row.match_status === "matched") {
    if (row.payment?.status === "confirmed") return { label: "Allocated", color: "emerald" };
    if (row.payment?.status === "pending") return { label: "Needs review", color: "amber" };
  }
  if (row.parse_status === "parsed" && row.match_status === "unmatched") {
    return { label: "No tenant match", color: "amber" };
  }
  if (row.parse_status === "unparsed") return { label: "Not recognised", color: "white" };
  if (row.parse_status === "duplicate") return { label: "Duplicate", color: "white" };
  if (row.parse_status === "rejected") return { label: "Rejected", color: "amber" };
  return { label: row.parse_status ?? "—", color: "white" };
}

function StatusChip({ row }) {
  const { label, color } = statusChip(row);
  // "danger"/rejected reads red — Badge has no dedicated rose tone, borrow amber-adjacent
  // styling via a direct class override only for that one case to match the spec's "danger" tone.
  if (color === "amber" && row.parse_status === "rejected") {
    return (
      <span className="inline-flex items-center rounded-full border border-rose-500/30 bg-rose-500/15 px-2.5 py-1 text-xs font-medium text-rose-300">
        {label}
      </span>
    );
  }
  return <Badge color={color}>{label}</Badge>;
}

export default function CopilotInboxTab() {
  const pg = usePagination(25);
  const [filters, setFilters] = useState({ status: "all", match: "all", q: "" });
  const [appliedFilters, setAppliedFilters] = useState({ status: "all", match: "all", q: "" });
  const { data, isLoading } = useGetCopilotInboxMessagesQuery({ ...appliedFilters, ...pg.params });
  const [viewingId, setViewingId] = useState(null);

  const rows = toRows(data);

  const columns = [
    { key: "received", header: "Received", render: (r) => formatDateTime(r.sms_received_at || r.created_at) },
    { key: "sender_id", header: "Sender", render: (r) => <Badge color="third">{r.sender_id}</Badge> },
    { key: "parsed_amount", header: "Amount", render: (r) => (r.parsed_amount != null ? formatCurrency(r.parsed_amount) : "—") },
    { key: "parsed_account", header: "Account", render: (r) => r.parsed_account ?? "—" },
    { key: "parsed_ref", header: "Reference", render: (r) => r.parsed_ref ?? "—" },
    {
      key: "tenant",
      header: "Tenant",
      render: (r) =>
        r.tenant ? (
          <span>{r.tenant.name}{r.tenant.unit ? ` · ${r.tenant.unit}` : ""}</span>
        ) : (
          <Badge color="amber">Unmatched</Badge>
        ),
    },
    { key: "status", header: "Status", render: (r) => <StatusChip row={r} /> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-6 lg:flex-row">
        <FilterPanel
          onApply={() => { setAppliedFilters(filters); pg.reset(); }}
          onReset={() => {
            setFilters({ status: "all", match: "all", q: "" });
            setAppliedFilters({ status: "all", match: "all", q: "" });
            pg.reset();
          }}
        >
          <Select
            label="Status"
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            options={[
              { value: "all", label: "All" },
              { value: "parsed", label: "Parsed" },
              { value: "unparsed", label: "Not recognised" },
              { value: "duplicate", label: "Duplicate" },
              { value: "rejected", label: "Rejected" },
            ]}
          />
          <Select
            label="Match"
            value={filters.match}
            onChange={(e) => setFilters((f) => ({ ...f, match: e.target.value }))}
            options={[
              { value: "all", label: "All" },
              { value: "matched", label: "Matched" },
              { value: "unmatched", label: "Unmatched" },
            ]}
          />
          <Input
            label="Search"
            placeholder="Name, reference, or account"
            value={filters.q}
            onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
          />
        </FilterPanel>

        <div className="min-w-0 flex-1">
          <ResponsiveTable
            columns={columns}
            rows={rows}
            isLoading={isLoading}
            onRowClick={(row) => setViewingId(row.id)}
            emptyState={
              <EmptyState
                icon={<Smartphone className="h-6 w-6" />}
                title="No Co-Pilot messages yet"
                description="Payment confirmation SMSs forwarded by your paired phone will show up here."
              />
            }
            rowActions={(row) => (
              <Button variant="ghost" size="sm" onClick={() => setViewingId(row.id)}>
                View
              </Button>
            )}
          />
          <Pagination page={pg.page} perPage={pg.perPage} total={data?.total ?? 0} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
        </div>
      </div>

      <CopilotMessageDetailModal messageId={viewingId} onClose={() => setViewingId(null)} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// §4.3 — detail modal
// ---------------------------------------------------------------------------
function CopilotMessageDetailModal({ messageId, onClose }) {
  const { data: msg, isLoading } = useGetCopilotInboxMessageQuery(messageId, { skip: !messageId });
  const [reviewPaymentId, setReviewPaymentId] = useState(null);

  return (
    <>
      <Modal isOpen={Boolean(messageId)} onClose={onClose} title="Co-Pilot message" size="lg">
        {isLoading || !msg ? (
          <p className="text-sm text-white/50">Loading…</p>
        ) : (
          <div className="space-y-4 text-sm">
            <div className="glass p-4">
              <p className="mb-1 text-white/40">Raw SMS</p>
              {msg.raw_text_redacted ? (
                <p className="text-white/50">
                  This message wasn't recognised as a payment, so its contents weren't stored.
                </p>
              ) : (
                <p className="whitespace-pre-wrap font-mono text-xs text-white/90">{msg.raw_text}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Amount" value={msg.parsed_amount != null ? formatCurrency(msg.parsed_amount) : "—"} />
              <Field label="Reference" value={msg.parsed_ref ?? "—"} />
              <Field label="Name" value={msg.parsed_name ?? "—"} />
              <Field label="Account" value={msg.parsed_account ?? "—"} />
              <Field label="Phone" value={msg.parsed_phone ?? "—"} />
              <Field label="Tenant" value={msg.tenant ? `${msg.tenant.name}${msg.tenant.unit ? ` · ${msg.tenant.unit}` : ""}` : "—"} />
              <Field label="Payment" value={msg.payment ? `${msg.payment.payment_ref} (${msg.payment.status})` : "—"} />
              <Field label="Error" value={msg.error_reason ?? "—"} />
            </div>

            <div className="border-t border-white/10 pt-4">
              {msg.payment?.status === "pending" && (
                <Button onClick={() => setReviewPaymentId(msg.payment.id)}>Review &amp; allocate</Button>
              )}
              {msg.payment?.status === "confirmed" && (
                <Button variant="ghost" onClick={() => setReviewPaymentId(msg.payment.id)}>View payment</Button>
              )}
              {!msg.payment && msg.parse_status === "parsed" && msg.match_status === "unmatched" && (
                <p className="text-xs text-white/50">
                  No tenant matched account <code className="rounded bg-white/10 px-1">{msg.parsed_account ?? "—"}</code>.
                  Check that a tenant's account number matches the one in this message.
                </p>
              )}
              {msg.parse_status === "unparsed" && (
                <p className="text-xs text-white/50">
                  This message format isn't recognised yet. Contact support if this was a rent payment.
                </p>
              )}
            </div>
          </div>
        )}
      </Modal>

      <PaymentReviewBridge paymentId={reviewPaymentId} onClose={() => setReviewPaymentId(null)} />
    </>
  );
}

function Field({ label, value }) {
  return (
    <div>
      <p className="text-white/40">{label}</p>
      <p className="text-white">{value}</p>
    </div>
  );
}

// Loads the full Payment row (ConfirmPaymentModal needs the same shape the
// Payments list/detail endpoints return, not the slim summary embedded in a
// CopilotMessage) and hands off to the EXISTING review flow — §3.4 forbids a
// second allocation path, this only links to the one that already works.
function PaymentReviewBridge({ paymentId, onClose }) {
  const { data: payment } = useGetPaymentQuery(paymentId, { skip: !paymentId });
  if (!paymentId) return null;
  return <ConfirmPaymentModal payment={payment} onClose={onClose} />;
}
