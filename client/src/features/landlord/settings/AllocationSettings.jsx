import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
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
  useGetAutomationSettingsQuery,
  useUpdateAutomationSettingsMutation,
} from "./settingsApiSlice";
import {
  useGetAllocationMethodQuery,
  useSetAllocationMethodMutation,
  useGetCommissionRulesQuery,
  useSaveCommissionRuleMutation,
  useDeleteCommissionRuleMutation,
  useGetPaymentSourcesQuery,
  useCreatePaymentSourceMutation,
} from "@/features/landlord/allocation/allocationApiSlice";

// sahilpay_payment_allocation_spec.md §7 — allocation method, tax withholding,
// three-level commission, and the paybills money arrives through.
//
// Mobile-first throughout: every control is full-width and stacked by default,
// only spreading out from sm.

export default function AllocationSettings() {
  const { data: settings, isLoading } = useGetAllocationMethodQuery();
  const [saveSettings, { isLoading: savingSettings }] = useSetAllocationMethodMutation();

  const { data: rules } = useGetCommissionRulesQuery();
  const [saveRule, { isLoading: savingRule }] = useSaveCommissionRuleMutation();
  const [deleteRule] = useDeleteCommissionRuleMutation();

  const { data: sources } = useGetPaymentSourcesQuery();
  const [createSource] = useCreatePaymentSourceMutation();

  const { data: propertiesData } = useGetPropertiesQuery({ per_page: 200 });
  // toRows() is the platform's one adapter for list responses — the API keys
  // each list by its entity name rather than a generic `items`, so guessing at
  // the shape here is how you end up calling .map on an object.
  const properties = toRows(propertiesData);

  const [draftRule, setDraftRule] = useState({
    scope_type: "landlord", scope_id: "", rate_type: "percentage", rate_value: "",
  });
  const [draftSource, setDraftSource] = useState({
    label: "", shortcode: "", mapped_property_id: "",
  });

  if (isLoading || !settings) return <SkeletonForm fields={5} />;

  const update = async (patch, message) => {
    try {
      await saveSettings(patch).unwrap();
      toast(message, { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not save.", { type: "error" });
    }
  };

  const addRule = async () => {
    try {
      await saveRule({
        scope_type: draftRule.scope_type,
        scope_id: draftRule.scope_type === "landlord" ? null : Number(draftRule.scope_id),
        rate_type: draftRule.rate_type,
        rate_value: draftRule.rate_value,
      }).unwrap();
      toast("Commission rule saved.", { type: "success" });
      setDraftRule({ scope_type: "landlord", scope_id: "", rate_type: "percentage", rate_value: "" });
    } catch (err) {
      toast(err?.data?.error || "Could not save that rule.", { type: "error" });
    }
  };

  const addSource = async () => {
    try {
      await createSource({
        label: draftSource.label,
        shortcode: draftSource.shortcode,
        mapped_property_id: draftSource.mapped_property_id
          ? Number(draftSource.mapped_property_id) : null,
      }).unwrap();
      toast("Paybill added.", { type: "success" });
      setDraftSource({ label: "", shortcode: "", mapped_property_id: "" });
    } catch (err) {
      toast(err?.data?.error || "Could not add that paybill.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      {/* --- How payments are matched ------------------------------------ */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <div>
          <h3 className="text-base font-medium text-white">How tenants reference payments</h3>
          <p className="mt-1 text-sm text-white/50">
            This decides how an incoming M-Pesa payment finds the right unit.
          </p>
        </div>

        <div className="space-y-3">
          {(settings.options ?? []).map((option) => {
            const selected = settings.allocation_method === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => update({ allocation_method: option.value },
                                      `Payments will now be matched by ${option.label.toLowerCase()}.`)}
                disabled={savingSettings}
                className={[
                  "w-full rounded-lg border p-4 text-left transition-colors",
                  selected
                    ? "border-secondary/60 bg-secondary/10"
                    : "border-white/10 hover:bg-white/5",
                ].join(" ")}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-white">{option.label}</span>
                  {option.value === "unit_code" && <Badge color="third">Recommended</Badge>}
                  {selected && <Badge color="secondary">Current</Badge>}
                </div>
                <p className="mt-1 text-sm text-white/50">{option.description}</p>
              </button>
            );
          })}
        </div>

        {settings.allocation_method === "phone" && (
          <p className="text-xs text-white/40">
            A tenant renting more than one unit can&apos;t be matched to a single unit
            by phone alone, so those payments wait in &ldquo;Payments to review&rdquo;
            with a suggested split rather than being guessed at.
          </p>
        )}
      </div>

      {/* --- Tax withholding --------------------------------------------- */}
      <div className="glass space-y-3 p-5 sm:p-6">
        <h3 className="text-base font-medium text-white">Rental income tax</h3>
        <p className="text-sm text-white/50">
          Monthly Rental Income is 7.5% of rent collected. By default it is shown
          on payout statements for the landlord&apos;s own filing and is not deducted.
        </p>
        <Checkbox
          label="Withhold the 7.5% from payouts instead of only showing it"
          checked={Boolean(settings.tax_withholding_enabled)}
          onChange={(e) => update({ tax_withholding_enabled: e.target.checked },
                                  e.target.checked
                                    ? "Tax will now be withheld from payouts."
                                    : "Tax will be shown but not deducted.")}
        />
      </div>

      {/* --- Commission --------------------------------------------------- */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <div>
          <h3 className="text-base font-medium text-white">Commission</h3>
          <p className="mt-1 text-sm text-white/50">
            Charged on rent collected only — never on deposits or utilities. The
            most specific rule wins: a unit overrides its property, which overrides
            the whole account.
          </p>
        </div>

        <div className="space-y-2">
          {(rules ?? []).map((rule) => (
            <div key={rule.id}
                 className="flex flex-col gap-2 rounded-lg border border-white/10 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-sm text-white">
                  {rule.rate_type === "fixed"
                    ? `KES ${Number(rule.rate_value).toLocaleString()}`
                    : `${Number(rule.rate_value)}%`}
                  <span className="text-white/40"> · {rule.scope_name}</span>
                </div>
                <div className="text-xs text-white/30">{rule.scope_type} rule</div>
              </div>
              <Button type="button" variant="ghost" className="shrink-0"
                      onClick={() => deleteRule(rule.id)} aria-label="Remove rule">
                <Trash2 size={14} />
              </Button>
            </div>
          ))}
        </div>

        <div className="space-y-3 border-t border-white/10 pt-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Select
              label="Applies to"
              value={draftRule.scope_type}
              onChange={(e) => setDraftRule((d) => ({ ...d, scope_type: e.target.value, scope_id: "" }))}
              options={[
                { value: "landlord", label: "The whole account" },
                { value: "property", label: "One property" },
              ]}
            />
            {draftRule.scope_type === "property" && (
              <Select
                label="Property"
                value={draftRule.scope_id}
                onChange={(e) => setDraftRule((d) => ({ ...d, scope_id: e.target.value }))}
                placeholder="Choose a property"
                options={properties.map((p) => ({ value: p.id, label: p.name }))}
              />
            )}
            <Select
              label="Rate type"
              value={draftRule.rate_type}
              onChange={(e) => setDraftRule((d) => ({ ...d, rate_type: e.target.value }))}
              options={[
                { value: "percentage", label: "Percentage of rent collected" },
                { value: "fixed", label: "Fixed amount per period" },
              ]}
            />
            <Input
              label={draftRule.rate_type === "fixed" ? "Amount (KES)" : "Percentage"}
              type="number"
              value={draftRule.rate_value}
              onChange={(e) => setDraftRule((d) => ({ ...d, rate_value: e.target.value }))}
            />
          </div>
          <Button type="button" className="w-full sm:w-auto" onClick={addRule}
                  isLoading={savingRule} disabled={!draftRule.rate_value}>
            <Plus size={14} className="mr-1" /> Save commission rule
          </Button>
        </div>
      </div>

      {/* --- Paybills ------------------------------------------------------ */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <div>
          <h3 className="text-base font-medium text-white">Paybills and tills</h3>
          <p className="mt-1 text-sm text-white/50">
            Only needed if different properties collect to different numbers.
            Mapping a paybill to a property lets us route its payments straight there.
          </p>
        </div>

        <div className="space-y-2">
          {(sources ?? []).map((source) => (
            <div key={source.id} className="rounded-lg border border-white/10 p-3 text-sm">
              <div className="text-white">{source.label}</div>
              <div className="text-xs text-white/40">
                {source.shortcode || "no shortcode"}
                {source.mapped_property_name ? ` → ${source.mapped_property_name}` : ""}
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-3 border-t border-white/10 pt-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Input label="Name" value={draftSource.label}
                   onChange={(e) => setDraftSource((d) => ({ ...d, label: e.target.value }))} />
            <Input label="Paybill / till number" value={draftSource.shortcode}
                   onChange={(e) => setDraftSource((d) => ({ ...d, shortcode: e.target.value }))} />
            <Select
              label="Collects for"
              value={draftSource.mapped_property_id}
              onChange={(e) => setDraftSource((d) => ({ ...d, mapped_property_id: e.target.value }))}
              placeholder="Any property"
              options={properties.map((p) => ({ value: p.id, label: p.name }))}
            />
          </div>
          <Button type="button" variant="ghost" className="w-full sm:w-auto"
                  onClick={addSource} disabled={!draftSource.label.trim()}>
            <Plus size={14} className="mr-1" /> Add paybill
          </Button>
        </div>
      </div>

      <AutoReceiptCard />
    </div>
  );
}

// Receipts for payments that arrive and allocate with nobody watching —
// Co-pilot matching an M-Pesa SMS, or M-Pesa reconciliation. Lives here rather
// than in its own tab because it is the same mental model as allocation: what
// happens to money that arrives on its own.
//
// A payment that lands in the review queue deliberately sends NOTHING. Telling
// a tenant "we have your money but don't know what it is for" produces exactly
// the phone call the review queue exists to prevent.
function AutoReceiptCard() {
  const { data, isLoading } = useGetAutomationSettingsQuery();
  const [save, { isLoading: isSaving }] = useUpdateAutomationSettingsMutation();

  const settings = data?.data ?? data ?? {};
  const enabled = Boolean(settings.auto_receipt_enabled);

  const update = async (patch) => {
    try {
      await save({ ...patch }).unwrap();
    } catch (err) {
      toast(err?.data?.error || "Could not save this setting.", { type: "error" });
    }
  };

  if (isLoading) return <SkeletonForm fields={3} />;

  return (
    <div className="glass space-y-4 p-6">
      <div>
        <h3 className="text-base font-medium text-white">Automatic payment receipts</h3>
        <p className="mt-1 text-sm leading-relaxed text-white/50">
          When a payment arrives and is matched automatically, send the tenant
          their receipt without anyone having to press anything.
        </p>
      </div>

      <Checkbox
        name="auto_receipt_enabled"
        label="Send receipts for automatically matched payments"
        checked={enabled}
        disabled={isSaving}
        onChange={(e) => update({ auto_receipt_enabled: e.target.checked })}
      />

      {enabled && (
        <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-sm text-white/70">Send by</p>
          <Checkbox
            name="auto_receipt_email"
            label="Email — the full itemised receipt as a PDF"
            checked={Boolean(settings.auto_receipt_email)}
            disabled={isSaving}
            onChange={(e) => update({ auto_receipt_email: e.target.checked })}
          />
          <Checkbox
            name="auto_receipt_sms"
            label="SMS — a breakdown, the balance, and a link to the receipt"
            checked={Boolean(settings.auto_receipt_sms)}
            disabled={isSaving}
            onChange={(e) => update({ auto_receipt_sms: e.target.checked })}
          />
          <p className="-mt-1 pl-7 text-xs text-white/40">
            SMS is charged per message from your balance. Email and in-app are free.
          </p>
          <Checkbox
            name="auto_receipt_in_app"
            label="In the tenant's portal"
            checked={Boolean(settings.auto_receipt_in_app)}
            disabled={isSaving}
            onChange={(e) => update({ auto_receipt_in_app: e.target.checked })}
          />
        </div>
      )}

      <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-xs text-white/50">
        Payments held in the review queue send nothing until someone allocates
        them — a tenant should never be told their money arrived without being
        told what it paid for.
      </div>
    </div>
  );
}
