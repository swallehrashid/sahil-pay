import { useMemo, useState } from "react";
import { Plus, Trash2, AlertTriangle, PlayCircle } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Badge from "@/components/ui/Badge";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { toRows } from "@/utils/tableAdapters";
import { useGetPropertiesQuery } from "@/features/landlord/properties/propertyApiSlice";
import {
  useGetPenaltyPolicyQuery,
  useSavePenaltyPolicyMutation,
  usePreviewPenaltiesQuery,
  useRunPenaltiesMutation,
} from "@/features/landlord/penalties/penaltyApiSlice";

// Late-payment penalties, configured PER PROPERTY.
//
// Per property rather than per account because that is how the business works:
// a manager running eighty blocks for seventy owners has some who charge late
// fees and some who refuse to, at different amounts and on different days. So
// the page is a property picker first, and a form second.
//
// The preview is deliberately prominent: switching this on takes money off real
// tenants automatically, and nobody should have to learn what it does by
// watching it happen.

const MODES = [
  { value: "fixed",      label: "A fixed amount" },
  { value: "percentage", label: "A percentage of what's owed" },
  { value: "tiered",     label: "Banded by how much is owed" },
];

const TRIGGERS = [
  { value: "day_of_month",   label: "On a day of the month" },
  { value: "days_after_due", label: "A number of days after the invoice due date" },
];

const EMPTY = {
  is_enabled: false,
  mode: "fixed",
  fixed_amount: "",
  percentage_rate: "",
  trigger_type: "day_of_month",
  trigger_day: 5,
  grace_days: "",
  min_balance: "",
  max_penalty: "",
  tiers: [],
};

