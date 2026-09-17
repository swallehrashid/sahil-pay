import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  FileText, Upload, Check, X, Download, Send, Eye, PenLine, Printer, ClipboardCheck,
  Users, CheckCircle2, ChevronLeft, ChevronRight, ScrollText,
} from "lucide-react";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import Drawer from "@/components/ui/Drawer";
import FileUpload from "@/components/ui/FileUpload";
import SearchInput from "@/components/ui/SearchInput";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { toast } from "@/components/ui/Toast";
import { toRows } from "@/utils/tableAdapters";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile, fetchObjectUrl } from "@/utils/downloadFile";
import { usePermissions } from "@/hooks/usePermissions";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import {
  useGetLeasesQuery,
  useSendLeaseMutation,
  useApproveLeaseMutation,
  useRejectLeaseMutation,
  useUploadLeaseMutation,
  useGetLeaseDocumentOptionsQuery,
  useSendLeasesMutation,
} from "./leaseApiSlice";

// Tenancy agreements — sent, signed, reviewed and filed in one place.
//
// SEND: pick tenants → pick the document (Sahil Pay standard, your own written
// template, or an uploaded lease) → send. Every tenant is notified in the
// portal, by SMS and by email.
// SIGN: the tenant signs in the portal, or prints, signs by hand and uploads the
// pages. Either way it lands here under "Needs your review".
// REVIEW: open it, look at the signature or the scanned pages, approve or return
// with a reason. Both sides then download the same final copy.

const STATUS = {
  draft:      { color: "white",     label: "Draft" },
  sent:       { color: "third",     label: "With tenant" },
  submitted:  { color: "amber",     label: "Needs review" },
  rejected:   { color: "secondary", label: "Returned" },
  approved:   { color: "emerald",   label: "Approved" },
  uploaded:   { color: "emerald",   label: "Signed in office" },
  superseded: { color: "white",     label: "Replaced" },
};

const KIND_LABEL = { standard: "Sahil Pay standard", custom: "Your template", uploaded: "Uploaded document" };

