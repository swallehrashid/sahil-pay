import { useState } from "react";
import { Download, FileText } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import EmptyState from "@/components/ui/EmptyState";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetEtimsScopeQuery, useGetKraMonthlyReportQuery } from "./etimsApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §4.3 — the filing aid.
//
// Two things this page must get right:
//   * The CONSOLIDATED figure is what gets filed. Under a PM account that
//     means per property OWNER, because the owner is the taxpayer even though
//     the manager collected the money.
//   * The coverage line ("eTIMS invoices recorded: N of M") is the only place
//     in the entire product where a count of unrecorded invoices appears, and
//     it renders as plain muted text — never a warning colour, never a badge.
//
// Mobile-first: the two headline figures stack into a single column on a phone
// and the per-payment appendix becomes stacked cards, because the number a
// landlord actually needs — the MRI total — must be readable without any
// horizontal scrolling.

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

const APPENDIX_COLUMNS = [
  { key: "date", header: "Date" },
  { key: "tenant", header: "Tenant", render: (row) => row.tenant ?? "—" },
  { key: "unit", header: "Unit", render: (row) => row.unit ?? "—" },
  { key: "property", header: "Property", render: (row) => row.property ?? "—" },
  { key: "amount", header: "Rent received", className: "text-right",
    render: (row) => formatCurrency(row.amount) },
  // Blank when not recorded — plain, unstyled, unremarked.
  { key: "etims_invoice_number", header: "eTIMS invoice no.",
    render: (row) => row.etims_invoice_number || "" },
];

export default function KraMonthlyReport() {
  const { data: scope, isLoading: scopeLoading } = useGetEtimsScopeQuery();
  const [month, setMonth] = useState(currentMonth());
  const [propertyId, setPropertyId] = useState("");
  const [consolidated, setConsolidated] = useState(true);

  const { data: report, isLoading, isFetching } = useGetKraMonthlyReportQuery(
    { month, propertyId: propertyId || undefined, consolidated },
    { skip: !scope?.enabled }
  );

  if (scopeLoading) return <SkeletonForm fields={6} />;

  if (!scope?.enabled) {
    return (
      <EmptyState
        title="Nothing here yet"
        description="Turn on eTIMS for a property in Settings → Tax Compliance to use this report."
      />
    );
  }

  const download = (format) => {
    const params = new URLSearchParams({
      month,
      consolidated: consolidated ? "true" : "false",
      format,
      ...(propertyId ? { property_id: propertyId } : {}),
    });
    window.open(`/api/reports/kra-monthly?${params}`, "_blank");
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="KRA Monthly Report"
        subtitle="Gross rent received in the month and the indicative 7.5% Monthly Rental Income figure."
      />

      <div className="glass space-y-3 p-4 sm:space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input type="month" label="Month" value={month}
                 onChange={(e) => setMonth(e.target.value)} />
          <Select
            label="Property"
            value={propertyId}
            onChange={(e) => setPropertyId(e.target.value)}
            placeholder="All properties"
            options={(scope.properties ?? []).map((p) => ({ value: p.id, label: p.name }))}
          />
        </div>
        <Checkbox
          label="Consolidate per landlord (the filing figure)"
          checked={consolidated}
          onChange={(e) => setConsolidated(e.target.checked)}
        />
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={() => download("csv")}>
            <Download size={14} className="mr-1" /> CSV
          </Button>
          <Button type="button" variant="ghost" onClick={() => download("pdf")}>
            <FileText size={14} className="mr-1" /> PDF
          </Button>
        </div>
      </div>

      {isLoading || isFetching ? (
        <SkeletonForm fields={6} />
      ) : !report?.groups?.length ? (
        <EmptyState
          title="No rent received in this month"
          description="Choose another month above."
        />
      ) : (
        <>
          <div className="glass grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 sm:p-6">
            <div>
              <div className="text-xs uppercase tracking-wide text-white/40">
                Gross rent received
              </div>
              <div className="mt-1 text-xl font-light text-white sm:text-2xl">
                {formatCurrency(report.totals.gross_rent_received)}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-white/40">
                Indicative MRI @ 7.5%
              </div>
              <div className="mt-1 text-xl font-light text-secondary sm:text-2xl">
                {formatCurrency(report.totals.mri_due)}
              </div>
            </div>
            <p className="text-sm text-white/50 sm:col-span-2">{report.filing_note}</p>
          </div>

          {report.groups.map((group) => (
            <div key={group.key} className="space-y-3">
              <div className="glass flex flex-col gap-2 p-5 sm:flex-row sm:items-baseline sm:justify-between sm:p-6">
                <div className="min-w-0">
                  <h3 className="text-base font-medium text-white">{group.name}</h3>
                  {group.kra_pin && (
                    <div className="text-xs text-white/40">KRA PIN: {group.kra_pin}</div>
                  )}
                  <div className="text-xs text-white/40">
                    {group.properties.map((p) => p.name).join(", ")}
                  </div>
                </div>
                <div className="shrink-0 sm:text-right">
                  <div className="text-sm text-white/70">
                    {formatCurrency(group.gross_rent_received)} received
                  </div>
                  <div className="text-sm font-medium text-secondary">
                    {formatCurrency(group.mri_due)} MRI
                  </div>
                </div>
              </div>

              {group.appendix.length > 0 && (
                <ResponsiveTable
                  columns={APPENDIX_COLUMNS}
                  rows={group.appendix}
                  keyField="payment_id"
                />
              )}

              {/* The one coverage figure in the product. Muted text, nothing more. */}
              <div className="text-xs text-white/40">{group.coverage_line}</div>
            </div>
          ))}

          <p className="text-xs text-white/30">{report.disclaimer}</p>
        </>
      )}
    </div>
  );
}
