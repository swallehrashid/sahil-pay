import { useRef, useState } from "react";
import {
  Upload, Download, CheckCircle2, AlertTriangle, XCircle, ArrowRight, Loader2,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import { toast } from "@/components/ui/Toast";
import { env } from "@/config/env";
import { getAccessToken } from "@/utils/tokenStorage";

/**
 * Bring an existing estate in from a spreadsheet.
 *
 * Three steps, deliberately: download a template, upload it and SEE what would
 * happen, then commit. The review step is the point — importing 200 tenants
 * blind and discovering afterwards that half are missing is unrecoverable, so
 * nothing is written until the landlord has looked at the damage report.
 */

const STEPS = ["Upload", "Review", "Done"];

async function apiCall(path, { method = "POST", body } = {}) {
  const res = await fetch(`${env.apiBaseUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${getAccessToken()}` },
    body,
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.error || "Something went wrong.");
  return payload;
}

export default function TenantImportWizard({ isOpen, onClose, onImported }) {
  const [step, setStep] = useState(0);
  const [file, setFile] = useState(null);
  const [validation, setValidation] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  function reset() {
    setStep(0);
    setFile(null);
    setValidation(null);
    setResult(null);
    setBusy(false);
  }

  function close() {
    reset();
    onClose?.();
  }

  async function downloadTemplate() {
    try {
      const res = await fetch(`${env.apiBaseUrl}/tenants/import/template`, {
        headers: { Authorization: `Bearer ${getAccessToken()}` },
      });
      if (!res.ok) throw new Error("Could not download the template.");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sahilpay-tenant-import-template.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err.message, { type: "error" });
    }
  }

  async function runValidation(selected) {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", selected);
      const data = await apiCall("/tenants/import/validate", { body: form });
      setValidation(data);
      setStep(1);
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await apiCall("/tenants/import/commit", { body: form });
      setResult(data);
      setStep(2);
      onImported?.();
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setBusy(false);
    }
  }

  const summary = validation?.summary;
  const rows = validation?.rows ?? [];
  const badRows = rows.filter((r) => !r.ok);

  return (
    <Modal isOpen={isOpen} onClose={close} title="Import tenants from a spreadsheet" size="lg">
      {/* Step indicator */}
      <div className="mb-6 flex items-center gap-2">
        {STEPS.map((label, index) => (
          <div key={label} className="flex flex-1 items-center gap-2">
            <span
              className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                index < step
                  ? "bg-emerald-500/20 text-emerald-300"
                  : index === step
                  ? "bg-secondary text-white"
                  : "bg-white/10 text-white/40"
              }`}
            >
              {index < step ? "✓" : index + 1}
            </span>
            <span className={index === step ? "text-sm text-white" : "text-sm text-white/40"}>
              {label}
            </span>
            {index < STEPS.length - 1 && <div className="h-px flex-1 bg-white/10" />}
          </div>
        ))}
      </div>

      {/* ---- Step 1: upload ------------------------------------------------ */}
      {step === 0 && (
        <div className="space-y-5">
          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
            <h3 className="text-sm font-medium text-white">Start with the template</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-white/55">
              It has every column, two example rows, and a Notes sheet explaining
              what goes where. If your list is in a book, a photo or a PDF, get it
              into this template first — then upload it here.
            </p>
            <Button
              variant="ghost"
              className="mt-3"
              leftIcon={<Download className="h-4 w-4" />}
              onClick={downloadTemplate}
            >
              Download the template
            </Button>
          </div>

          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) {
                setFile(dropped);
                runValidation(dropped);
              }
            }}
            className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-white/20 p-10 text-center transition-colors hover:border-secondary/50 hover:bg-white/[0.03]"
          >
            {busy ? (
              <Loader2 className="h-6 w-6 animate-spin text-secondary" />
            ) : (
              <Upload className="h-6 w-6 text-white/40" />
            )}
            <p className="text-sm text-white">
              {busy ? "Checking your file…" : "Drop your filled-in file here, or click to choose"}
            </p>
            <p className="text-xs text-white/40">Excel (.xlsx) or CSV · up to 2,000 rows</p>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,.xlsm,.csv"
              className="hidden"
              onChange={(e) => {
                const chosen = e.target.files?.[0];
                if (chosen) {
                  setFile(chosen);
                  runValidation(chosen);
                }
              }}
            />
          </div>

          <p className="text-xs leading-relaxed text-white/40">
            Nothing is saved at this stage — you'll see exactly what would be
            created before anything is written.
          </p>
        </div>
      )}

      {/* ---- Step 2: review ------------------------------------------------ */}
      {step === 1 && summary && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: "Rows found", value: summary.total, tone: "text-white" },
              { label: "Ready to import", value: summary.valid, tone: "text-emerald-300" },
              { label: "Have problems", value: summary.errors, tone: summary.errors ? "text-red-300" : "text-white/50" },
              { label: "New properties", value: summary.new_properties, tone: "text-white/70" },
            ].map((stat) => (
              <div key={stat.label} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className={`text-2xl font-light tabular-nums ${stat.tone}`}>{stat.value}</div>
                <div className="mt-0.5 text-xs text-white/45">{stat.label}</div>
              </div>
            ))}
          </div>

          {summary.errors > 0 && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="flex items-start gap-2 text-sm text-amber-100">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>
                  {summary.errors} row{summary.errors === 1 ? "" : "s"} can't be
                  imported and will be skipped. Fix them in your spreadsheet and
                  upload again, or go ahead and import the {summary.valid} good
                  one{summary.valid === 1 ? "" : "s"} now.
                </span>
              </p>
            </div>
          )}

          <div className="max-h-72 overflow-y-auto rounded-xl border border-white/10">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-primary-900 text-left text-xs uppercase tracking-wider text-white/40">
                <tr>
                  <th className="px-3 py-2">Row</th>
                  <th className="px-3 py-2">Tenant</th>
                  <th className="px-3 py-2">Unit</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.line}
                    className={`border-t border-white/5 ${row.ok ? "" : "bg-red-500/[0.06]"}`}
                  >
                    <td className="px-3 py-2 text-white/40">{row.line}</td>
                    <td className="px-3 py-2 text-white">
                      {row.data.first_name} {row.data.last_name}
                    </td>
                    <td className="px-3 py-2 text-white/60">
                      {row.data.property_name} · {row.data.unit_name}
                    </td>
                    <td className="px-3 py-2">
                      {row.ok ? (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                          <CheckCircle2 className="h-3 w-3" />
                          {row.warnings.length ? row.warnings[0] : "Ready"}
                        </span>
                      ) : (
                        <span className="inline-flex items-start gap-1 text-xs text-red-300">
                          <XCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                          {row.errors.join(" ")}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={reset}>Choose another file</Button>
            <Button
              onClick={commit}
              isLoading={busy}
              disabled={summary.valid === 0}
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Import {summary.valid} tenant{summary.valid === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      )}

      {/* ---- Step 3: done -------------------------------------------------- */}
      {step === 2 && result && (
        <div className="space-y-5">
          <div className="flex flex-col items-center gap-2 py-4 text-center">
            <CheckCircle2 className="h-10 w-10 text-emerald-400" />
            <h3 className="text-lg font-light text-white">{result.message}</h3>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Tenants", result.created.tenants],
              ["Units", result.created.units],
              ["Properties", result.created.properties],
              ["Opening balances", result.created.opening_invoices],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                <div className="text-2xl font-light tabular-nums text-white">{value}</div>
                <div className="mt-0.5 text-xs text-white/45">{label}</div>
              </div>
            ))}
          </div>

          {result.created.opening_invoices > 0 && (
            <p className="text-xs leading-relaxed text-white/45">
              Opening balances were raised as invoices, so each tenant's arrears
              show on their statement with a clear origin rather than appearing
              from nowhere.
            </p>
          )}

          {result.skipped?.length > 0 && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="text-sm text-amber-100">
                {result.skipped.length} row{result.skipped.length === 1 ? "" : "s"} were
                skipped. Fix them in your spreadsheet and import again — the
                tenants already brought in won't be duplicated, because their
                account numbers are taken.
              </p>
            </div>
          )}

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={reset}>Import another file</Button>
            <Button onClick={close}>Done</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