const FILTERS = [
  { key: "", label: "All" },
  { key: "submitted", label: "Needs review" },
  { key: "sent", label: "With tenant" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Returned" },
  { key: "uploaded", label: "Signed in office" },
];

export default function LeasesPage() {
  const { can } = usePermissions();
  const mayEdit = can("leases", "edit") || can("tenants", "edit");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [searchParams] = useSearchParams();
  const [isSendOpen, setSendOpen] = useState(() => searchParams.get("new") === "1");
  const [isUploadOpen, setUploadOpen] = useState(false);
  const [reviewing, setReviewing] = useState(null);

  const params = useMemo(() => (status ? { status } : {}), [status]);
  const { data, isLoading } = useGetLeasesQuery(params);
  const { data: allData } = useGetLeasesQuery({});
  const [sendLease] = useSendLeaseMutation();

  const rows = (data?.items ?? []).filter((r) => {
    if (!search) return true;
    const hay = `${r.tenant_name} ${r.unit_name} ${r.property_name} ${r.title}`.toLowerCase();
    return hay.includes(search.toLowerCase());
  });

  const counts = {
    review: allData?.awaiting_review ?? 0,
    withTenant: allData?.with_tenant ?? 0,
    signed: allData?.signed ?? 0,
  };

  const columns = [
    {
      key: "tenant_name", header: "Tenant",
      render: (r) => (
        <div className="min-w-0">
          <p className="text-white">{r.tenant_name}</p>
          <p className="text-xs text-white/45">{[r.unit_name && `Unit ${r.unit_name}`, r.property_name].filter(Boolean).join(" · ")}</p>
        </div>
      ),
    },
    {
      key: "title", header: "Document",
      render: (r) => (
        <div>
          <p className="text-white/85">{r.title}</p>
          <p className="text-xs text-white/40">{KIND_LABEL[r.document_kind] ?? r.document_kind}</p>
        </div>
      ),
    },
    {
      key: "status", header: "Status",
      render: (r) => {
        const meta = STATUS[r.status] ?? { color: "white", label: r.status };
        return <Badge color={meta.color}>{meta.label}</Badge>;
      },
    },
    { key: "sent_at", header: "Sent", render: (r) => (r.sent_at ? formatDate(r.sent_at) : "—") },
    {
      key: "viewed_at", header: "Opened",
      render: (r) => (r.viewed_at ? formatDate(r.viewed_at) : r.status === "sent" ? <span className="text-white/40">Not yet</span> : "—"),
    },
    {
      key: "signed_at", header: "Signed",
      render: (r) => r.signed_at
        ? <span>{formatDate(r.signed_at)} <span className="text-xs text-white/40">{r.signing_method === "scan" ? "· paper" : "· portal"}</span></span>
        : "—",
    },
    {
      key: "reviewed_at", header: "Approved",
      render: (r) => (r.status === "approved" && r.reviewed_at ? formatDate(r.reviewed_at) : "—"),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lease agreements"
        subtitle="Send leases, review what tenants sign, and keep the final copies"
        actions={mayEdit && (
          <>
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />} onClick={() => setUploadOpen(true)}>
              Record a lease signed in office
            </Button>
            <Button leftIcon={<Send className="h-4 w-4" />} onClick={() => setSendOpen(true)} data-testid="send-lease">
              Send a lease
            </Button>
          </>
        )}
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile icon={ClipboardCheck} label="Need your review" value={counts.review} active={status === "submitted"} onClick={() => setStatus("submitted")} accent="bg-amber-500/20 text-amber-200" />
        <StatTile icon={Users} label="With tenants to sign" value={counts.withTenant} active={status === "sent"} onClick={() => setStatus("sent")} accent="bg-third/30 text-third-100" />
        <StatTile icon={CheckCircle2} label="Signed and on file" value={counts.signed} active={status === "approved"} onClick={() => setStatus("approved")} accent="bg-emerald-500/20 text-emerald-200" />
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1" role="tablist" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              role="tab"
              aria-selected={status === f.key}
              onClick={() => setStatus(f.key)}
              className={clsx(
                "whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm transition-colors",
                status === f.key ? "border-secondary bg-secondary/20 text-white" : "border-white/15 text-white/60 hover:text-white"
              )}
            >
              {f.label}
              {f.key === "submitted" && counts.review > 0 && (
                <span className="ml-1.5 rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-primary-900">{counts.review}</span>
              )}
            </button>
          ))}
        </div>
        <SearchInput value={search} onSearch={setSearch} placeholder="Search tenant, unit, property…" className="lg:w-80" />
      </div>

      {!isLoading && rows.length === 0 ? (
        <EmptyState
          icon={<ScrollText className="h-6 w-6" />}
          title={status ? "Nothing here" : "No lease agreements yet"}
          description={status ? "No leases with this status." : "Send your first lease — tenants sign in their portal or on paper, and you approve it here."}
          action={!status && mayEdit && <Button leftIcon={<Send className="h-4 w-4" />} onClick={() => setSendOpen(true)}>Send a lease</Button>}
        />
      ) : (
        <ResponsiveTable
          columns={columns}
          rows={rows}
          isLoading={isLoading}
          onRowClick={(row) => setReviewing(row)}
          rowActions={(row) => (
            <div className="flex flex-wrap justify-end gap-2" onClick={(e) => e.stopPropagation()}>
              {row.status === "submitted" && (
                <Button size="sm" leftIcon={<Eye className="h-3.5 w-3.5" />} onClick={() => setReviewing(row)}>Review</Button>
              )}
              {row.status === "draft" && mayEdit && (
                <Button size="sm" variant="ghost" leftIcon={<Send className="h-3.5 w-3.5" />}
                        onClick={() => sendLease(row.id).unwrap().then(() => toast("Sent to the tenant.", { type: "success" }))
                          .catch((e) => toast(e?.data?.message || "Could not send.", { type: "error" }))}>
                  Send
                </Button>
              )}
              {row.is_downloadable && (
                <Button size="sm" variant="ghost" leftIcon={<Download className="h-3.5 w-3.5" />}
                        onClick={() => downloadFile(`/leases/${row.id}/download`, { filename: `lease-${row.tenant_name || row.id}.pdf` })
                          .catch((e) => toast(e.message, { type: "error" }))}>
                  Final copy
                </Button>
              )}
              {!row.is_downloadable && row.status !== "submitted" && row.status !== "superseded" && (
                <Button size="sm" variant="ghost" leftIcon={<Printer className="h-3.5 w-3.5" />}
                        onClick={() => downloadFile(`/leases/${row.id}/blank`, { filename: `lease-${row.id}-unsigned.pdf` })
                          .catch((e) => toast(e.message, { type: "error" }))}>
                  Unsigned copy
                </Button>
              )}
            </div>
          )}
        />
      )}

      <SendLeaseWizard isOpen={isSendOpen} onClose={() => setSendOpen(false)} />
      <UploadLeaseModal isOpen={isUploadOpen} onClose={() => setUploadOpen(false)} />
      <ReviewDrawer lease={reviewing} onClose={() => setReviewing(null)} mayEdit={mayEdit} />
    </div>
  );
}

