import { useMemo, useState } from "react";
import { FileText, Upload, Check, X, Download, Send } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Textarea from "@/components/ui/Textarea";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import FileUpload from "@/components/ui/FileUpload";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { toast } from "@/components/ui/Toast";
import { toRows } from "@/utils/tableAdapters";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import {
  useGetLeasesQuery,
  useCreateLeaseMutation,
  useSendLeaseMutation,
  useApproveLeaseMutation,
  useRejectLeaseMutation,
  useUploadLeaseMutation,
} from "./leaseApiSlice";

// Tenancy agreements, both routes in one place.
//
// A lease is either signed in the tenant's portal or on paper and photographed.
// A landlord asking "do I have a signed lease for this unit?" does not care
// which, so the two are one list with a Source column rather than two screens.

const STATUS_TONE = {
  draft:     { tone: "muted",   label: "Draft" },
  sent:      { tone: "info",    label: "With the tenant" },
  submitted: { tone: "warning", label: "Needs review" },
  rejected:  { tone: "danger",  label: "Returned" },
  approved:  { tone: "success", label: "Approved" },
  uploaded:  { tone: "success", label: "Signed on paper" },
};

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  ...Object.entries(STATUS_TONE).map(([value, { label }]) => ({ value, label })),
];

export default function LeasesPage() {
  const [status, setStatus] = useState("");
  const [isPrepareOpen, setPrepareOpen] = useState(false);
  const [isUploadOpen, setUploadOpen] = useState(false);
  const [rejecting, setRejecting] = useState(null);

  const params = useMemo(() => (status ? { status } : {}), [status]);
  const { data, isLoading } = useGetLeasesQuery(params);
  const { data: tenantsData } = useGetTenantsQuery();
  const tenants = useMemo(() => toRows(tenantsData), [tenantsData]);

  const [sendLease] = useSendLeaseMutation();
  const [approveLease] = useApproveLeaseMutation();

  const rows = data?.items ?? [];
  const awaiting = data?.awaiting_review ?? 0;

  const act = async (fn, okMessage) => {
    try {
      await fn().unwrap();
      toast(okMessage, { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "That didn't work.", { type: "error" });
    }
  };

  const columns = [
    { key: "tenant_name", header: "Tenant" },
    {
      key: "status", header: "Status",
      render: (r) => {
        const meta = STATUS_TONE[r.status] ?? { tone: "muted", label: r.status };
        return <Badge tone={meta.tone}>{meta.label}</Badge>;
      },
    },
    {
      key: "source", header: "Signed",
      render: (r) => (r.source === "uploaded" ? "On paper" : "In the portal"),
    },
    { key: "signed_name", header: "Signed by", render: (r) => r.signed_name || "—" },
    {
      key: "signed_at", header: "Signed on",
      render: (r) => (r.signed_at ? formatDate(r.signed_at) : "—"),
    },
    {
      key: "created_at", header: "Created",
      render: (r) => formatDate(r.created_at),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lease agreements"
        subtitle="Signed in the portal or on paper — both end up here"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />}
                    onClick={() => setUploadOpen(true)}>
              Upload a signed lease
            </Button>
            <Button leftIcon={<FileText className="h-4 w-4" />}
                    onClick={() => setPrepareOpen(true)}>
              Prepare a lease
            </Button>
          </div>
        }
      />

      {awaiting > 0 && (
        <div className="glass flex items-center gap-3 border-l-2 border-amber-400/60 p-4">
          <p className="text-sm text-amber-100">
            {awaiting} lease{awaiting === 1 ? "" : "s"} signed and waiting for your review.
          </p>
        </div>
      )}

      <div className="glass p-4">
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}
                options={STATUS_FILTERS} />
      </div>

      {!isLoading && rows.length === 0 ? (
        <EmptyState
          title="No lease agreements yet"
          description="Prepare one for a tenant to sign in their portal, or upload a lease that was signed on paper."
        />
      ) : (
        <ResponsiveTable
          columns={columns}
          rows={rows}
          isLoading={isLoading}
          rowActions={(row) => (
            <div className="flex flex-wrap gap-2">
              {row.status === "draft" && (
                <Button size="sm" variant="ghost" leftIcon={<Send className="h-3.5 w-3.5" />}
                        onClick={() => act(() => sendLease(row.id), "Sent to the tenant.")}>
                  Send
                </Button>
              )}
              {row.status === "submitted" && (
                <>
                  <Button size="sm" leftIcon={<Check className="h-3.5 w-3.5" />}
                          onClick={() => act(() => approveLease(row.id), "Lease approved.")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="ghost" leftIcon={<X className="h-3.5 w-3.5" />}
                          onClick={() => setRejecting(row)}>
                    Return
                  </Button>
                </>
              )}
              {row.is_downloadable && (
                <Button size="sm" variant="ghost" leftIcon={<Download className="h-3.5 w-3.5" />}
                        onClick={() => downloadFile(`/leases/${row.id}/download`,
                                                    { filename: `lease-${row.tenant_name || row.id}.pdf` })}>
                  Download
                </Button>
              )}
            </div>
          )}
        />
      )}

      <PrepareLeaseModal isOpen={isPrepareOpen} onClose={() => setPrepareOpen(false)}
                        tenants={tenants} />
      <UploadLeaseModal isOpen={isUploadOpen} onClose={() => setUploadOpen(false)}
                        tenants={tenants} />
      <RejectModal lease={rejecting} onClose={() => setRejecting(null)} />
    </div>
  );
}

