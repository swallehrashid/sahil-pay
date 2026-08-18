import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { Link } from "react-router-dom";
import { Upload } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Tabs from "@/components/ui/Tabs";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import {
  useGetEtimsScopeQuery,
  useGetEtimsRegisterQuery,
  useBulkEtimsMutation,
} from "./etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §4.2 — bulk entry, the workhorse.
//
// Framed as a TOOL, not a to-do list. The status filter says "Not yet
// recorded" because that is a working filter for someone doing data entry —
// it is not a judgement, and nothing on this page counts, colours or badges
// the rows that have no number.
//
// Mobile-first: this is the one screen a property manager will genuinely use
// on a phone, sitting with the KRA app open in another window and typing
// numbers across. Everything goes through ResponsiveTable, so on a phone each
// payment is a stacked card with a full-width input rather than a row in a
// sideways-scrolling table.

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "recorded", label: "Recorded" },
  { value: "not_recorded", label: "Not yet recorded" },
];

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function EtimsRegisterPage() {
  const { data: scope, isLoading: scopeLoading } = useGetEtimsScopeQuery();

  const [tab, setTab] = useState("payments");
  const [month, setMonth] = useState(currentMonth());
  const [status, setStatus] = useState("all");
  const [propertyIds, setPropertyIds] = useState([]);
  // Only edited rows are sent, so an untouched table saves nothing.
  const [edits, setEdits] = useState({});
  const [rowErrors, setRowErrors] = useState({});

  const { data, isLoading, isFetching } = useGetEtimsRegisterQuery(
    { scope: tab, month, status, propertyIds },
    { skip: !scope?.enabled }
  );
  const [bulkSave, { isLoading: isSaving }] = useBulkEtimsMutation();

  const rows = data?.rows ?? [];
  const editedCount = useMemo(() => Object.keys(edits).length, [edits]);

  if (scopeLoading) return <SkeletonForm fields={6} />;

  // No tax scope at all: this route should not have been reachable, and the
  // sidebar hides it. Say nothing about compliance — just point the way back.
  if (!scope?.enabled) {
    return (
      <EmptyState
        title="Nothing here yet"
        description="Turn on eTIMS for a property in Settings → Tax Compliance to use the Register."
      />
    );
  }

  const rowKey = (row) => `${row.kind}:${row.id}`;

  const setEdit = (row, field, value) => {
    const key = rowKey(row);
    setEdits((prev) => ({
      ...prev,
      [key]: {
        kind: row.kind,
        id: row.id,
        etims_invoice_number: row.etims_invoice_number ?? "",
        etims_issued_at: row.etims_issued_at?.slice(0, 10) ?? "",
        ...prev[key],
        [field]: value,
      },
    }));
    setRowErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  const handleSaveAll = async () => {
    const records = Object.values(edits).map((edit) => ({
      type: edit.kind,
      id: edit.id,
      etims_invoice_number: edit.etims_invoice_number,
      ...(edit.etims_issued_at ? { etims_issued_at: edit.etims_issued_at } : {}),
    }));
    if (!records.length) return;

    try {
      const payload = await bulkSave(records).unwrap();

      // Per-row errors are shown inline against their own row; the rows that
      // saved stay saved. Losing nine good rows to one typo would make bulk
      // entry pointless.
      const nextErrors = {};
      (payload.errors ?? []).forEach((err) => {
        const record = records[err.index];
        if (record) nextErrors[`${record.type}:${record.id}`] = err.message;
      });
      setRowErrors(nextErrors);

      const savedKeys = new Set((payload.saved ?? []).map((s) => `${s.kind}:${s.id}`));
      setEdits((prev) =>
        Object.fromEntries(Object.entries(prev).filter(([key]) => !savedKeys.has(key)))
      );

      if (payload.saved_count) {
        toast(
          `Saved ${payload.saved_count} ${payload.saved_count === 1 ? "entry" : "entries"}.`,
          { type: "success" }
        );
      }
      if (payload.error_count) {
        toast(`${payload.error_count} could not be saved — see the rows below.`, {
          type: "error",
        });
      }
    } catch (err) {
      toast(err?.data?.error || "Could not save.", { type: "error" });
    }
  };

  const exportCsv = () => {
    const header = ["Date", "Counterparty", "Unit", "Property", "Amount", "eTIMS invoice no."];
    const body = rows.map((row) =>
      [row.date, row.counterparty, row.unit, row.property, row.amount, row.etims_invoice_number]
        .map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`)
        .join(",")
    );
    const blob = new Blob([[header.join(","), ...body].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `etims-register-${tab}-${month}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const columns = [
    { key: "date", header: "Date" },
    { key: "counterparty", header: tab === "payouts" ? "Owner" : "Tenant",
      render: (row) => row.counterparty ?? "—" },
    { key: "unit", header: "Unit", render: (row) => row.unit ?? "—" },
    { key: "property", header: "Property", render: (row) => row.property ?? "—" },
    { key: "amount", header: "Amount", className: "text-right",
      render: (row) => formatCurrency(row.amount) },
    {
      key: "etims_invoice_number",
      header: "eTIMS invoice no.",
      render: (row) => {
        const key = rowKey(row);
        const edit = edits[key];
        const error = rowErrors[key];
        return (
          // w-full so the mobile card gives the input the whole width; the
          // desktop cell caps it so the table keeps its shape.
          <div className="w-full md:min-w-[12rem]">
            <Input
              value={edit?.etims_invoice_number ?? row.etims_invoice_number ?? ""}
              placeholder="Paste the number from KRA"
              onChange={(e) => setEdit(row, "etims_invoice_number", e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
            {error && <div className="mt-1 text-xs text-secondary">{error}</div>}
          </div>
        );
      },
    },
    {
      key: "etims_issued_at",
      header: "Issued",
      render: (row) => {
        const edit = edits[rowKey(row)];
        return (
          <div className="w-full md:min-w-[9rem]">
            <Input
              type="date"
              value={edit?.etims_issued_at ?? row.etims_issued_at?.slice(0, 10) ?? ""}
              onChange={(e) => setEdit(row, "etims_issued_at", e.target.value)}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="eTIMS Register"
        subtitle="Record the eTIMS invoice numbers you issued at KRA against the payments they cover."
        actions={
          /* Typing four hundred of these by hand is a morning's work and a
             morning's chance to put one on the wrong payment. */
          <Link to={LANDLORD_ROUTES.etimsImport}>
            <Button variant="ghost" leftIcon={<Upload className="h-4 w-4" />}>
              Import from a file
            </Button>
          </Link>
        }
      />

      <Tabs
        activeKey={tab}
        onChange={(next) => {
          setTab(next);
          setEdits({});
          setRowErrors({});
        }}
        tabs={[
          { key: "payments", label: "Rent payments" },
          { key: "payouts", label: "Commission payouts" },
        ]}
      />

      {/* Filters stack on a phone and only go side-by-side from sm up. */}
      <div className="glass space-y-3 p-4 sm:space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Input type="month" label="Month" value={month}
                 onChange={(e) => setMonth(e.target.value)} />
          <Select label="Status" value={status} options={STATUS_OPTIONS}
                  onChange={(e) => setStatus(e.target.value)} />
          <Select
            label="Property"
            value={propertyIds[0] ?? ""}
            onChange={(e) => setPropertyIds(e.target.value ? [Number(e.target.value)] : [])}
            placeholder="All properties"
            options={(scope.properties ?? []).map((p) => ({ value: p.id, label: p.name }))}
          />
        </div>
        {/* Full-width, thumb-reachable buttons on a phone; inline from sm up. */}
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={exportCsv} disabled={!rows.length}>
            <Download size={14} className="mr-1" /> CSV
          </Button>
          <Button type="button" onClick={handleSaveAll} disabled={!editedCount || isSaving}>
            {isSaving ? "Saving…" : `Save all${editedCount ? ` (${editedCount})` : ""}`}
          </Button>
        </div>
      </div>

      <ResponsiveTable
        columns={columns}
        rows={rows}
        keyField="id"
        isLoading={isLoading || isFetching}
        emptyState={
          <EmptyState
            title="No records for this month"
            description="Choose another month or property above."
          />
        }
      />
    </div>
  );
}
