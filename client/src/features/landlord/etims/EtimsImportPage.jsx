import { useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Info, Upload } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import FileUpload from "@/components/ui/FileUpload";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import {
  useGetEtimsImportCatalogueQuery,
  useInspectEtimsFileMutation,
  useValidateEtimsImportMutation,
  useCommitEtimsImportMutation,
} from "./etimsImportApiSlice";

/**
 * Putting KRA control numbers back onto the payments they belong to.
 *
 * This screen exists because the matcher refuses to guess. A control number
 * attests to KRA that a particular sale happened for a particular amount, so a
 * number on the wrong payment is a false statement to a tax authority — and the
 * only safe way to resolve a row that could be two payments is to show a person
 * both and let them choose.
 *
 * Which is why the review step is not a summary. Every row shows the payment it
 * matched, by tenant and unit and amount, because "412 matched" is not something
 * anybody can check.
 */

const STATUS_LOOK = {
  matched:          { label: "Will apply",  color: "third" },
  ambiguous:        { label: "Choose one",  color: "white" },
  unmatched:        { label: "No match",    color: "secondary" },
  amount_mismatch:  { label: "Disagrees",   color: "secondary" },
  already_recorded: { label: "Already done", color: "white" },
  invalid:          { label: "Unusable",    color: "secondary" },
};

