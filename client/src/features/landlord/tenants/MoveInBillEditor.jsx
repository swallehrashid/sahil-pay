import { useEffect, useMemo, useState } from "react";
import { X, Plus, CalendarClock } from "lucide-react";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { formatCurrency } from "@/utils/currencyFormatter";
import { useGetChargeCategoriesQuery } from "@/features/landlord/chargeCategoryApiSlice";
import { useGetUnitQuery } from "@/features/landlord/units/unitApiSlice";
import { usePreviewMoveInMutation } from "./tenantApiSlice";

/**
 * The move-in bill on the Add Tenant form — a normal invoice editor.
 *
 * Pick any charge (Rent — Deposit / Balance / This month, Penalty — …, Water —
 * Deposit, Lease Agreement, or a custom item) and type the amount. The only
 * question is WHICH MONTH it is for:
 *
 *   Moving in before the 20th → leave "Bill the next month's move-in now"
 *   unticked. The bill is for the move-in month; "Rent — This month" is the
 *   part month (e.g. 5,000 of a 10,000 rent). Full rent starts next month.
 *
 *   Moving in from the 20th → tick it and choose the month (next month by
 *   default). Everything on this bill — rent, deposit, fees — is FOR that
 *   month, although it is raised and paid today. Receipts and reports say so,
 *   and the 1st-of-month run will not bill that month's rent again.
 *
 * "Include the first month's rent" adds the Rent — This month line, prefilled
 * with the unit's rent and editable.
 *
 * `value` = { bill_next_month, bill_month: "YYYY-MM", lines: [{key, category_id,
 * subcategory, item, amount}] } — sent as move_in_billing when the tenant is saved.
 */
const SUB_LABEL = { current: "This month", deposit: "Deposit", balance: "Balance" };
const CUSTOM = "custom";