function StatTile({ icon: Icon, label, value, active, onClick, accent }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx("glass flex items-center gap-4 p-4 text-left transition-colors hover:border-white/40", active && "border-secondary/70")}
    >
      <span className={clsx("rounded-xl p-2.5", accent)}><Icon className="h-5 w-5" /></span>
      <span>
        <span className="block text-2xl font-light text-white">{value}</span>
        <span className="block text-xs text-white/55">{label}</span>
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Send wizard: tenants → document → review
// ---------------------------------------------------------------------------

function SendLeaseWizard({ isOpen, onClose }) {
  const [step, setStep] = useState(0);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState({});
  const [kind, setKind] = useState("standard");
  const [templateId, setTemplateId] = useState("");
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");

  const { data: tenantsData, isFetching } = useGetTenantsQuery({ search, per_page: 50 }, { skip: !isOpen });
  const tenants = toRows(tenantsData);
  const { data: options } = useGetLeaseDocumentOptionsQuery(undefined, { skip: !isOpen });
  const [sendLeases, { isLoading }] = useSendLeasesMutation();

  const chosen = Object.values(selected);
  const reset = () => { setStep(0); setSelected({}); setKind("standard"); setTemplateId(""); setFile(null); setTitle(""); setSearch(""); };
  const close = () => { reset(); onClose(); };

  const documentReady = kind === "standard" || (kind === "custom" && templateId) || (kind === "uploaded" && (templateId || file));

  const submit = async () => {
    try {
      let body;
      if (kind === "uploaded" && file) {
        body = new FormData();
        chosen.forEach((t) => body.append("tenant_ids", t.id));
        body.append("file", file);
        body.append("document_kind", "uploaded");
        if (title) body.append("title", title);
      } else {
        body = { tenant_ids: chosen.map((t) => t.id), document_kind: kind, template_id: templateId ? Number(templateId) : null, title: title || null };
      }
      const res = await sendLeases(body).unwrap();
      toast(`Lease sent to ${res.count} tenant${res.count === 1 ? "" : "s"}. They've been notified in the portal, by SMS and email.`, { type: "success" });
      close();
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not send.", { type: "error" });
    }
  };

  const steps = ["Tenants", "Document", "Send"];

  return (
    <Modal isOpen={isOpen} onClose={close} title="Send a lease" size="lg">
      <ol className="mb-5 grid grid-cols-3 gap-2" aria-label="Steps">
        {steps.map((label, i) => (
          <li key={label} className={clsx("rounded-xl border px-3 py-2 text-xs",
            i === step ? "border-secondary bg-secondary/15 text-white" : i < step ? "border-emerald-400/40 text-emerald-200" : "border-white/10 text-white/40")}>
            <span className="font-semibold">{i + 1}.</span> {label}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <div className="space-y-3">
          <SearchInput value={search} onSearch={setSearch} placeholder="Search tenants by name, phone or unit…" />
          <div className="max-h-72 space-y-1 overflow-y-auto rounded-xl border border-white/10 p-1" aria-busy={isFetching}>
            {tenants.length === 0 && <p className="p-4 text-center text-sm text-white/40">{isFetching ? "Searching…" : "No tenants found."}</p>}
            {tenants.map((t) => {
              const on = Boolean(selected[t.id]);
              return (
                <label key={t.id} className={clsx("flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-sm",
                  on ? "bg-secondary/15" : "hover:bg-white/5")}>
                  <input type="checkbox" className="h-4 w-4 accent-secondary" checked={on}
                         onChange={() => setSelected((cur) => {
                           const next = { ...cur };
                           if (on) delete next[t.id]; else next[t.id] = t;
                           return next;
                         })} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-white">{t.first_name} {t.last_name}</span>
                    <span className="block truncate text-xs text-white/45">
                      {[t.unit_name || t.unit?.name, t.property_name || t.unit?.property_name, t.phone].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          <p className="text-sm text-white/60">{chosen.length} selected</p>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3" role="radiogroup" aria-label="Which document">
          <DocOption active={kind === "standard"} onClick={() => { setKind("standard"); setTemplateId(""); }}
                     icon={ScrollText} title="Sahil Pay standard agreement"
                     text="A complete Kenyan residential tenancy agreement, filled in from each tenant's details." />
          <DocOption active={kind === "custom"} onClick={() => { setKind("custom"); setTemplateId(""); }}
                     icon={PenLine} title="My own written template"
                     text={options?.custom?.length ? "Your wording from Settings → Documents." : "You haven't written one yet — create it in Settings → Documents."}
                     disabled={!options?.custom?.length} />
          {kind === "custom" && (
            <Select label="Template" value={templateId} onChange={(e) => setTemplateId(e.target.value)}
                    options={(options?.custom ?? []).map((t) => ({ value: t.id, label: t.name }))} />
          )}
          <DocOption active={kind === "uploaded"} onClick={() => { setKind("uploaded"); setTemplateId(""); }}
                     icon={Upload} title="An uploaded lease document"
                     text="Your own lease as a PDF or a photo. Tenants download it, sign on paper or in the portal, and send it back." />
          {kind === "uploaded" && (
            <div className="space-y-3 rounded-xl border border-white/10 p-3">
              {options?.uploaded?.length > 0 && (
                <Select label="Use a saved document" value={templateId}
                        onChange={(e) => { setTemplateId(e.target.value); if (e.target.value) setFile(null); }}
                        options={[{ value: "", label: "— or upload a new file below —" },
                                  ...options.uploaded.map((t) => ({ value: t.id, label: t.name }))]} />
              )}
              {!templateId && (
                <FileUpload label="Upload the lease" accept=".pdf,image/*" value={file} onChange={setFile}
                            hint="PDF is best. A clear photo of each page also works. Up to 20 MB." />
              )}
              <Input label="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Riverside Apartments lease 2026" />
            </div>
          )}
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <table className="doc-table kv">
            <tbody>
              <tr><td>Tenants</td><td>{chosen.map((t) => `${t.first_name} ${t.last_name}`).join(", ")}</td></tr>
              <tr><td>Document</td><td>{kind === "standard" ? "Sahil Pay standard agreement" : kind === "custom"
                ? (options?.custom ?? []).find((t) => String(t.id) === String(templateId))?.name
                : file?.name || (options?.uploaded ?? []).find((t) => String(t.id) === String(templateId))?.name}</td></tr>
              <tr><td>Branding</td><td>Your logo, colours, letterhead and contact details on every page</td></tr>
              <tr><td>Tenants are told by</td><td>Portal notification, SMS and email</td></tr>
            </tbody>
          </table>
          <p className="text-sm text-white/55">
            Sending replaces any earlier unsigned lease for the same tenancy. Anything already signed is untouched.
          </p>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between gap-2 border-t border-white/10 pt-4">
        <Button type="button" variant="ghost" onClick={step === 0 ? close : () => setStep(step - 1)}
                leftIcon={step === 0 ? null : <ChevronLeft className="h-4 w-4" />}>
          {step === 0 ? "Cancel" : "Back"}
        </Button>
        {step < 2 ? (
          <Button type="button" onClick={() => setStep(step + 1)}
                  disabled={(step === 0 && chosen.length === 0) || (step === 1 && !documentReady)}
                  rightIcon={<ChevronRight className="h-4 w-4" />}>
            Next
          </Button>
        ) : (
          <Button type="button" onClick={submit} isLoading={isLoading} leftIcon={<Send className="h-4 w-4" />}>
            Send to {chosen.length} tenant{chosen.length === 1 ? "" : "s"}
          </Button>
        )}
      </div>
    </Modal>
  );
}

function DocOption({ active, onClick, icon: Icon, title, text, disabled }) {
  return (
    <button type="button" role="radio" aria-checked={active} disabled={disabled} onClick={onClick}
            className={clsx("flex w-full items-start gap-3 rounded-2xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              active ? "border-secondary bg-secondary/15" : "border-white/15 bg-white/5 hover:border-white/30")}>
      <span className={clsx("rounded-xl p-2", active ? "bg-secondary text-white" : "bg-white/10 text-white/70")}><Icon className="h-5 w-5" /></span>
      <span>
        <span className="block text-sm font-medium text-white">{title}</span>
        <span className="mt-0.5 block text-xs text-white/55">{text}</span>
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Review drawer
// ---------------------------------------------------------------------------

function ReviewDrawer({ lease, onClose, mayEdit }) {
  const [approve, { isLoading: approving }] = useApproveLeaseMutation();
  const [reject, { isLoading: rejecting }] = useRejectLeaseMutation();
  const [reason, setReason] = useState("");
  const [returning, setReturning] = useState(false);
  const [pages, setPages] = useState([]);

  useEffect(() => {
    let urls = [];
    let cancelled = false;
    if (lease?.signing_method === "scan" && lease.scan_page_count) {
      Promise.all(Array.from({ length: lease.scan_page_count }, (_, i) =>
        fetchObjectUrl(`/leases/${lease.id}/scans/${i}`).catch(() => null)))
        .then((result) => { urls = result; if (!cancelled) setPages(result); });
    }
    return () => { cancelled = true; urls.forEach((u) => u && URL.revokeObjectURL(u)); setPages([]); };
  }, [lease?.id, lease?.signing_method, lease?.scan_page_count]);

  if (!lease) return null;
  const meta = STATUS[lease.status] ?? { color: "white", label: lease.status };

  const doApprove = async () => {
    try {
      await approve(lease.id).unwrap();
      toast("Approved. The tenant has been notified and both of you can download the final copy.", { type: "success" });
      onClose();
    } catch (e) { toast(e?.data?.message || "Could not approve.", { type: "error" }); }
  };
  const doReturn = async () => {
    try {
      await reject({ id: lease.id, reason }).unwrap();
      toast("Returned to the tenant with your note.", { type: "success" });
      setReason(""); setReturning(false); onClose();
    } catch (e) { toast(e?.data?.message || "Could not return it.", { type: "error" }); }
  };

  return (
    <Drawer isOpen={Boolean(lease)} onClose={onClose} title="Lease">
      <div className="space-y-5 overflow-y-auto pb-6">
        <div>
          <p className="text-lg text-white">{lease.tenant_name}</p>
          <p className="text-sm text-white/50">{[lease.unit_name && `Unit ${lease.unit_name}`, lease.property_name].filter(Boolean).join(" · ")}</p>
          <div className="mt-2"><Badge color={meta.color}>{meta.label}</Badge></div>
        </div>

        <table className="doc-table kv">
          <tbody>
            <tr><td>Document</td><td>{lease.title} <span className="text-xs text-white/40">({KIND_LABEL[lease.document_kind]})</span></td></tr>
            <tr><td>Sent</td><td>{lease.sent_at ? formatDate(lease.sent_at) : "—"}</td></tr>
            <tr><td>Opened by tenant</td><td>{lease.viewed_at ? formatDate(lease.viewed_at) : "Not yet"}</td></tr>
            <tr><td>Signed</td><td>{lease.signed_at ? `${formatDate(lease.signed_at)} · ${lease.signing_method === "scan" ? "on paper" : "in the portal"}` : "—"}</td></tr>
            <tr><td>Signed name</td><td>{lease.signed_name || "—"}</td></tr>
            <tr><td>Approved</td><td>{lease.status === "approved" && lease.reviewed_at ? formatDate(lease.reviewed_at) : "—"}</td></tr>
            {lease.rejection_reason && <tr><td>Returned because</td><td>{lease.rejection_reason}</td></tr>}
          </tbody>
        </table>

        {lease.signing_method === "scan" && (
          <div>
            <p className="mb-2 text-sm font-medium text-white">Pages the tenant signed ({lease.scan_page_count})</p>
            <div className="grid grid-cols-2 gap-2">
              {pages.map((url, i) => url ? (
                <a key={i} href={url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-xl border border-white/15 bg-white">
                  <img src={url} alt={`Signed page ${i + 1}`} className="aspect-[3/4] w-full object-contain"
                       onError={(e) => { e.currentTarget.replaceWith(Object.assign(document.createElement("div"), { className: "flex aspect-[3/4] items-center justify-center text-xs text-primary-900", textContent: `PDF page ${i + 1} — open` })); }} />
                </a>
              ) : (
                <div key={i} className="flex aspect-[3/4] items-center justify-center rounded-xl border border-white/10 text-xs text-white/40">Page {i + 1}</div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {(lease.status === "submitted" || lease.is_downloadable) && (
            <Button variant="ghost" size="sm" leftIcon={<FileText className="h-4 w-4" />}
                    onClick={() => downloadFile(`/leases/${lease.id}/download`, { filename: `lease-${lease.id}.pdf` })
                      .catch((e) => toast(e.message, { type: "error" }))}>
              {lease.is_downloadable ? "Download final copy" : "Open signed copy"}
            </Button>
          )}
          <Button variant="ghost" size="sm" leftIcon={<Printer className="h-4 w-4" />}
                  onClick={() => downloadFile(`/leases/${lease.id}/blank`, { filename: `lease-${lease.id}-unsigned.pdf` })
                    .catch((e) => toast(e.message, { type: "error" }))}>
            Unsigned copy
          </Button>
        </div>

        {lease.status === "submitted" && mayEdit && (
          <div className="space-y-3 border-t border-white/10 pt-4">
            {!returning ? (
              <div className="flex flex-wrap gap-2">
                <Button leftIcon={<Check className="h-4 w-4" />} onClick={doApprove} isLoading={approving} data-testid="approve-lease">
                  Approve lease
                </Button>
                <Button variant="ghost" leftIcon={<X className="h-4 w-4" />} onClick={() => setReturning(true)}>
                  Return for correction
                </Button>
              </div>
            ) : (
              <>
                <Textarea label="What needs correcting?" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
                <div className="flex gap-2">
                  <Button onClick={doReturn} isLoading={rejecting} disabled={!reason.trim()}>Return to tenant</Button>
                  <Button variant="ghost" onClick={() => setReturning(false)}>Cancel</Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </Drawer>
  );
}

function UploadLeaseModal({ isOpen, onClose }) {
  const [search, setSearch] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [file, setFile] = useState(null);
  const { data: tenantsData } = useGetTenantsQuery({ search, per_page: 50 }, { skip: !isOpen });
  const tenants = toRows(tenantsData);
  const [upload, { isLoading }] = useUploadLeaseMutation();

  const submit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    formData.append("file", file);
    try {
      await upload({ tenantId: Number(tenantId), formData }).unwrap();
      toast("Signed lease stored. You and the tenant can both download it now.", { type: "success" });
      onClose(); setTenantId(""); setFile(null);
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not store that file.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Record a lease signed in the office">
      <form onSubmit={submit} className="space-y-4">
        <SearchInput value={search} onSearch={setSearch} placeholder="Find the tenant…" />
        <Select label="Tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)} required
                options={tenants.map((t) => ({ value: t.id, label: `${t.first_name} ${t.last_name}` }))} />
        <FileUpload label="The signed agreement" accept=".pdf,image/*" value={file} onChange={setFile}
                    hint="One PDF is best. A clear photo of the signed pages also works." />
        <p className="text-sm text-white/50">
          For a lease the tenant signed in front of you. It is filed straight away — there is nothing to review.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" isLoading={isLoading} disabled={!tenantId || !file}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}
