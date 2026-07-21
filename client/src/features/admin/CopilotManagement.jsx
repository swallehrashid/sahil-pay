import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Smartphone, MessageSquareWarning, AlertTriangle, Wallet, Activity, Percent,
  Trash2, Lock, Unlock, Plus, FlaskConical, UploadCloud, Copy, RefreshCw,
} from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import Tabs from "@/components/ui/Tabs";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import StatusBadge from "@/components/ui/StatusBadge";
import Modal from "@/components/ui/Modal";
import Drawer from "@/components/ui/Drawer";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import EmptyState from "@/components/ui/EmptyState";
import FileUpload from "@/components/ui/FileUpload";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { env } from "@/config/env";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetCopilotOverviewQuery,
  useGetCopilotDevicesQuery,
  useRevokeCopilotDeviceAdminMutation,
  useGetCopilotLandlordPostureQuery,
  useSetCopilotLandlordLockMutation,
  useGetCopilotMessagesAdminQuery,
  useGetCopilotTemplatesQuery,
  useCreateCopilotTemplateMutation,
  useUpdateCopilotTemplateMutation,
  useDeleteCopilotTemplateMutation,
  useTestCopilotTemplateMutation,
  useGetCopilotUnparsedQuery,
  useRetryCopilotMessageMutation,
  useRetryAllCopilotMessagesMutation,
  useGetCopilotReleasesQuery,
  useCreateCopilotReleaseMutation,
} from "./adminCopilotApiSlice";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "devices", label: "Devices" },
  { key: "landlords", label: "Landlords" },
  { key: "messages", label: "Messages" },
  { key: "templates", label: "Templates" },
  { key: "releases", label: "Releases" },
];