export default function EtimsImportPage() {
  const { data: catalogue } = useGetEtimsImportCatalogueQuery();
  const fields = catalogue?.fields ?? [];

  const [step, setStep] = useState(0);
  const [file, setFile] = useState(null);
  const [parsed, setParsed] = useState(null);
  const [mapping, setMapping] = useState({});
  const [allowAmountDate, setAllowAmountDate] = useState(false);
  const [preview, setPreview] = useState(null);
  // {line: payment_id} — a human's explicit choice for rows the matcher would
  // not decide. Nothing else about an ambiguous row is assumed.
  const [resolutions, setResolutions] = useState({});
  const [result, setResult] = useState(null);

  const [inspectFile, { isLoading: inspecting }] = useInspectEtimsFileMutation();
  const [validateImport, { isLoading: validating }] = useValidateEtimsImportMutation();
  const [commitImport, { isLoading: committing }] = useCommitEtimsImportMutation();

  const missingRequired = useMemo(
    () => fields.filter((f) => f.required && !mapping[f.key]).map((f) => f.label),
    [fields, mapping]
  );

  const applyCount = useMemo(() => {
    if (!preview) return 0;
    return preview.summary.matched + Object.keys(resolutions).length;
  }, [preview, resolutions]);

  const upload = async () => {
    try {
      const data = await inspectFile({ file }).unwrap();
      setParsed(data);
      setMapping(data.suggested_mapping || {});
      setStep(1);
    } catch (err) {
      toast(err?.data?.message || "Could not read that file.", { type: "error" });
    }
  };

  const review = async () => {
    try {
      const data = await validateImport({
        rows: parsed.rows,
        mapping,
        options: { allow_amount_date_match: allowAmountDate },
      }).unwrap();
      setPreview(data);
      setResolutions({});
      setStep(2);
    } catch (err) {
      toast(err?.data?.message || "Could not check that file.", { type: "error" });
    }
  };

  const commit = async () => {
    try {
      const data = await commitImport({
        rows: parsed.rows,
        mapping,
        options: { allow_amount_date_match: allowAmountDate },
        resolutions,
      }).unwrap();
      setResult(data);
      setStep(3);
      toast(`${data.applied.length} control number(s) recorded.`, { type: "success" });
    } catch (err) {
      toast(err?.data?.message || "The import failed.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader
        title="Import eTIMS numbers"
        subtitle="Match control numbers issued outside Sahil Pay back onto their payments"
      />

      <p className="mb-5 flex items-start gap-2 text-sm leading-relaxed text-white/50">
        <Info className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <span>
          A control number says a specific sale happened for a specific amount, so
          nothing here is guessed. A row that could be two payments is handed back
          to you to choose, and a row whose amount disagrees with the payment is
          refused rather than applied.
        </span>
      </p>

      {/* ---------------------------------------------------------------- */}
      {step === 0 && (
        <div className="glass space-y-4 p-5 sm:p-6">
          <FileUpload
            label="File from KRA or your accountant"
            accept=".csv,.xlsx,.xlsm,.xls"
            hint="CSV or Excel. Your own column names are fine."
            value={file}
            onChange={setFile}
          />
          <Button onClick={upload} isLoading={inspecting} disabled={!file}
                  leftIcon={<Upload className="h-4 w-4" />}>
            Read the file
          </Button>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {step === 1 && parsed && (
        <div className="space-y-5">
          <div className="glass space-y-3 p-5 sm:p-6">
            <p className="text-sm text-white/60">
              {parsed.row_count} row{parsed.row_count === 1 ? "" : "s"}. Match each
              field to a column.
            </p>
            {fields.map((field) => (
              <div key={field.key} className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:items-center">
                <div>
                  <span className="text-sm text-white/80">
                    {field.label}
                    {field.required && <span className="ml-1 text-secondary">*</span>}
                  </span>
                  {field.help && (
                    <p className="text-xs leading-relaxed text-white/40">{field.help}</p>
                  )}
                </div>
                <Select
                  value={mapping[field.key] || ""}
                  onChange={(e) =>
                    setMapping((m) => ({ ...m, [field.key]: e.target.value || undefined }))
                  }
                  options={[
                    { value: "", label: "— not in my file —" },
                    ...parsed.headers.filter(Boolean).map((h) => ({ value: h, label: h })),
                  ]}
                />
              </div>
            ))}
          </div>

          <div className="glass space-y-2 p-5 sm:p-6">
            <Checkbox
              label="Also match on amount + date when there is no reference"
              checked={allowAmountDate}
              onChange={(e) => setAllowAmountDate(e.target.checked)}
            />
            <p className="text-xs leading-relaxed text-white/40">
              Off by default. Two tenants paying the same rent on the same day is
              ordinary, so amount and date alone identify a payment poorly — any
              tie is shown to you rather than picked.
            </p>
          </div>

          {missingRequired.length > 0 && (
            <p className="flex items-center gap-2 text-sm text-amber-300/80">
              <AlertTriangle className="h-4 w-4" /> Still to match: {missingRequired.join(", ")}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" onClick={() => setStep(0)}
                    leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
            <Button onClick={review} isLoading={validating}
                    disabled={missingRequired.length > 0}>
              Check the matches
            </Button>
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {step === 2 && preview && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Will apply" value={preview.summary.matched} tone="good" />
            <Stat label="Need a choice" value={preview.summary.ambiguous} tone="warn" />
            <Stat label="No match" value={preview.summary.unmatched} tone="bad" />
            <Stat label="Refused" value={preview.summary.mismatch + preview.summary.invalid} tone="bad" />
          </div>

          <div className="glass overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/10 text-white/40">
                  <th className="px-3 py-2 font-medium">Row</th>
                  <th className="px-3 py-2 font-medium">Control number</th>
                  <th className="px-3 py-2 font-medium">Payment</th>
                  <th className="px-3 py-2 font-medium">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => {
                  const look = STATUS_LOOK[row.status] || STATUS_LOOK.invalid;
                  return (
                    <tr key={row._line} className="border-b border-white/5 last:border-0">
                      <td className="px-3 py-2 text-white/40">{row._line}</td>
                      <td className="px-3 py-2 text-white/85">{row.etims_invoice_number || "—"}</td>
                      <td className="px-3 py-2">
                        {/* The reviewer's job is to confirm THIS number belongs to
                            THAT payment, which they cannot do from a count. */}
                        {row.payment ? (
                          <div className="text-xs text-white/70">
                            <div className="text-white/85">{row.payment.tenant_name}</div>
                            <div className="text-white/40">
                              {row.payment.property_name} · {row.payment.unit_name} ·{" "}
                              {formatCurrency(row.payment.amount)} · {row.payment.payment_date}
                            </div>
                          </div>
                        ) : row.status === "ambiguous" ? (
                          <Select
                            value={resolutions[row._line] ? String(resolutions[row._line]) : ""}
                            onChange={(e) =>
                              setResolutions((r) => {
                                const next = { ...r };
                                if (e.target.value) next[row._line] = Number(e.target.value);
                                else delete next[row._line];
                                return next;
                              })
                            }
                            options={[
                              { value: "", label: "Choose the right payment…" },
                              ...(row.candidates || []).map((c) => ({
                                value: String(c.payment_id),
                                label: `${c.tenant_name} · ${c.unit_name} · ${formatCurrency(c.amount)} · ${c.payment_date}`,
                              })),
                            ]}
                          />
                        ) : (
                          <span className="text-white/30">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Badge color={look.color}>{look.label}</Badge>
                        {row.message && (
                          <p className="mt-1 max-w-md text-xs leading-relaxed text-white/45">
                            {row.message}
                          </p>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" onClick={() => setStep(1)}
                    leftIcon={<ArrowLeft className="h-4 w-4" />}>Back to mapping</Button>
            <Button onClick={commit} isLoading={committing} disabled={applyCount === 0}>
              Record {applyCount} number{applyCount === 1 ? "" : "s"}
            </Button>
            {preview.summary.ambiguous > 0 && (
              <span className="text-xs text-white/40">
                {preview.summary.ambiguous} row(s) still need a choice — they are
                skipped unless you pick a payment.
              </span>
            )}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------------- */}
      {step === 3 && result && (
        <div className="glass space-y-4 p-6">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-6 w-6 text-emerald-400" />
            <div>
              <p className="text-white">
                {result.applied.length} control number
                {result.applied.length === 1 ? "" : "s"} recorded.
              </p>
              {result.failed.length > 0 && (
                <p className="text-sm text-white/50">{result.failed.length} refused.</p>
              )}
            </div>
          </div>
          {result.failed.length > 0 && (
            <ul className="space-y-1 text-xs text-white/50">
              {result.failed.map((f, i) => (
                <li key={i}>Row {f._line}: {f.message}</li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={() => { setStep(0); setFile(null); setResult(null); }}>
            Import another file
          </Button>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }) {
  const colour =
    tone === "good" ? "text-emerald-400"
    : tone === "warn" ? "text-amber-300"
    : tone === "bad" ? "text-secondary"
    : "text-white";
  return (
    <div className="glass px-4 py-3">
      <p className="text-xs uppercase tracking-wide text-white/40">{label}</p>
      <p className={`text-xl ${colour}`}>{value}</p>
    </div>
  );
}
