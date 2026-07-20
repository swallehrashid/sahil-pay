import { useState } from "react";
import Select from "@/components/ui/Select";
import DatePicker from "@/components/ui/DatePicker";
import Spinner from "@/components/ui/Spinner";
import ExportButtons from "@/components/ui/ExportButtons";
import { formatCurrency } from "@/utils/currencyFormatter";
import {
  useGetChargeCategoriesQuery,
  useGetPaymentsReportQuery,
} from "../chargeCategoryApiSlice";

// Charge-category Payments Report (§5.5). Pick a category (or All) + a date range;
// per tenant it consolidates deposit invoiced/paid/balance/held plus balance &
// current collected, with total = balance + current (deposits excluded).
const COLUMNS = [
  { key: "deposit_invoiced", label: "Deposit invoiced" },
  { key: "deposit_paid", label: "Deposit paid" },
  { key: "deposit_balance", label: "Deposit balance" },
  { key: "deposit_held", label: "Deposit held" },
  { key: "balance_collected", label: "Balance collected" },
  { key: "current_collected", label: "Current collected" },
  { key: "total_collected", label: "Total collected", strong: true },
];

function Row({ cells, name, strong }) {
  return (
    <tr className={"border-t border-white/5 " + (strong ? "font-semibold text-white" : "text-white/80")}>
      <td className="py-2 pr-3 text-sm">{name}</td>
      {COLUMNS.map((c) => (
        <td key={c.key} className={"py-2 pl-3 text-right text-sm " + (c.strong ? "text-white" : "")}>
          {formatCurrency(cells[c.key] || 0)}
        </td>
      ))}
    </tr>
  );
}

function CategorySection({ section }) {
  if (!section.rows.length) {
    return (
      <div className="glass p-5">
        <h3 className="text-base font-medium text-white">{section.category_name}</h3>
        <p className="mt-2 text-sm text-white/40">No activity in this range.</p>
      </div>
    );
  }
  return (
    <div className="glass overflow-hidden p-5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-base font-medium text-white">{section.category_name}</h3>
        <span className="rounded bg-white/5 px-1.5 py-0.5 text-xs uppercase tracking-wide text-white/40">
          {section.kind}
        </span>
      </div>
      <div className="table-scroll overflow-x-auto">
        <table className="w-full min-w-[720px]">
          <thead>
            <tr className="text-xs text-white/40">
              <th className="pb-2 pr-3 text-left font-medium">Tenant</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="pb-2 pl-3 text-right font-medium">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {section.rows.map((r) => (
              <Row key={r.tenant_id} name={r.tenant_name} cells={r} />
            ))}
            <tr className="border-t-2 border-white/15 font-semibold text-white">
              <td className="py-2 pr-3 text-sm">Total</td>
              {COLUMNS.map((c) => (
                <td key={c.key} className="py-2 pl-3 text-right text-sm">
                  {formatCurrency(section.totals[c.key] || 0)}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PaymentsReport({ properties = [] }) {
  const [categoryId, setCategoryId] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [propertyId, setPropertyId] = useState("");

  const { data: catData } = useGetChargeCategoriesQuery({ include_inactive: 0 });
  const categories = catData?.categories ?? [];

  const params = {
    category_id: categoryId,
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    ...(propertyId ? { property_id: propertyId } : {}),
  };
  const { data, isFetching } = useGetPaymentsReportQuery(params);
  const sections = data?.categories ?? [];
  const grand = data?.grand_total;

  return (
    <div className="space-y-6">
      <div className="glass grid grid-cols-1 gap-4 p-5 sm:grid-cols-2 lg:grid-cols-4">
        <Select
          label="Category"
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value)}
          options={[
            { value: "all", label: "All categories" },
            ...categories.map((c) => ({ value: String(c.id), label: `${c.name} (${c.kind})` })),
          ]}
        />
        <DatePicker label="From" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <DatePicker label="To" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <Select
          label="Property"
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          options={[
            { value: "", label: "All properties" },
            ...properties.map((p) => ({ value: String(p.id), label: p.name })),
          ]}
        />
        <div className="sm:col-span-2 lg:col-span-4">
          <ExportButtons endpoint="/reports/payments" filenameBase="payments-report" params={params} />
        </div>
      </div>

      {isFetching ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : sections.length === 0 ? (
        <div className="glass p-8 text-center text-sm text-white/40">
          No categories or payments to report on for this selection.
        </div>
      ) : (
        <>
          {sections.map((s) => (
            <CategorySection key={s.category_id} section={s} />
          ))}

          {categoryId === "all" && grand && (
            <div className="glass p-5">
              <h3 className="mb-3 text-base font-medium text-white">All categories — grand total</h3>
              <div className="table-scroll overflow-x-auto">
                <table className="w-full min-w-[720px]">
                  <tbody>
                    <Row name="Everything" cells={grand} strong />
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-white/40">
                Total collected excludes deposits (held money), matching each category's total.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