export default function PenaltySettings() {
  const { data: propertiesData, isLoading: loadingProperties } =
    useGetPropertiesQuery({ per_page: 200 });
  const properties = useMemo(() => toRows(propertiesData), [propertiesData]);

  const [chosenId, setChosenId] = useState(null);
  // Derived, not synced: the picker defaults to the first property until
  // someone chooses. Doing this in an effect would render once with nothing
  // selected and then again with a selection, for no gain.
  const propertyId = chosenId ?? properties[0]?.id ?? null;

  if (loadingProperties) return <SkeletonForm fields={6} />;

  if (!properties.length) {
    return (
      <div className="glass p-6">
        <h3 className="text-base font-medium text-white">Late payment penalties</h3>
        <p className="mt-2 text-sm text-white/50">
          Add a property first — penalties are set per property, because
          different owners charge different late fees, or none at all.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="glass space-y-3 p-6">
        <h3 className="text-base font-medium text-white">Late payment penalties</h3>
        <p className="text-sm leading-relaxed text-white/50">
          Set per property. A penalty is charged at most once a month while a
          tenant is still in arrears, and is never included in management
          commission.
        </p>
        <Select
          label="Property"
          value={propertyId ?? ""}
          onChange={(e) => setChosenId(Number(e.target.value))}
          options={properties.map((p) => ({ value: p.id, label: p.name }))}
        />
      </div>

      {propertyId != null && (
        <PolicyForm key={propertyId} propertyId={propertyId} />
      )}

      <PenaltyPreview />
    </div>
  );
}

function PolicyForm({ propertyId }) {
  const { data, isLoading } = useGetPenaltyPolicyQuery(propertyId);
  const [save, { isLoading: isSaving }] = useSavePenaltyPolicyMutation();
  const [form, setForm] = useState(EMPTY);
  const [loadedFor, setLoadedFor] = useState(null);

  // Seed the form from the server's answer once it arrives, adjusting state
  // during render rather than in an effect. An effect would paint the empty
  // form first and the real values a frame later, which reads as a flicker on
  // a slow connection — and React documents this as the pattern for exactly
  // this case (state derived from props/data that changes).
  if (data && loadedFor !== data.property_id) {
    setLoadedFor(data.property_id);
    setForm({
      is_enabled:      Boolean(data.is_enabled),
      mode:            data.mode || "fixed",
      fixed_amount:    data.fixed_amount ?? "",
      percentage_rate: data.percentage_rate ?? "",
      trigger_type:    data.trigger_type || "day_of_month",
      trigger_day:     data.trigger_day ?? 5,
      grace_days:      data.grace_days ?? "",
      min_balance:     data.min_balance ?? "",
      max_penalty:     data.max_penalty ?? "",
      tiers:           (data.tiers || []).map((t) => ({
        min_balance: t.min_balance ?? "",
        max_balance: t.max_balance ?? "",
        amount_type: t.amount_type || "fixed",
        amount:      t.amount ?? "",
      })),
    });
  }

  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target?.value ?? e }));

  const addTier = () =>
    setForm((f) => ({
      ...f,
      tiers: [...f.tiers, { min_balance: "", max_balance: "", amount_type: "fixed", amount: "" }],
    }));

  const setTier = (index, key, value) =>
    setForm((f) => ({
      ...f,
      tiers: f.tiers.map((t, i) => (i === index ? { ...t, [key]: value } : t)),
    }));

  const removeTier = (index) =>
    setForm((f) => ({ ...f, tiers: f.tiers.filter((_, i) => i !== index) }));

  const submit = async (e) => {
    e.preventDefault();
    // Send blanks as null rather than "" so the server's numeric validation
    // sees "not set" instead of "not a number".
    const blankToNull = (v) => (v === "" || v === undefined ? null : v);
    try {
      await save({
        propertyId,
        is_enabled:      form.is_enabled,
        mode:            form.mode,
        fixed_amount:    blankToNull(form.fixed_amount),
        percentage_rate: blankToNull(form.percentage_rate),
        trigger_type:    form.trigger_type,
        trigger_day:     blankToNull(form.trigger_day),
        grace_days:      blankToNull(form.grace_days),
        min_balance:     blankToNull(form.min_balance),
        max_penalty:     blankToNull(form.max_penalty),
        tiers: form.tiers.map((t) => ({
          min_balance: blankToNull(t.min_balance),
          max_balance: blankToNull(t.max_balance),
          amount_type: t.amount_type,
          amount:      blankToNull(t.amount),
        })),
      }).unwrap();
      toast("Penalty rules saved.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save these rules.", { type: "error" });
    }
  };

  if (isLoading) return <SkeletonForm fields={5} />;

  return (
    <form onSubmit={submit} className="glass space-y-5 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-medium text-white">Rules for this property</h3>
        {form.is_enabled
          ? <Badge tone="success">Automatic</Badge>
          : <Badge tone="muted">Off</Badge>}
      </div>

      <Checkbox
        name="is_enabled"
        label="Charge penalties automatically"
        checked={form.is_enabled}
        onChange={(e) => setForm((f) => ({ ...f, is_enabled: e.target.checked }))}
      />
      <p className="-mt-2 text-xs text-white/40">
        When this is off, nothing is ever charged without someone asking for it.
      </p>

      <Select label="How much" value={form.mode} onChange={set("mode")} options={MODES} />

      {form.mode === "fixed" && (
        <Input label="Penalty amount (KES)" type="number" min="0"
               value={form.fixed_amount} onChange={set("fixed_amount")} />
      )}

      {form.mode === "percentage" && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="Percentage of arrears (%)" type="number" min="0" max="100" step="0.01"
                 value={form.percentage_rate} onChange={set("percentage_rate")} />
          <Input label="Never charge more than (KES)" type="number" min="0"
                 value={form.max_penalty} onChange={set("max_penalty")}
                 hint="Optional cap" />
        </div>
      )}

      {form.mode === "tiered" && (
        <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-white/70">Bands</p>
            <Button type="button" size="sm" variant="ghost"
                    leftIcon={<Plus className="h-4 w-4" />} onClick={addTier}>
              Add band
            </Button>
          </div>
          <p className="text-xs text-white/40">
            Each band runs from its "owes at least" up to (but not including)
            the next one. Leave the top band's upper limit empty for "and above".
          </p>

          {form.tiers.length === 0 && (
            <p className="text-sm text-white/40">No bands yet.</p>
          )}

          {form.tiers.map((tier, index) => (
            <div key={index} className="grid grid-cols-1 gap-3 sm:grid-cols-4">
              <Input label="Owes at least" type="number" min="0" value={tier.min_balance}
                     onChange={(e) => setTier(index, "min_balance", e.target.value)} />
              <Input label="Up to (blank = no limit)" type="number" min="0" value={tier.max_balance}
                     onChange={(e) => setTier(index, "max_balance", e.target.value)} />
              <Input label="Charge (KES)" type="number" min="0" value={tier.amount}
                     onChange={(e) => setTier(index, "amount", e.target.value)} />
              <div className="flex items-end">
                <Button type="button" variant="ghost" size="sm"
                        leftIcon={<Trash2 className="h-4 w-4" />}
                        onClick={() => removeTier(index)}>
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Select label="When" value={form.trigger_type} onChange={set("trigger_type")}
              options={TRIGGERS} />

      {form.trigger_type === "day_of_month" ? (
        <Input label="Day of the month" type="number" min="1" max="28"
               value={form.trigger_day} onChange={set("trigger_day")}
               hint="1–28, so the rule means the same thing in February" />
      ) : (
        <Input label="Days after the due date" type="number" min="0"
               value={form.grace_days} onChange={set("grace_days")}
               hint="Each tenant is judged against their own invoice" />
      )}

      <Input label="Only charge if they owe at least (KES)" type="number" min="0"
             value={form.min_balance} onChange={set("min_balance")}
             hint="Optional. Stops a small rounding remainder producing a fine." />

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs text-white/50">
        Penalties are never included in management commission, and never
        compound — a tenant in arrears for three months has three separate
        charges, not a penalty on a penalty.
      </div>

      <div className="flex justify-end">
        <Button type="submit" isLoading={isSaving}>Save rules</Button>
      </div>
    </form>
  );
}

// Who would be charged if the run happened today — across every property on the
// account, so a manager can see the whole picture before switching anything on.
function PenaltyPreview() {
  const [date, setDate] = useState("");
  const { data, isFetching, refetch } = usePreviewPenaltiesQuery(date || undefined);
  const [run, { isLoading: isRunning }] = useRunPenaltiesMutation();

  const charged = data?.charged ?? 0;

  const doRun = async () => {
    try {
      const result = await run(date ? { date } : {}).unwrap();
      toast(`${result.charged} penalty charge(s) raised.`, { type: "success" });
      refetch();
    } catch (err) {
      toast(err?.data?.error || "Could not run penalties.", { type: "error" });
    }
  };

  return (
    <div className="glass space-y-4 p-6">
      <h3 className="text-base font-medium text-white">Preview</h3>
      <p className="text-sm text-white/50">
        Who would be charged if the run happened on this date. Nothing is
        written until you press Run.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>

      {isFetching ? (
        <SkeletonForm fields={2} />
      ) : charged === 0 ? (
        <p className="text-sm text-white/40">
          Nothing would be charged on this date.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            {charged} tenant{charged === 1 ? "" : "s"} would be charged,
            totalling KES {Number(data.total).toLocaleString()}.
          </p>
          {(data.properties || []).map((prop) => (
            <div key={prop.property_id}
                 className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
              <p className="text-sm font-medium text-white/80">{prop.property}</p>
              <ul className="mt-1 space-y-0.5">
                {(prop.tenants || []).map((t) => (
                  <li key={t.tenant_id} className="text-xs text-white/50">
                    {t.name} — owes {Number(t.arrears).toLocaleString()},
                    charge {Number(t.amount).toLocaleString()}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="flex justify-end">
            <Button type="button" onClick={doRun} isLoading={isRunning}
                    leftIcon={<PlayCircle className="h-4 w-4" />}>
              Run now
            </Button>
          </div>
        </div>
      )}

      <p className="text-xs text-white/40">
        The nightly job applies these automatically at 02:30 — running here is
        only for catching up.
      </p>
    </div>
  );
}