function PrepareLeaseModal({ isOpen, onClose, tenants }) {
  const [tenantId, setTenantId] = useState("");
  const [sendNow, setSendNow] = useState(true);
  const [create, { isLoading }] = useCreateLeaseMutation();

  const submit = async (e) => {
    e.preventDefault();
    try {
      await create({ tenantId: Number(tenantId), send: sendNow }).unwrap();
      toast(sendNow ? "Prepared and sent to the tenant." : "Draft prepared.",
            { type: "success" });
      onClose();
      setTenantId("");
    } catch (err) {
      toast(err?.data?.error || "Could not prepare the lease.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Prepare a lease">
      <form onSubmit={submit} className="space-y-4">
        <Select
          label="Tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          options={tenants.map((t) => ({
            value: t.id, label: `${t.first_name} ${t.last_name}`,
          }))}
          required
        />
        <p className="text-sm text-white/50">
          The agreement is built from your lease template in Settings → Documents.
          If you haven't written one, a complete standard Kenyan tenancy agreement
          is used.
        </p>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-white/70">
          <input type="checkbox" checked={sendNow} className="h-4 w-4 accent-secondary"
                 onChange={(e) => setSendNow(e.target.checked)} />
          Send it to the tenant to sign straight away
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" isLoading={isLoading} disabled={!tenantId}>Prepare</Button>
        </div>
      </form>
    </Modal>
  );
}

function UploadLeaseModal({ isOpen, onClose, tenants }) {
  const [tenantId, setTenantId] = useState("");
  const [file, setFile] = useState(null);
  const [upload, { isLoading }] = useUploadLeaseMutation();

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return toast("Choose the signed lease first.", { type: "error" });
    const formData = new FormData();
    formData.append("file", file);
    try {
      await upload({ tenantId: Number(tenantId), formData }).unwrap();
      toast("Signed lease stored. Both you and the tenant can download it.",
            { type: "success" });
      onClose();
      setTenantId(""); setFile(null);
    } catch (err) {
      toast(err?.data?.error || "Could not store that file.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Upload a signed lease">
      <form onSubmit={submit} className="space-y-4">
        <Select
          label="Tenant"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          options={tenants.map((t) => ({
            value: t.id, label: `${t.first_name} ${t.last_name}`,
          }))}
          required
        />
        <FileUpload
          label="The signed agreement"
          accept=".pdf,image/*"
          value={file}
          onChange={setFile}
          hint="One PDF is best. A clear photo of the signed pages also works."
        />
        <p className="text-sm text-white/50">
          Use this when the tenant signed on paper. It is stored against the
          tenancy and both of you can download it immediately — there is nothing
          to review, because you were there.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" isLoading={isLoading} disabled={!tenantId || !file}>
            Upload
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RejectModal({ lease, onClose }) {
  const [reason, setReason] = useState("");
  const [reject, { isLoading }] = useRejectLeaseMutation();

  const submit = async (e) => {
    e.preventDefault();
    try {
      await reject({ id: lease.id, reason }).unwrap();
      toast("Returned to the tenant.", { type: "success" });
      onClose();
      setReason("");
    } catch (err) {
      toast(err?.data?.error || "Could not return it.", { type: "error" });
    }
  };

  return (
    <Modal isOpen={Boolean(lease)} onClose={onClose} title="Return this lease">
      <form onSubmit={submit} className="space-y-4">
        <p className="text-sm text-white/50">
          The tenant gets their answers back with your note, corrects them and
          signs again. Their previous signature is discarded — it belonged to the
          old wording.
        </p>
        <Textarea
          label="What needs correcting?"
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required
        />
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" isLoading={isLoading} disabled={!reason.trim()}>
            Return to tenant
          </Button>
        </div>
      </form>
    </Modal>
  );
}
