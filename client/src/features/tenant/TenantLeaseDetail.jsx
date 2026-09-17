import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import clsx from "clsx";
import {
  ArrowLeft, Download, FileText, PenLine, Printer, Upload, CheckCircle2, AlertTriangle,
  Clock, X, ImageIcon, Check,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Spinner from "@/components/ui/Spinner";
import EmptyState from "@/components/ui/EmptyState";
import { toast } from "@/components/ui/Toast";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { TENANT_ROUTES } from "@/config/routePaths";
import {
  useGetPortalLeaseDetailQuery,
  useSignPortalLeaseMutation,
  useUploadPortalLeaseScanMutation,
} from "@/features/landlord/leases/leaseApiSlice";

// One tenancy agreement, start to finish, on a phone.
//
//   1 Read  →  2 Sign  →  3 Landlord reviews  →  4 Download
//
// Signing has two equal doors, because both are how Kenyans actually sign:
//   • "Sign here"      — type your name and agree; recorded with time and origin.
//   • "Sign on paper"  — download, print, sign in pen, photograph each page and
//                        upload them. The landlord reviews the pages here, so
//                        nobody has to visit the office.

const STEPS = ["Read", "Sign", "Review", "Download"];

function stepIndex(status) {
  if (status === "approved" || status === "uploaded") return 4;
  if (status === "submitted") return 2;
  return 1; // sent / rejected — reading and signing
}

function Stepper({ status }) {
  const current = stepIndex(status);
  return (
    <ol className="grid grid-cols-4 gap-1" aria-label="Lease progress">
      {STEPS.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={label} className="flex flex-col items-center gap-1.5 text-center">
            <span
              className={clsx(
                "flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                done && "border-emerald-400 bg-emerald-500/20 text-emerald-200",
                active && "border-secondary bg-secondary text-white shadow-lg shadow-secondary/30",
                !done && !active && "border-white/15 text-white/40"
              )}
              aria-current={active ? "step" : undefined}
            >
              {done ? <Check className="h-4 w-4" /> : i + 1}
            </span>
            <span className={clsx("text-[11px] sm:text-xs", active ? "text-white" : "text-white/50")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default function TenantLeaseDetail() {
  const { id } = useParams();
  const { data: lease, isLoading, isError } = useGetPortalLeaseDetailQuery(id);
  const [method, setMethod] = useState("electronic");

  if (isLoading) return <div className="flex justify-center py-16"><Spinner /></div>;
  if (isError || !lease) {
    return (
      <EmptyState
        title="Lease not found"
        description="It may have been replaced by a newer agreement."
        action={<Link to={TENANT_ROUTES.leases}><Button variant="ghost">Back to my leases</Button></Link>}
      />
    );
  }

  const downloadBlank = () =>
    downloadFile(`/portal/leases/${lease.id}/blank`, { filename: "tenancy-agreement-to-sign.pdf" })
      .then(() => toast("Downloaded. Print it, sign, then upload photos of the pages.", { type: "success" }))
      .catch((e) => toast(e.message || "Could not download.", { type: "error" }));

  const downloadFinal = () =>
    downloadFile(`/portal/leases/${lease.id}/download`, { filename: "tenancy-agreement.pdf" })
      .catch((e) => toast(e.message || "Could not download.", { type: "error" }));

  const isUploadedDoc = lease.document_kind === "uploaded";

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <Link to={TENANT_ROUTES.leases} className="inline-flex items-center gap-1.5 text-sm text-white/60 hover:text-white">
        <ArrowLeft className="h-4 w-4" /> My leases
      </Link>

      <header className="glass space-y-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-light tracking-wide text-white sm:text-2xl">{lease.title}</h1>
            <p className="mt-1 text-sm text-white/55">
              {[lease.unit_name && `Unit ${lease.unit_name}`, lease.property_name, lease.landlord_name]
                .filter(Boolean).join(" · ")}
            </p>
          </div>
          {lease.is_downloadable && (
            <Button leftIcon={<Download className="h-4 w-4" />} onClick={downloadFinal}>
              Download final copy
            </Button>
          )}
        </div>
        <Stepper status={lease.status} />
        <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          {[
            ["Sent", lease.sent_at],
            ["Opened", lease.viewed_at],
            ["Signed", lease.signed_at],
            ["Approved", lease.status === "approved" ? lease.reviewed_at : null],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg bg-white/5 px-3 py-2">
              <dt className="text-white/45">{label}</dt>
              <dd className="mt-0.5 text-white/85">{value ? formatDate(value) : "—"}</dd>
            </div>
          ))}
        </dl>
      </header>

      <StatusBanner lease={lease} />

      {/* The agreement itself */}
      {isUploadedDoc ? (
        <div className="glass flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div className="flex items-start gap-3">
            <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-white/60" />
            <p className="text-sm text-white/75">
              Your landlord sent their own lease document. Download it to read every page.
            </p>
          </div>
          <Button variant="ghost" leftIcon={<Download className="h-4 w-4" />} onClick={downloadBlank}>
            Download to read
          </Button>
        </div>
      ) : (
        lease.body_html && (
          <article
            className="glass max-h-[65vh] overflow-y-auto p-4 text-sm leading-relaxed text-white/80 sm:p-6
                       [&_h1]:mb-4 [&_h1]:text-base [&_h1]:font-medium [&_h1]:tracking-wide [&_h1]:text-white
                       [&_h2]:mt-5 [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-medium [&_h2]:text-white
                       [&_p]:my-2 [&_strong]:text-white"
            aria-label="Tenancy agreement text"
            dangerouslySetInnerHTML={{ __html: lease.body_html }}
          />
        )
      )}

      {lease.can_sign && (
        <section className="glass space-y-4 p-4 sm:p-6" aria-labelledby="sign-heading">
          <h2 id="sign-heading" className="text-lg font-medium text-white">How would you like to sign?</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup">
            <MethodCard
              active={method === "electronic"}
              onClick={() => setMethod("electronic")}
              icon={PenLine}
              title="Sign here"
              text="Type your name and agree. Takes a minute."
            />
            <MethodCard
              active={method === "scan"}
              onClick={() => setMethod("scan")}
              icon={Printer}
              title="Sign on paper"
              text="Download, print and sign in pen, then upload photos of the pages."
            />
          </div>
          {method === "electronic"
            ? <ElectronicSign lease={lease} />
            : <PaperSign lease={lease} onDownload={downloadBlank} />}
        </section>
      )}

      {!lease.can_sign && lease.signed_name && (
        <div className="glass p-4 sm:p-5">
          <p className="text-xs uppercase tracking-wide text-white/40">
            {lease.signing_method === "scan" ? "Signed on paper by" : "Signed electronically by"}
          </p>
          <p className="mt-1 font-serif text-lg italic text-white">{lease.signed_name}</p>
          <p className="mt-1 text-xs text-white/45">
            {formatDate(lease.signed_at)}
            {lease.signing_method === "scan" && lease.scan_page_count ? ` · ${lease.scan_page_count} page(s) uploaded` : ""}
          </p>
        </div>
      )}
    </div>
  );
}

function StatusBanner({ lease }) {
  const map = {
    sent: { icon: PenLine, tone: "border-secondary", title: "Please read and sign this agreement.",
            text: "Choose to sign here, or on paper — both are accepted by your landlord." },
    rejected: { icon: AlertTriangle, tone: "border-red-400", title: "Your landlord asked for a correction.",
                text: lease.rejection_reason },
    submitted: { icon: Clock, tone: "border-amber-400", title: "Signed — with your landlord for review.",
                 text: "You'll get a notification when it is approved, and can then download the final copy." },
    approved: { icon: CheckCircle2, tone: "border-emerald-400", title: "Approved. This lease is complete.",
                text: "Both you and your landlord have the same final copy. Download it for your records." },
    uploaded: { icon: CheckCircle2, tone: "border-emerald-400", title: "Signed in person and on file.",
                text: "Download your copy any time." },
  };
  const m = map[lease.status];
  if (!m) return null;
  const Icon = m.icon;
  return (
    <div className={clsx("glass flex items-start gap-3 border-l-4 p-4", m.tone)} role="status">
      <Icon className="mt-0.5 h-5 w-5 flex-shrink-0 text-white/80" />
      <div>
        <p className="text-sm font-medium text-white">{m.title}</p>
        {m.text && <p className="mt-1 text-sm text-white/65">{m.text}</p>}
      </div>
    </div>
  );
}

function MethodCard({ active, onClick, icon: Icon, title, text }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={clsx(
        "flex items-start gap-3 rounded-2xl border p-4 text-left transition-all",
        active ? "border-secondary bg-secondary/15 shadow-lg shadow-secondary/10" : "border-white/15 bg-white/5 hover:border-white/30"
      )}
    >
      <span className={clsx("rounded-xl p-2", active ? "bg-secondary text-white" : "bg-white/10 text-white/70")}>
        <Icon className="h-5 w-5" />
      </span>
      <span>
        <span className="block text-sm font-medium text-white">{title}</span>
        <span className="mt-0.5 block text-xs text-white/55">{text}</span>
      </span>
    </button>
  );
}

function ElectronicSign({ lease }) {
  const [name, setName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [sign, { isLoading }] = useSignPortalLeaseMutation();

  const submit = async (e) => {
    e.preventDefault();
    try {
      await sign({ id: lease.id, signed_name: name, agreed }).unwrap();
      toast("Signed and sent to your landlord for review.", { type: "success" });
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not sign.", { type: "error" });
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4 border-t border-white/10 pt-4">
      <Input
        label="Your full name, as on your ID"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g. Amina Wanjiru Kamau"
        autoComplete="name"
        required
      />
      <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-white/5 p-3 text-sm text-white/80">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
               className="mt-0.5 h-5 w-5 flex-shrink-0 accent-secondary" />
        <span>I have read this tenancy agreement and I agree to be bound by it.</span>
      </label>
      <p className="text-xs text-white/45">We record the date, time and device you sign from. That is what makes this binding.</p>
      <Button type="submit" className="w-full sm:w-auto" isLoading={isLoading}
              disabled={name.trim().length < 3 || !agreed} leftIcon={<PenLine className="h-4 w-4" />}>
        Sign and submit
      </Button>
    </form>
  );
}

function PaperSign({ lease, onDownload }) {
  const [files, setFiles] = useState([]);
  const [name, setName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [upload, { isLoading }] = useUploadPortalLeaseScanMutation();

  const previews = useMemo(
    () => files.map((f) => ({ file: f, url: f.type.startsWith("image/") ? URL.createObjectURL(f) : null })),
    [files]
  );
  useEffect(() => () => previews.forEach((p) => p.url && URL.revokeObjectURL(p.url)), [previews]);

  const addFiles = (list) => {
    const incoming = Array.from(list || []).filter((f) => /^(image\/|application\/pdf)/.test(f.type));
    if (incoming.length !== (list?.length ?? 0)) toast("Only photos (JPG, PNG) or PDF files can be uploaded.", { type: "error" });
    setFiles((cur) => [...cur, ...incoming].slice(0, 15));
  };

  const submit = async (e) => {
    e.preventDefault();
    const formData = new FormData();
    files.forEach((f) => formData.append("files", f));
    formData.append("signed_name", name);
    formData.append("agreed", agreed ? "true" : "false");
    try {
      await upload({ id: lease.id, formData }).unwrap();
      toast("Uploaded and sent to your landlord for review.", { type: "success" });
    } catch (err) {
      toast(err?.data?.message || err?.data?.error || "Could not upload.", { type: "error" });
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5 border-t border-white/10 pt-4">
      <ol className="space-y-4">
        <li className="flex gap-3">
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-white">1</span>
          <div className="flex-1 space-y-2">
            <p className="text-sm text-white">Download the agreement and print it.</p>
            <Button type="button" variant="ghost" leftIcon={<Download className="h-4 w-4" />} onClick={onDownload}>
              Download to print
            </Button>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-white">2</span>
          <p className="text-sm text-white">Fill in your details and sign every signature box in pen.</p>
        </li>
        <li className="flex gap-3">
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-white">3</span>
          <div className="flex-1 space-y-3">
            <p className="text-sm text-white">Photograph each page flat in good light (or scan them) and add them here, in order.</p>
            <label
              className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-white/25 bg-white/5 px-4 py-6 text-center transition-colors hover:border-secondary/60"
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}
            >
              <Upload className="h-7 w-7 text-white/50" />
              <span className="text-sm text-white/80">Take photos or choose files</span>
              <span className="text-xs text-white/45">JPG, PNG or PDF · up to 15 pages · 20 MB each</span>
              <input type="file" className="sr-only" multiple accept="image/*,application/pdf"
                     onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
            </label>
            {previews.length > 0 && (
              <ul className="grid grid-cols-3 gap-2 sm:grid-cols-5" aria-label="Pages to upload">
                {previews.map((p, i) => (
                  <li key={`${p.file.name}-${i}`} className="relative overflow-hidden rounded-xl border border-white/15 bg-white/5">
                    {p.url
                      ? <img src={p.url} alt={`Page ${i + 1}`} className="aspect-[3/4] w-full object-cover" />
                      : <div className="flex aspect-[3/4] items-center justify-center text-white/50"><FileText className="h-6 w-6" /></div>}
                    <span className="absolute left-1 top-1 rounded-md bg-black/60 px-1.5 text-[10px] text-white">{i + 1}</span>
                    <button type="button" aria-label={`Remove page ${i + 1}`}
                            onClick={() => setFiles((cur) => cur.filter((_, idx) => idx !== i))}
                            className="absolute right-1 top-1 rounded-full bg-black/60 p-1 text-white hover:bg-red-500">
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {previews.length === 0 && (
              <p className="flex items-center gap-1.5 text-xs text-white/40"><ImageIcon className="h-3.5 w-3.5" /> No pages added yet.</p>
            )}
          </div>
        </li>
      </ol>

      <Input label="Your full name, as you signed" value={name} onChange={(e) => setName(e.target.value)}
             autoComplete="name" required />
      <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-white/5 p-3 text-sm text-white/80">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
               className="mt-0.5 h-5 w-5 flex-shrink-0 accent-secondary" />
        <span>These are the pages of the agreement I signed.</span>
      </label>
      <Button type="submit" className="w-full sm:w-auto" isLoading={isLoading}
              disabled={!files.length || name.trim().length < 3 || !agreed}
              leftIcon={<Upload className="h-4 w-4" />}>
        Upload and submit ({files.length} page{files.length === 1 ? "" : "s"})
      </Button>
    </form>
  );
}