// COPILOT_PLATFORM_SPEC.md §7-8 — the admin's total control surface over every
// landlord's Co-pilot SMS forwarder: fleet health, per-landlord kill switch,
// the global ingest/audit log, the parser-template registry (onboard a new
// bank without touching code), and APK release management.
export default function CopilotManagement() {
  const [searchParams] = useSearchParams();
  const tabFromQuery = searchParams.get("tab");
  const [tab, setTab] = useState(TABS.some((t) => t.key === tabFromQuery) ? tabFromQuery : "overview");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Co-pilot"
        subtitle="SMS-forwarder fleet, ingest log, parser templates and app releases"
        breadcrumbs={[{ label: "Admin", to: ADMIN_ROUTES.dashboard }, { label: "Co-pilot" }]}
      />
      <Tabs tabs={TABS} activeKey={tab} onChange={setTab} />
      {tab === "overview" && <OverviewTab />}
      {tab === "devices" && <DevicesTab />}
      {tab === "landlords" && <LandlordsTab />}
      {tab === "messages" && <MessagesTab />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "releases" && <ReleasesTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------
function OverviewTab() {
  const { data, isLoading } = useGetCopilotOverviewQuery();

  const columns = [
    { key: "created_at", header: "Time", render: (r) => formatDateTime(r.created_at) },
    { key: "sender_id", header: "Sender", render: (r) => <Badge color="third">{r.sender_id}</Badge> },
    { key: "parsed_amount", header: "Amount", render: (r) => (r.parsed_amount != null ? formatCurrency(r.parsed_amount) : "—") },
    { key: "parse_status", header: "Parse", render: (r) => <StatusBadge status={r.parse_status} /> },
    { key: "match_status", header: "Match", render: (r) => <StatusBadge status={r.match_status} /> },
  ];

  if (isLoading) return <SkeletonStatCards count={6} />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <SummaryCard label="Devices active" value={data?.devices_active ?? 0} icon={<Smartphone className="h-5 w-5" />} accent="third" />
        <SummaryCard label="Devices stale (48h)" value={data?.devices_stale ?? 0} icon={<AlertTriangle className="h-5 w-5" />} />
        <SummaryCard label="Messages (7d)" value={data?.messages_7d ?? 0} icon={<Activity className="h-5 w-5" />} accent="third" />
        <SummaryCard label="Parse failure rate" value={`${data?.parse_failure_pct ?? 0}%`} icon={<Percent className="h-5 w-5" />} />
        <SummaryCard label="Unmatched open" value={data?.unmatched_open ?? 0} icon={<MessageSquareWarning className="h-5 w-5" />} accent="third" />
        <SummaryCard label="KES via Co-pilot (7d)" value={formatCurrency(data?.payments_7d?.sum ?? 0)} icon={<Wallet className="h-5 w-5" />} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">Landlords with Co-pilot enabled</p>
          <p className="mt-2 text-2xl font-light text-white">{data?.landlords_enabled ?? 0}</p>
        </div>
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">Messages today</p>
          <p className="mt-2 text-2xl font-light text-white">{data?.messages_today ?? 0}</p>
        </div>
        <div className="glass p-6">
          <p className="text-sm font-medium text-white/50">Unparsed backlog</p>
          <p className="mt-2 text-2xl font-light text-white">{data?.unparsed_open ?? 0}</p>
          <p className="mt-1 text-xs text-white/40">Needs a parser template — see the Templates tab</p>
        </div>
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Latest messages</h3>
        <ResponsiveTable columns={columns} rows={data?.latest_messages ?? []} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
function DevicesTab() {
  const [filters, setFilters] = useState({ status: "" });
  const { data, isLoading } = useGetCopilotDevicesQuery(filters);
  const [revoke] = useRevokeCopilotDeviceAdminMutation();
  const [pendingRevoke, setPendingRevoke] = useState(null);

  const rows = toRows(data);

  const handleRevoke = async () => {
    try {
      await revoke(pendingRevoke.id).unwrap();
      toast("Device revoked.", { type: "success" });
    } catch {
      toast("Could not revoke the device.", { type: "error" });
    } finally {
      setPendingRevoke(null);
    }
  };

  const columns = [
    { key: "landlord_name", header: "Landlord" },
    { key: "device_name", header: "Device" },
    { key: "device_model", header: "Model", render: (r) => r.device_model ?? "—" },
    { key: "app_version", header: "Version", render: (r) => r.app_version ?? "—" },
    {
      key: "sender_ids",
      header: "Senders",
      render: (r) => (r.sender_ids?.length ? r.sender_ids.join(", ") : "—"),
    },
    { key: "last_seen_at", header: "Last seen", render: (r) => formatDateTime(r.last_seen_at) },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <div className="space-y-4">
      <div className="glass flex flex-wrap items-end gap-4 p-4">
        <Select
          label="Status"
          value={filters.status}
          onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
          options={[{ value: "", label: "All" }, { value: "active", label: "Active" }, { value: "revoked", label: "Revoked" }]}
        />
      </div>
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowActions={(row) =>
          row.status === "active" && (
            <Button variant="ghost" size="sm" leftIcon={<Trash2 className="h-4 w-4" />} onClick={() => setPendingRevoke(row)}>
              Revoke
            </Button>
          )
        }
      />
      <ConfirmDialog
        isOpen={Boolean(pendingRevoke)}
        onClose={() => setPendingRevoke(null)}
        onConfirm={handleRevoke}
        title="Revoke this device?"
        description={`"${pendingRevoke?.device_name}" (${pendingRevoke?.landlord_name}) will stop forwarding immediately.`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Landlords
// ---------------------------------------------------------------------------
function LandlordsTab() {
  const { data, isLoading } = useGetCopilotLandlordPostureQuery();
  const [setLock] = useSetCopilotLandlordLockMutation();
  const [pendingLock, setPendingLock] = useState(null);

  const rows = toRows(data);

  const handleConfirmLock = async () => {
    try {
      await setLock({ id: pendingLock.landlord_id, admin_locked: !pendingLock.admin_locked }).unwrap();
      toast(pendingLock.admin_locked ? "Co-pilot unlocked." : "Co-pilot locked.", { type: "success" });
    } catch {
      toast("Could not update this landlord's Co-pilot lock.", { type: "error" });
    } finally {
      setPendingLock(null);
    }
  };

  const columns = [
    { key: "company_name", header: "Landlord" },
    { key: "enabled", header: "Enabled", render: (r) => (r.enabled ? <StatusBadge status="active" /> : <StatusBadge status="revoked" />) },
    { key: "auto_allocate", header: "Mode", render: (r) => (r.auto_allocate ? "Auto-allocate" : "Review first") },
    { key: "device_count", header: "Devices" },
    { key: "last_message_at", header: "Last message", render: (r) => formatDateTime(r.last_message_at) },
    { key: "unmatched_open", header: "Unmatched" },
    {
      key: "admin_locked",
      header: "Admin lock",
      render: (r) =>
        r.admin_locked ? <StatusBadge status="revoked" /> : <span className="text-white/40">—</span>,
    },
  ];

  return (
    <div className="space-y-4">
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        rowActions={(row) => (
          <Button
            variant="ghost"
            size="sm"
            leftIcon={row.admin_locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
            onClick={() => setPendingLock(row)}
          >
            {row.admin_locked ? "Unlock" : "Lock"}
          </Button>
        )}
      />
      <ConfirmDialog
        isOpen={Boolean(pendingLock)}
        onClose={() => setPendingLock(null)}
        onConfirm={handleConfirmLock}
        title={pendingLock?.admin_locked ? "Unlock Co-pilot?" : "Lock Co-pilot?"}
        description={
          pendingLock?.admin_locked
            ? `${pendingLock?.company_name} will be able to use Co-pilot again once they re-enable it.`
            : `This immediately stops payment ingestion for ${pendingLock?.company_name}.`
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messages (global ingest log)
// ---------------------------------------------------------------------------
function MessagesTab() {
  const pg = usePagination(20);
  const [filters, setFilters] = useState({ sender_id: "", parse_status: "", match_status: "" });
  const [appliedFilters, setAppliedFilters] = useState({});
  const { data, isLoading } = useGetCopilotMessagesAdminQuery({ ...appliedFilters, ...pg.params });
  const [expanded, setExpanded] = useState(null);

  const rows = toRows(data);

  const columns = [
    { key: "created_at", header: "Time", render: (r) => formatDateTime(r.created_at) },
    { key: "landlord_id", header: "Landlord ID" },
    { key: "sender_id", header: "Sender", render: (r) => <Badge color="third">{r.sender_id}</Badge> },
    { key: "parsed_amount", header: "Amount", render: (r) => (r.parsed_amount != null ? formatCurrency(r.parsed_amount) : "—") },
    { key: "parse_status", header: "Parse", render: (r) => <StatusBadge status={r.parse_status} /> },
    { key: "match_status", header: "Match", render: (r) => <StatusBadge status={r.match_status} /> },
  ];

  return (
    <div className="space-y-4">
      <div className="glass flex flex-wrap items-end gap-4 p-4">
        <Input
          label="Sender ID"
          value={filters.sender_id}
          onChange={(e) => setFilters((f) => ({ ...f, sender_id: e.target.value }))}
          placeholder="e.g. MPESA"
        />
        <Select
          label="Parse status"
          value={filters.parse_status}
          onChange={(e) => setFilters((f) => ({ ...f, parse_status: e.target.value }))}
          options={[
            { value: "", label: "All" },
            { value: "parsed", label: "Parsed" },
            { value: "unparsed", label: "Unparsed" },
            { value: "duplicate", label: "Duplicate" },
            { value: "rejected", label: "Rejected" },
          ]}
        />
        <Select
          label="Match status"
          value={filters.match_status}
          onChange={(e) => setFilters((f) => ({ ...f, match_status: e.target.value }))}
          options={[
            { value: "", label: "All" },
            { value: "matched", label: "Matched" },
            { value: "unmatched", label: "Unmatched" },
            { value: "n_a", label: "N/A" },
          ]}
        />
        <Button
          variant="ghost"
          onClick={() => {
            setAppliedFilters(filters);
            pg.reset();
          }}
        >
          Apply
        </Button>
      </div>

      <ResponsiveTable columns={columns} rows={rows} isLoading={isLoading} onRowClick={setExpanded} />
      <Pagination page={pg.page} perPage={pg.perPage} total={data?.total ?? 0} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />

      <Modal isOpen={Boolean(expanded)} onClose={() => setExpanded(null)} title="Co-pilot message" size="lg">
        {expanded && (
          <div className="space-y-3 text-sm">
            <div className="glass p-4">
              <p className="mb-1 text-white/40">Raw SMS</p>
              <p className="whitespace-pre-wrap text-white/90">{expanded.raw_text}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><p className="text-white/40">Parsed amount</p><p className="text-white">{expanded.parsed_amount != null ? formatCurrency(expanded.parsed_amount) : "—"}</p></div>
              <div><p className="text-white/40">Parsed ref</p><p className="text-white">{expanded.parsed_ref ?? "—"}</p></div>
              <div><p className="text-white/40">Parsed name</p><p className="text-white">{expanded.parsed_name ?? "—"}</p></div>
              <div><p className="text-white/40">Parsed account</p><p className="text-white">{expanded.parsed_account ?? "—"}</p></div>
              <div><p className="text-white/40">Parsed phone</p><p className="text-white">{expanded.parsed_phone ?? "—"}</p></div>
              <div><p className="text-white/40">Tenant ID</p><p className="text-white">{expanded.tenant_id ?? "—"}</p></div>
              <div><p className="text-white/40">Payment ID</p><p className="text-white">{expanded.payment_id ?? "—"}</p></div>
              <div><p className="text-white/40">Error</p><p className="text-white">{expanded.error_reason ?? "—"}</p></div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Templates (+ Unparsed queue)
// ---------------------------------------------------------------------------
const TEMPLATE_PLACEHOLDERS = ["amount", "ref", "name", "account", "phone", "date", "time", "*"];

function TemplatesTab() {
  const [subTab, setSubTab] = useState("templates");
  const [editing, setEditing] = useState(null); // null = closed, {} = new, {...} = edit/prefill

  return (
    <div className="space-y-4">
      <Tabs
        tabs={[{ key: "templates", label: "Templates" }, { key: "unparsed", label: "Unparsed queue" }]}
        activeKey={subTab}
        onChange={setSubTab}
      />
      {subTab === "templates" ? (
        <TemplatesList onEdit={setEditing} onNew={() => setEditing({})} />
      ) : (
        <UnparsedQueue onCreateTemplate={setEditing} />
      )}
      <TemplateDrawer template={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function TemplatesList({ onEdit, onNew }) {
  const { data, isLoading } = useGetCopilotTemplatesQuery();
  const [deleteTemplate] = useDeleteCopilotTemplateMutation();
  const [pendingDelete, setPendingDelete] = useState(null);

  const rows = toRows(data);

  const handleDelete = async () => {
    try {
      const res = await deleteTemplate(pendingDelete.id).unwrap();
      toast(res?.message || "Template removed.", { type: "success" });
    } catch {
      toast("Could not remove this template.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "sender_id", header: "Sender", render: (r) => <Badge color="third">{r.sender_id}</Badge> },
    { key: "name", header: "Name" },
    { key: "priority", header: "Priority" },
    { key: "is_active", header: "Active", render: (r) => (r.is_active ? <StatusBadge status="active" /> : <StatusBadge status="revoked" />) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button leftIcon={<Plus className="h-4 w-4" />} onClick={onNew}>New template</Button>
      </div>
      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={onEdit}
        rowActions={(row) => (
          <Button variant="ghost" size="sm" leftIcon={<Trash2 className="h-4 w-4" />} onClick={() => setPendingDelete(row)}>
            Delete
          </Button>
        )}
      />
      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Remove this template?"
        description={`"${pendingDelete?.name}" — if it's referenced by ingest history it will be deactivated instead of deleted.`}
      />
    </div>
  );
}

function UnparsedQueue({ onCreateTemplate }) {
  const { data, isLoading } = useGetCopilotUnparsedQuery();
  const [retryAll, { isLoading: isRetrying }] = useRetryAllCopilotMessagesMutation();
  const [retryOne, { isLoading: isRetryingOne }] = useRetryCopilotMessageMutation();

  const senders = data?.senders ?? [];

  if (isLoading) return <SkeletonStatCards count={3} />;
  if (!senders.length) {
    return <EmptyState title="Nothing unparsed" description="Every forwarded SMS matched a parser template." />;
  }

  const handleRetryAll = async (senderId) => {
    try {
      const res = await retryAll(senderId).unwrap();
      toast(`Retried ${res.retried} message(s) — ${res.now_resolved} now resolved.`, { type: "success" });
    } catch {
      toast("Could not retry this sender's queue.", { type: "error" });
    }
  };

  const handleRetryOne = async (message) => {
    try {
      const res = await retryOne(message.id).unwrap();
      toast(
        res.parse_status === "unparsed" ? "Still no template matches this message." : `Now ${res.parse_status}.`,
        { type: res.parse_status === "unparsed" ? "error" : "success" }
      );
    } catch {
      toast("Could not retry this message.", { type: "error" });
    }
  };

  return (
    <div className="space-y-4">
      {senders.map((s) => (
        <div key={s.sender_id} className="glass space-y-3 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Badge color="secondary">{s.sender_id}</Badge>
              <span className="text-sm text-white/60">{s.count} unparsed message(s)</span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                leftIcon={<Plus className="h-4 w-4" />}
                onClick={() => onCreateTemplate({
                  sender_id: s.sender_id,
                  sample_text: s.examples[0]?.raw_text ?? "",
                  template_text: "",
                  name: `${s.sender_id} template`,
                  priority: 100,
                  is_active: true,
                })}
              >
                Create template
              </Button>
              <Button variant="ghost" size="sm" leftIcon={<RefreshCw className="h-4 w-4" />} isLoading={isRetrying} onClick={() => handleRetryAll(s.sender_id)}>
                Retry all
              </Button>
            </div>
          </div>
          <div className="space-y-2">
            {s.examples.map((ex) => (
              <div key={ex.id} className="flex items-start justify-between gap-3 rounded-xl bg-white/5 p-3 text-xs text-white/70">
                <div>
                  <p className="mb-1 text-white/40">{formatDateTime(ex.created_at)}</p>
                  <p className="whitespace-pre-wrap">{ex.raw_text}</p>
                </div>
                <Button variant="ghost" size="sm" isLoading={isRetryingOne} onClick={() => handleRetryOne(ex)}>
                  Retry
                </Button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function TemplateDrawer({ template, onClose }) {
  const [form, setForm] = useState(null);
  const [prevTemplate, setPrevTemplate] = useState(undefined);
  const [testResult, setTestResult] = useState(null);
  // §1.5.2 — sample_text (the raw, untouched SMS the admin pastes in) is the
  // authoring surface. workingCopy starts as a COPY of it and is what
  // placeholder clicks progressively rewrite in place; template_text is
  // always derived from workingCopy. sample_text itself is never mutated by
  // a placeholder click, so it stays the true ground truth "Live test" (and
  // the server's own save-time validation) matches template_text against.
  const [workingCopy, setWorkingCopy] = useState("");
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const [rawEditMode, setRawEditMode] = useState(false);
  const sampleRef = useRef(null);
  const [createTemplate, { isLoading: isCreating }] = useCreateCopilotTemplateMutation();
  const [updateTemplate, { isLoading: isUpdating }] = useUpdateCopilotTemplateMutation();
  const [testTemplate, { isLoading: isTesting }] = useTestCopilotTemplateMutation();

  if (template !== prevTemplate) {
    setPrevTemplate(template);
    const nextForm =
      template && Object.keys(template).length
        ? { name: "", sender_id: "", template_text: "", sample_text: "", priority: 100, is_active: true, ...template }
        : template
        ? { name: "", sender_id: "", template_text: "", sample_text: "", priority: 100, is_active: true }
        : null;
    setForm(nextForm);
    // Seed the working copy: prefer an existing template_text (editing a
    // saved template) so re-opening doesn't discard prior authoring work;
    // otherwise start from the raw sample, unconverted.
    setWorkingCopy(nextForm?.template_text || nextForm?.sample_text || "");
    setSelection({ start: 0, end: 0 });
    setRawEditMode(false);
    setTestResult(null);
  }

  // Auto-run live test whenever the derived template_text changes (§1.5.2
  // step 5) so authoring mistakes (literal date/time/balance left in) surface
  // immediately instead of only on manual click.
  useEffect(() => {
    if (!form) return undefined;
    const templateText = (form.template_text ?? "").trim();
    const sampleText = (form.sample_text ?? "").trim();
    const handle = setTimeout(() => {
      if (!templateText || !sampleText) {
        setTestResult(null);
        return;
      }
      testTemplate({ template_text: templateText, sample_sms: form.sample_text }).unwrap()
        .then(setTestResult)
        .catch(() => setTestResult({ ok: false, error: "Could not run the test." }));
    }, 400); // debounce — avoid a request per keystroke while raw-editing
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form?.template_text, form?.sample_text]);

  if (!form) return null;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const hasSelection = selection.end > selection.start;

  const trackSelection = (e) => {
    const el = e.target;
    setSelection({ start: el.selectionStart ?? 0, end: el.selectionEnd ?? 0 });
  };

  // Sample SMS changed (retyped/pasted a different message) — reset the
  // working copy to match so old placeholder placements from a previous
  // message don't linger against new text.
  const handleSampleChange = (e) => {
    const value = e.target.value;
    setForm((f) => ({ ...f, sample_text: value, template_text: value }));
    setWorkingCopy(value);
    setSelection({ start: 0, end: 0 });
  };

  // §1.5.2 step 2 — replace the selected span of the working copy with a
  // placeholder token, leaving every other character literal, then re-derive
  // template_text from the result (step 3).
  const placeholderize = (ph) => {
    if (!hasSelection) return;
    const { start, end } = selection;
    const next = workingCopy.slice(0, start) + `{${ph}}` + workingCopy.slice(end);
    setWorkingCopy(next);
    setForm((f) => ({ ...f, template_text: next }));
    // Put the caret right after the inserted token so a second placeholder
    // pick doesn't require re-selecting from scratch.
    const caret = start + `{${ph}}`.length;
    setSelection({ start: caret, end: caret });
    requestAnimationFrame(() => {
      sampleRef.current?.focus();
      sampleRef.current?.setSelectionRange(caret, caret);
    });
  };

  const handleWorkingCopyChange = (e) => {
    const value = e.target.value;
    setWorkingCopy(value);
    setForm((f) => ({ ...f, template_text: value }));
  };

  const resetWorkingCopy = () => {
    setWorkingCopy(form.sample_text ?? "");
    setForm((f) => ({ ...f, template_text: f.sample_text ?? "" }));
    setSelection({ start: 0, end: 0 });
  };

  const handleTest = async () => {
    try {
      const result = await testTemplate({ template_text: form.template_text, sample_sms: form.sample_text }).unwrap();
      setTestResult(result);
    } catch {
      setTestResult({ ok: false, error: "Could not run the test." });
    }
  };

  const handleSave = async () => {
    try {
      if (form.id) {
        await updateTemplate({ id: form.id, ...form }).unwrap();
        toast("Template updated.", { type: "success" });
      } else {
        await createTemplate(form).unwrap();
        toast("Template created.", { type: "success" });
      }
      onClose();
    } catch (err) {
      toast(err?.data?.error || "Could not save this template.", { type: "error" });
    }
  };

  return (
    <Drawer
      isOpen={Boolean(template)}
      onClose={onClose}
      title={form.id ? "Edit template" : "New parser template"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} isLoading={isCreating || isUpdating}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Sender ID" value={form.sender_id ?? ""} onChange={set("sender_id")} placeholder="e.g. KCB" required />
          <Input label="Priority" type="number" value={form.priority ?? 100} onChange={set("priority")} />
        </div>
        <Input label="Name" value={form.name ?? ""} onChange={set("name")} placeholder="e.g. KCB credit alert" required />

        <Textarea
          label="Sample SMS"
          rows={3}
          value={form.sample_text ?? ""}
          onChange={handleSampleChange}
          placeholder="Paste the real bank SMS here"
          hint="The exact message this template must match. Editing this resets the authoring box below to match it."
        />

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <p className="text-sm font-medium text-white/70">Build the template</p>
            <button
              type="button"
              onClick={resetWorkingCopy}
              className="text-xs text-white/40 underline decoration-dotted hover:text-white/70"
            >
              Reset to sample
            </button>
          </div>
          <p className="mb-1.5 text-sm text-white/50">
            Select the part of the message that changes each time (amount, name, phone, date...) and click the
            matching placeholder. Leave everything else as-is — that's the fixed wording this template will match on.
          </p>
          <Textarea
            ref={sampleRef}
            rows={4}
            value={workingCopy}
            onChange={handleWorkingCopyChange}
            onSelect={trackSelection}
            onMouseUp={trackSelection}
            onKeyUp={trackSelection}
            placeholder="Starts as a copy of the sample SMS above — select spans here and click a placeholder"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {TEMPLATE_PLACEHOLDERS.map((ph) => (
              <button
                key={ph}
                type="button"
                disabled={!hasSelection}
                title={hasSelection ? `Replace the selected text with {${ph}}` : "Select a span of text above first"}
                onClick={() => placeholderize(ph)}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  hasSelection
                    ? "border-white/15 bg-white/5 text-white/70 hover:border-secondary hover:text-white"
                    : "cursor-not-allowed border-white/5 bg-white/[0.02] text-white/25"
                }`}
              >
                {`{${ph}}`}
              </button>
            ))}
          </div>
          {!hasSelection && (
            <p className="mt-1 text-xs text-white/30">Select text above to enable these.</p>
          )}
        </div>

        <div>
          <button
            type="button"
            onClick={() => setRawEditMode((v) => !v)}
            className="mb-1.5 text-xs font-medium text-white/50 underline decoration-dotted hover:text-white/80"
          >
            {rawEditMode ? "Hide raw template text" : "Edit raw template text"}
          </button>
          {rawEditMode ? (
            <Textarea
              label="Template (derived — hand-edit only if you know what you're doing)"
              rows={4}
              value={form.template_text ?? ""}
              onChange={(e) => {
                set("template_text")(e);
                setWorkingCopy(e.target.value);
              }}
              placeholder="{ref} Confirmed. Ksh{amount} received from {name} {phone}"
              required
            />
          ) : (
            <pre className="overflow-x-auto rounded-lg bg-white/5 p-3 text-xs text-white/60">
              {form.template_text || "—"}
            </pre>
          )}
        </div>

        <Checkbox
          label="Active"
          checked={Boolean(form.is_active)}
          onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
        />

        <div className="glass space-y-2 p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-white/70">Live test</p>
            <Button variant="ghost" size="sm" leftIcon={<FlaskConical className="h-4 w-4" />} isLoading={isTesting} onClick={handleTest}>
              Test
            </Button>
          </div>
          {testResult && (
            testResult.ok ? (
              <pre className="overflow-x-auto rounded-lg bg-emerald-500/10 p-3 text-xs text-emerald-300">
                {JSON.stringify(testResult.fields, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-secondary-300">{testResult.error}</p>
            )
          )}
        </div>
      </div>
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Releases
// ---------------------------------------------------------------------------
function ReleasesTab() {
  const { data, isLoading } = useGetCopilotReleasesQuery();
  const [createRelease, { isLoading: isUploading }] = useCreateCopilotReleaseMutation();
  const [form, setForm] = useState({ version_name: "", version_code: "", release_notes: "", is_latest: true, min_supported_version_code: "" });
  const [apk, setApk] = useState(null);

  const downloadUrl = `${env.apiBaseUrl}/copilot/app/download`;

  const copyLink = () => {
    navigator.clipboard.writeText(downloadUrl);
    toast("Download link copied.", { type: "success" });
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!apk) {
      toast("Choose an APK file first.", { type: "error" });
      return;
    }
    const body = new FormData();
    body.append("file", apk);
    body.append("version_name", form.version_name);
    body.append("version_code", form.version_code);
    body.append("release_notes", form.release_notes);
    body.append("is_latest", form.is_latest ? "true" : "false");
    if (form.min_supported_version_code) body.append("min_supported_version_code", form.min_supported_version_code);

    try {
      await createRelease(body).unwrap();
      toast("Release uploaded.", { type: "success" });
      setForm({ version_name: "", version_code: "", release_notes: "", is_latest: true, min_supported_version_code: "" });
      setApk(null);
    } catch (err) {
      toast(err?.data?.error || "Could not upload this release.", { type: "error" });
    }
  };

  const columns = [
    { key: "version_name", header: "Version" },
    { key: "version_code", header: "Code" },
    { key: "is_latest", header: "Latest", render: (r) => (r.is_latest ? <StatusBadge status="active" /> : "—") },
    { key: "min_supported_version_code", header: "Min supported", render: (r) => r.min_supported_version_code ?? "—" },
    { key: "created_at", header: "Uploaded", render: (r) => formatDateTime(r.created_at) },
  ];

  return (
    <div className="space-y-6">
      <div className="glass flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-sm font-medium text-white/70">Public download link</p>
          <p className="text-xs text-white/40">Send this one link to clients — it always resolves to the latest release.</p>
        </div>
        <div className="flex items-center gap-2">
          <code className="rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/70">{downloadUrl}</code>
          <Button variant="ghost" size="sm" leftIcon={<Copy className="h-4 w-4" />} onClick={copyLink}>Copy</Button>
        </div>
      </div>

      <form onSubmit={handleUpload} className="glass space-y-4 p-6">
        <h3 className="text-base font-medium text-white">Upload a new release</h3>
        <FileUpload label="APK file" accept=".apk" value={apk} onChange={setApk} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Input label="Version name" placeholder="1.0.0" value={form.version_name} onChange={(e) => setForm((f) => ({ ...f, version_name: e.target.value }))} required />
          <Input label="Version code" type="number" value={form.version_code} onChange={(e) => setForm((f) => ({ ...f, version_code: e.target.value }))} required />
          <Input label="Min supported code" type="number" value={form.min_supported_version_code} onChange={(e) => setForm((f) => ({ ...f, min_supported_version_code: e.target.value }))} />
        </div>
        <Textarea label="Release notes" rows={3} value={form.release_notes} onChange={(e) => setForm((f) => ({ ...f, release_notes: e.target.value }))} />
        <Checkbox label="Mark as latest" checked={form.is_latest} onChange={(e) => setForm((f) => ({ ...f, is_latest: e.target.checked }))} />
        <div className="flex justify-end">
          <Button type="submit" leftIcon={<UploadCloud className="h-4 w-4" />} isLoading={isUploading}>Upload release</Button>
        </div>
      </form>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Release history</h3>
        <ResponsiveTable columns={columns} rows={toRows(data)} isLoading={isLoading} />
      </div>
    </div>
  );
}