function monthLabel(ym) {
  if (!ym) return "";
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}
function nextMonthOf(dateStr) {
  const d = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date();
  const n = new Date(d.getFullYear(), d.getMonth() + 1, 1);
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}`;
}
function monthOf(dateStr) {
  const d = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function ordinal(n) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
  return `${n}${s}`;
}


export default function MoveInBillEditor({ value, onChange, unitId, moveInDate }) {
  const { data: catData } = useGetChargeCategoriesQuery({ include_inactive: 0 });
  const categories = useMemo(() => catData?.categories ?? [], [catData]);
  const rentCat = categories.find((c) => c.name.toLowerCase() === "rent");
  const { data: unit } = useGetUnitQuery(unitId, { skip: !unitId });
  const [previewMoveIn] = usePreviewMoveInMutation();
  const [preview, setPreview] = useState(null);
  const [picker, setPicker] = useState("");
  const [customName, setCustomName] = useState("");

  const set = (patch) => onChange({ ...value, ...patch });
  const billedMonth = value.bill_next_month
    ? (value.bill_month || nextMonthOf(moveInDate))
    : monthOf(moveInDate);
  const moveInDay = moveInDate ? Number(moveInDate.slice(8, 10)) : null;

  const options = useMemo(() => {
    const opts = [];
    categories.forEach((c) => ["current", "deposit", "balance"].forEach((sub) => {
      opts.push({ value: `${c.id}:${sub}`, label: `${c.name} — ${SUB_LABEL[sub]}` });
    }));
    opts.push({ value: CUSTOM, label: "Custom item…" });
    return opts;
  }, [categories]);

  const firstRentLine = value.lines.find((l) => rentCat && String(l.category_id) === String(rentCat.id) && l.subcategory === "current");

  const addLine = (target, name) => {
    if (!target) return;
    if (target === CUSTOM) {
      if (!name?.trim()) return;
      set({ lines: [...value.lines, { key: `custom-${Date.now()}`, category_id: null, subcategory: "current", item: name.trim(), amount: "" }] });
      setCustomName("");
      setPicker("");
      return;
    }
    const [cid, sub] = target.split(":");
    if (value.lines.some((l) => String(l.category_id) === cid && l.subcategory === sub)) { setPicker(""); return; }
    const cat = categories.find((c) => String(c.id) === cid);
    const isRent = rentCat && cid === String(rentCat.id);
    const prefill = isRent && (sub === "current" || sub === "deposit") && unit?.rent_amount ? String(Number(unit.rent_amount)) : "";
    set({ lines: [...value.lines, { key: target, category_id: Number(cid), subcategory: sub,
                                    item: sub === "current" ? cat?.name : `${cat?.name} ${SUB_LABEL[sub]}`, amount: prefill }] });
    setPicker("");
  };
  const updateLine = (key, amount) => set({ lines: value.lines.map((l) => (l.key === key ? { ...l, amount } : l)) });
  const removeLine = (key) => set({ lines: value.lines.filter((l) => l.key !== key) });

  const toggleFirstRent = (checked) => {
    if (!rentCat) return;
    if (checked && !firstRentLine) addLine(`${rentCat.id}:current`);
    if (!checked && firstRentLine) removeLine(firstRentLine.key);
  };

  // The server's view of the bill: the exact wording each line will have on
  // the receipt, and the month it is filed under.
  const payloadLines = value.lines.map((l) => ({ category_id: l.category_id, subcategory: l.subcategory, item: l.item, amount: Number(l.amount) || 0 }));
  const key = JSON.stringify([unitId, moveInDate, value.bill_next_month, billedMonth, payloadLines]);
  useEffect(() => {
    if (!unitId) return undefined;
    const t = setTimeout(async () => {
      try {
        const res = await previewMoveIn({
          unit_id: unitId, move_in_date: moveInDate || undefined,
          bill_next_month: value.bill_next_month, bill_month: billedMonth, lines: payloadLines,
        }).unwrap();
        setPreview(res);
      } catch (err) {
        setPreview({ error: err?.data?.error || err?.data?.message || "Could not check the bill." });
      }
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <div className="space-y-4" data-testid="move-in-bill">
      <div>
        <Checkbox
          name="bill_next_month"
          label="Bill the next month's move-in now"
          checked={value.bill_next_month}
          onChange={(e) => set({ bill_next_month: e.target.checked, bill_month: e.target.checked ? (value.bill_month || nextMonthOf(moveInDate)) : "" })}
        />
        <p className="mt-1 pl-7 text-xs leading-relaxed text-white/45">
          For tenants moving in from the 20th. Everything on this bill is for the month you choose — the
          receipt, the reports and the 1st-of-month run all treat it as that month's, although it is raised
          and paid today. Moving in earlier? Leave it unticked and bill the part month as "Rent — This month".
        </p>
        {moveInDay >= 20 && !value.bill_next_month && (
          <p className="mt-2 flex items-center gap-2 pl-7 text-xs text-amber-300" data-testid="move-in-hint">
            <CalendarClock className="h-3.5 w-3.5" /> Moving in on the {ordinal(moveInDay)} — usually billed for {monthLabel(nextMonthOf(moveInDate))}: tick the box above.
          </p>
        )}
      </div>

      {value.bill_next_month && (
        <div className="max-w-xs pl-7">
          <Input label="Month this bill is for" type="month" name="bill_month" value={billedMonth}
                 onChange={(e) => set({ bill_month: e.target.value })} />
        </div>
      )}

      <div className="pl-7">
        <Checkbox
          name="include_first_rent"
          label={`Include the first month's rent (${monthLabel(billedMonth)})`}
          checked={Boolean(firstRentLine)}
          onChange={(e) => toggleFirstRent(e.target.checked)}
        />
      </div>

      <div className="space-y-2 pl-7">
        <p className="text-xs font-medium uppercase tracking-wide text-white/40">
          Invoice items — all for {monthLabel(billedMonth)}
        </p>
        {value.lines.map((l) => (
          <div key={l.key} className="flex items-end gap-3">
            <div className="min-w-0 flex-1 text-sm text-white/85">
              {l.item}
              <span className="ml-1 text-xs text-white/40">— {monthLabel(billedMonth)}</span>
            </div>
            <div className="w-40">
              <Input aria-label={`Amount for ${l.item}`} name={`amount_${l.key}`} type="number" step="0.01" value={l.amount}
                     onChange={(e) => updateLine(l.key, e.target.value)} placeholder="0.00" />
            </div>
            <button type="button" onClick={() => removeLine(l.key)} aria-label={`Remove ${l.item}`}
                    className="mb-2 rounded p-1.5 text-white/40 hover:text-secondary"><X className="h-4 w-4" /></button>
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-72">
            <Select label="Add an item" name="move_in_item" value={picker}
                    onChange={(e) => { const v = e.target.value; setPicker(v); if (v && v !== CUSTOM) addLine(v); }}
                    options={options.filter((o) => o.value === CUSTOM || !value.lines.some((l) => `${l.category_id}:${l.subcategory}` === o.value))} />
          </div>
          {picker === CUSTOM && (
            <>
              <div className="w-56"><Input label="Item name" name="custom_item" value={customName} onChange={(e) => setCustomName(e.target.value)} /></div>
              <Button type="button" variant="ghost" size="sm" leftIcon={<Plus className="h-4 w-4" />} onClick={() => addLine(CUSTOM, customName)}>Add</Button>
            </>
          )}
        </div>
      </div>

      {unitId && preview && (
        <div className="ml-7 rounded-lg bg-white/5 p-3 text-sm" data-testid="move-in-preview">
          {preview.error ? (
            <p className="text-red-300">{preview.error}</p>
          ) : preview.lines?.length ? (
            <>
              <p className="mb-1 text-xs text-white/45">As it will read on the receipt:</p>
              {preview.lines.map((l, i) => (
                <div key={i} className="flex justify-between gap-4 py-0.5">
                  <span className="text-white/85">{l.label}</span>
                  <span className="text-white">{formatCurrency(l.amount)}</span>
                </div>
              ))}
              <div className="mt-1 flex justify-between border-t border-white/10 pt-1 font-semibold text-white">
                <span>Move-in total</span><span>{formatCurrency(preview.total)}</span>
              </div>
            </>
          ) : (
            <p className="text-white/50">No items yet — add rent, a deposit, a fee… or leave it empty to bill later.</p>
          )}
        </div>
      )}
    </div>
  );
}
