import { useEffect, useMemo, useRef, useState } from "react";
import { Columns3, FileText, FileSpreadsheet } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import { SahilPayMark } from "@/components/branding/SahilPayLogo";
import { downloadFile } from "@/utils/downloadFile";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";

// Renders a structured report document (server JSON) as an on-screen preview
// with per-section column editing, then downloads honor the same column choice.
// One component powers every report — the server decides the sections/columns.
function formatCell(value, kind, currency) {
  if (value === null || value === undefined || value === "") {
    return kind === "money" ? formatCurrency(0, currency) : "—";
  }
  switch (kind) {
    case "money":
      return formatCurrency(value, currency);
    case "percent":
      return `${Number(value).toFixed(1)}%`;
    case "number":
      return Number.isInteger(Number(value)) ? String(value) : Number(value).toLocaleString();
    case "date":
      return formatDate(value);
    default:
      return String(value);
  }
}

// { sectionKey: [colKey,...] } of visible columns, seeded from the document.
function initialVisibility(doc) {
  const map = {};
  for (const sec of doc?.sections ?? []) {
    if (sec.kind === "keyvalue") continue;
    map[sec.key] = sec.columns.filter((c) => c.visible).map((c) => c.key);
  }
  return map;
}

function ColumnEditor({ section, visibleKeys, onToggle }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <Button variant="ghost" size="sm" leftIcon={<Columns3 className="h-4 w-4" />} onClick={() => setOpen((o) => !o)}>
        Edit columns
      </Button>
      {open && (
        <div className="glass-dark absolute right-0 z-30 mt-2 max-h-80 w-60 origin-top animate-scale-in overflow-y-auto p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-white/40">Columns</p>
          <div className="space-y-2">
            {section.columns.map((col) => (
              <Checkbox
                key={col.key}
                label={col.label}
                checked={visibleKeys.includes(col.key)}
                onChange={() => onToggle(section.key, col.key)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SectionTable({ section, visibleKeys, currency }) {
  const cols = section.columns.filter((c) => visibleKeys.includes(c.key));
  if (!cols.length) return <p className="py-6 text-center text-sm text-white/40">No columns selected.</p>;
  if (!section.rows.length) return <p className="py-6 text-center text-sm text-white/40">No records for this section.</p>;

  return (
    <div className="glass overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-white/40">
            {cols.map((c) => (
              <th key={c.key} className={`whitespace-nowrap px-4 py-3 font-medium ${c.align === "right" ? "text-right" : ""}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {section.rows.map((row, i) => (
            <tr key={i} className="border-b border-white/5 hover:bg-white/5">
              {cols.map((c) => (
                <td key={c.key} className={`whitespace-nowrap px-4 py-2.5 text-white/85 ${c.align === "right" ? "text-right" : ""}`}>
                  {formatCell(row[c.key], c.kind, currency)}
                </td>
              ))}
            </tr>
          ))}
          {section.totals && Object.keys(section.totals).length > 0 && (
            <tr className="border-t-2 border-white/20 font-semibold text-white">
              {cols.map((c, idx) => (
                <td key={c.key} className={`px-4 py-2.5 ${c.align === "right" ? "text-right" : ""}`}>
                  {c.key in section.totals
                    ? formatCell(section.totals[c.key], c.kind, currency)
                    : idx === 0
                    ? "Total"
                    : ""}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ChartsPanel({ section, includedKeys, onToggle }) {
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-white/70">Graphs — tick to include in the download</p>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {section.charts.map((chart) => {
          const data = section.rows.map((r) => ({ x: String(r[chart.x] ?? ""), value: Number(r[chart.y] ?? 0) }));
          return (
            <div key={chart.key} className="glass p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-medium text-white/80">{chart.title}</span>
                <Checkbox label="Include" checked={includedKeys.includes(chart.key)} onChange={() => onToggle(chart.key)} />
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="x" tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }} />
                  <YAxis tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 11 }} width={44} />
                  <Tooltip contentStyle={{ background: "#1a1a2e", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 8, color: "#fff" }} />
                  <Bar dataKey="value" fill="#7c5cff" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SummaryBlock({ section }) {
  return (
    <div className="glass max-w-md divide-y divide-white/10 p-2">
      {section.rows.map((row, i) => (
        <div key={i} className="flex items-center justify-between px-4 py-2.5 text-sm">
          <span className="text-white/50">{row.label}</span>
          <span className="font-medium text-white/90">{row.display}</span>
        </div>
      ))}
    </div>
  );
}

function initialCharts(doc) {
  // Every available chart is included in the download by default.
  const keys = [];
  for (const sec of doc?.sections ?? []) for (const c of sec.charts ?? []) keys.push(c.key);
  return keys;
}

export default function ReportView({ document: doc, endpoint, params = {}, filenameBase = "report" }) {
  const [visibility, setVisibility] = useState(() => initialVisibility(doc));
  const [includedCharts, setIncludedCharts] = useState(() => initialCharts(doc));
  const [downloading, setDownloading] = useState(null);

  // Re-seed column + chart selection whenever a fresh report is generated.
  useEffect(() => {
    setVisibility(initialVisibility(doc));
    setIncludedCharts(initialCharts(doc));
  }, [doc]);

  const currency = doc?.meta?.currency ?? "KES";

  const toggle = (sectionKey, colKey) =>
    setVisibility((prev) => {
      const cur = prev[sectionKey] ?? [];
      const next = cur.includes(colKey) ? cur.filter((k) => k !== colKey) : [...cur, colKey];
      return { ...prev, [sectionKey]: next };
    });

  const toggleChart = (key) =>
    setIncludedCharts((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  // Build ?columns=section.col,... preserving section column order.
  const columnsParam = useMemo(() => {
    const tokens = [];
    for (const sec of doc?.sections ?? []) {
      if (sec.kind === "keyvalue") continue;
      const chosen = visibility[sec.key] ?? [];
      for (const col of sec.columns) {
        if (chosen.includes(col.key)) tokens.push(`${sec.key}.${col.key}`);
      }
    }
    return tokens.join(",");
  }, [doc, visibility]);

  const handleDownload = async (format) => {
    setDownloading(format);
    try {
      const query = new URLSearchParams({ ...params, format, columns: columnsParam, charts: includedCharts.join(",") }).toString();
      await downloadFile(`${endpoint}?${query}`, {
        filename: `${filenameBase}.${format === "excel" ? "xlsx" : "pdf"}`,
        format,
      });
    } catch {
      toast("Export failed. Please try again.", { type: "error" });
    } finally {
      setDownloading(null);
    }
  };

  if (!doc) return null;
  const meta = doc.meta ?? {};

  return (
    <div className="space-y-6">
      {/* Letterhead preview */}
      <div className="glass flex items-start justify-between gap-4 border-l-2 border-secondary p-5">
        <div className="flex items-center gap-3">
          {meta.logo_url && <img src={meta.logo_url} alt="logo" className="max-h-12 max-w-[120px] object-contain" />}
          <div>
            <p className="text-lg font-semibold text-white">{meta.company_name}</p>
            {meta.company_address && <p className="text-xs text-white/50">{meta.company_address}</p>}
          </div>
        </div>
        <div className="text-right text-xs text-white/50">
          <p className="text-sm font-semibold text-white">{meta.report_title}</p>
          {meta.subject && <p>{meta.subject}</p>}
          {meta.property_name && <p>Property: {meta.property_name}</p>}
          {meta.period && <p>Period: {meta.period}</p>}
          <p>Generated: {meta.generated_at}</p>
          <p>Currency: {currency}</p>
        </div>
      </div>

      {/* Download controls */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-3">
          <Button variant="primary" size="sm" leftIcon={<FileText className="h-4 w-4" />} isLoading={downloading === "pdf"} onClick={() => handleDownload("pdf")}>
            Download PDF
          </Button>
          <Button variant="ghost" size="sm" leftIcon={<FileSpreadsheet className="h-4 w-4" />} isLoading={downloading === "excel"} onClick={() => handleDownload("excel")}>
            Download Excel
          </Button>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-white/30">
          <SahilPayMark className="h-4 w-4" /> Sahil Pay
        </span>
      </div>

      {/* Sections */}
      {doc.sections.map((section) => (
        <div key={section.key} className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">{section.title}</h3>
            {section.kind !== "keyvalue" && (
              <ColumnEditor section={section} visibleKeys={visibility[section.key] ?? []} onToggle={toggle} />
            )}
          </div>
          {section.note && <p className="text-xs text-white/40">{section.note}</p>}
          {section.kind === "keyvalue" ? (
            <SummaryBlock section={section} />
          ) : (
            <SectionTable section={section} visibleKeys={visibility[section.key] ?? []} currency={currency} />
          )}
          {section.charts?.length > 0 && (
            <ChartsPanel section={section} includedKeys={includedCharts} onToggle={toggleChart} />
          )}
        </div>
      ))}
    </div>
  );
}
